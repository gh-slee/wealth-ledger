"""Immutable holdings observations, frozen FX, and contribution-aware returns.

Only the Python standard library is required. Decimal values cross the public
API as strings. Source files and observations are never updated in place.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path

from .source_formats import WS_REQUIRED as REQUIRED

getcontext().prec = 60
D = Decimal
ZERO = D(0)
TOLERANCE = D("0.01")
ACCOUNT_ORDER = {"TFSA": 0, "RRSP": 1, "Non-registered": 2}


def _decimal(value):
    number = D(str(value))
    if not number.is_finite():
        raise ValueError("Amounts and rates must be finite")
    return number


def _string(value):
    if value is None:
        return None
    number = _decimal(value)
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _serialize(value):
    if isinstance(value, D):
        return _string(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _json(value):
    return json.dumps(_serialize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connection(project):
    db = Path(project) / "data/db/portfolio.sqlite3"
    if not db.exists():
        initialize(project)
    db.chmod(0o600)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize(project: Path):
    project = Path(project)
    for directory in ("data/db", "data/raw/holdings", "data/raw/activity", "work"):
        (project / directory).mkdir(parents=True, exist_ok=True)
    db = project / "data/db/portfolio.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS schema_info(version INTEGER NOT NULL);
        INSERT INTO schema_info SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_info);
        CREATE TABLE IF NOT EXISTS sources(
          id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL,
          semantic_hash TEXT NOT NULL, filename TEXT NOT NULL,
          path TEXT NOT NULL, row_count INTEGER NOT NULL, imported_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS accounts(
          account_id TEXT PRIMARY KEY, account_type TEXT NOT NULL,
          label TEXT NOT NULL, masked_number TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots(
          id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
          as_of TEXT NOT NULL, as_of_utc TEXT NOT NULL, kind TEXT NOT NULL,
          revision INTEGER NOT NULL, supersedes_id INTEGER REFERENCES snapshots(id),
          fx_json TEXT NOT NULL, issues_json TEXT NOT NULL,
          is_complete INTEGER NOT NULL, missing_json TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(as_of_utc,revision));
        CREATE TABLE IF NOT EXISTS positions(
          snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
          account_id TEXT NOT NULL REFERENCES accounts(account_id),
          security_id TEXT NOT NULL, payload_json TEXT NOT NULL,
          PRIMARY KEY(snapshot_id,account_id,security_id));
        CREATE TABLE IF NOT EXISTS cash_flows(
          flow_id TEXT PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
          flow_date TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES accounts(account_id),
          flow_type TEXT NOT NULL, amount_cad TEXT NOT NULL,
          transfer_id TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS flow_periods(
          id INTEGER PRIMARY KEY, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
          account_id TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS snapshots_asof ON snapshots(as_of_utc);
        CREATE INDEX IF NOT EXISTS cash_flow_date ON cash_flows(flow_date);
        """)
    db.chmod(0o600)
    return {"database": str(db), "schema_version": 1}


def _issue(code, message, severity="warning", **context):
    return {"code": code, "severity": severity, "message": message, **context}


def _parse_holdings(path):
    from .source_formats import parse_wealthsimple
    raw = Path(path).read_bytes()
    _, as_of, records, accounts, findings = parse_wealthsimple(raw)
    messages = {
        "market_math": "數量乘市價與來源市值不一致，保留來源值。",
        "unrealized_math": "來源未實現損益與市值減成本不一致，保留來源值。",
        "nonpositive_cost_quantity": "成本或數量非正；以非正數為分母的比例／平均成本不計算。",
    }
    issues = [_issue(item["code"], messages[item["code"]], item["severity"],
                     **{key: value for key, value in item.items() if key not in {"code", "severity"}})
              for item in findings]
    return raw, as_of, records, accounts, issues


def _fx(fx, as_of):
    required = ("usd_cad", "usd_twd", "usd_cad_date", "usd_twd_date",
                "usd_cad_source", "usd_twd_source")
    if any(key not in fx for key in required):
        raise ValueError("FX requires rates, effective dates, and sources")
    result = {key: str(fx[key]) for key in required}
    for key in ("usd_cad", "usd_twd"):
        if _decimal(result[key]) <= 0:
            raise ValueError("FX rates must be positive")
        result[key] = _string(result[key])
        effective = date.fromisoformat(result[key + "_date"])
        if effective > as_of.date():
            raise ValueError("FX effective date cannot follow the snapshot date")
        if not result[key + "_source"]:
            raise ValueError("FX source cannot be empty")
    result["cad_twd"] = _string(_decimal(result["usd_twd"]) / _decimal(result["usd_cad"]))
    return result


def _archive(project, path, raw, category, effective_date):
    folder = Path(project) / "data/raw" / category / effective_date.strftime("%Y/%m")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / Path(path).name
    if destination.exists() and destination.read_bytes() != raw:
        destination = folder / (Path(path).stem + "_" + _hash(raw)[:12] + Path(path).suffix)
    if not destination.exists():
        with destination.open("xb") as handle:
            handle.write(raw)
        destination.chmod(0o400)
    elif destination.read_bytes() != raw:
        raise ValueError("Archive collision; refusing to overwrite a source")
    destination.chmod(0o400)
    return str(destination.relative_to(Path(project)))


def _holdings_plan(conn, parsed, kind):
    """Share identity, revision and account checks without requiring exchange rates."""
    if kind not in ("baseline", "monthly", "interim"):
        raise ValueError("Snapshot kind must be baseline, monthly, or interim")
    raw, as_of, records, accounts, issues = parsed
    utc = as_of.astimezone(timezone.utc).isoformat(timespec="seconds")
    semantic = _hash(_json({"as_of": utc, "accounts": accounts,
                            "records": sorted(records, key=lambda r: (r["account_id"], r["security_id"]))}).encode())
    sha = _hash(raw)
    duplicate = conn.execute("SELECT s.id,s.fx_json FROM snapshots s JOIN sources o ON o.id=s.source_id WHERE o.sha256=? OR o.semantic_hash=? ORDER BY s.id DESC LIMIT 1", (sha, semantic)).fetchone() if conn else None
    if duplicate:
        return {"snapshot_id": duplicate["id"], "status": "duplicate",
                "fx_preserved": json.loads(duplicate["fx_json"]), "sha256": sha}
    first = conn.execute("SELECT * FROM snapshots ORDER BY as_of_utc,id LIMIT 1").fetchone() if conn else None
    if first and utc < first["as_of_utc"]:
        raise ValueError("Backfill before the tracking baseline is disabled")
    prior = conn.execute("SELECT * FROM snapshots WHERE as_of_utc=? ORDER BY revision DESC LIMIT 1", (utc,)).fetchone() if conn else None
    if first and kind == "baseline" and utc != first["as_of_utc"]:
        raise ValueError("The baseline cannot be reassigned to a later date")
    if prior:
        kind = prior["kind"]
    elif not first:
        kind = "baseline"
    known = {row["account_id"] for row in conn.execute("SELECT account_id FROM accounts")} if conn else set()
    for account in accounts.values():
        existing = conn.execute("SELECT account_type FROM accounts WHERE account_id=?", (account["account_id"],)).fetchone() if conn else None
        if existing and existing["account_type"] != account["account_type"]:
            raise ValueError("Existing account type changed; review account identity before import")
    missing = sorted(known - set(accounts))
    if missing:
        issues.append(_issue("missing_accounts", "本期缺少已知帳戶；不得視為零或計算完整組合比較。", missing_account_ids=missing))
    return {"status": "revision" if prior else "imported", "kind": kind,
            "revision": prior["revision"] + 1 if prior else 1,
            "supersedes_id": prior["id"] if prior else None, "missing_accounts": missing,
            "sha256": sha, "semantic_hash": semantic, "as_of_utc": utc}


def inspect_holdings(project, csv_path, kind="monthly"):
    """Read structural import eligibility; no database initialization or FX lookup."""
    parsed = _parse_holdings(csv_path)
    raw, as_of, records, accounts, issues = parsed
    db = Path(project) / "data/db/portfolio.sqlite3"
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) if db.exists() else None
    if conn:
        conn.row_factory = sqlite3.Row
    try:
        plan = _holdings_plan(conn, parsed, kind)
        if plan["status"] == "duplicate":
            saved = conn.execute("SELECT kind,is_complete,missing_json FROM snapshots WHERE id=?", (plan["snapshot_id"],)).fetchone()
            plan.update(kind=saved["kind"], missing_accounts=json.loads(saved["missing_json"]))
        return _serialize({**plan, "as_of": as_of.isoformat(timespec="seconds"),
                           "rows": len(records), "account_count": len(accounts),
                           "accounts": list(accounts.values()), "issues": issues,
                           "is_complete": not plan["missing_accounts"]})
    finally:
        if conn:
            conn.close()


def import_holdings(project: Path, csv_path: Path, kind: str, fx: dict) -> dict:
    if kind not in ("baseline", "monthly", "interim"):
        raise ValueError("Snapshot kind must be baseline, monthly, or interim")
    raw, as_of, records, accounts, issues = _parse_holdings(csv_path)
    frozen_fx = _fx(fx, as_of)
    with _connection(project) as conn:
        plan = _holdings_plan(conn, (raw, as_of, records, accounts, issues), kind)
        if plan["status"] == "duplicate":
            return {key: plan[key] for key in ("snapshot_id", "status", "fx_preserved", "sha256")}
        sha, semantic, utc = plan["sha256"], plan["semantic_hash"], plan["as_of_utc"]
        kind, missing = plan["kind"], plan["missing_accounts"]
        labels = defaultdict(list)
        for account in accounts.values():
            labels[account["account_type"]].append(account)
        for group in labels.values():
            if len(group) > 1:
                for account in group:
                    account["label"] += " " + account["masked_number"]
        for record in records:
            if record["security_type"] == "CURRENCY":
                expected = record["book_native"] * (_decimal(frozen_fx["usd_cad"]) if record["currency"] == "USD" else D(1))
                difference = abs(record["book_cad"] - expected)
                # Tiny FX movement is normal; a large cash cost/value mismatch is not silently repaired.
                if difference > max(TOLERANCE, abs(expected) * D("0.10")):
                    issues.append(_issue("cash_cad_book_anomaly", "現金 CAD 帳面成本與現金值不相稱；保留原值，估值採原幣市值。", account_id=record["account_id"], symbol=record["symbol"], reported_book_cad=_string(record["book_cad"]), reference_cad=_string(expected)))
        archive = _archive(project, csv_path, raw, "holdings", as_of.date())
        source_id = conn.execute("INSERT INTO sources(sha256,semantic_hash,filename,path,row_count,imported_at) VALUES(?,?,?,?,?,?)", (sha, semantic, Path(csv_path).name, archive, len(records), _now())).lastrowid
        for account in accounts.values():
            conn.execute("INSERT INTO accounts VALUES(?,?,?,?) ON CONFLICT(account_id) DO NOTHING", (account["account_id"], account["account_type"], account["label"], account["masked_number"]))
        revision = plan["revision"]
        snapshot_id = conn.execute("INSERT INTO snapshots(source_id,as_of,as_of_utc,kind,revision,supersedes_id,fx_json,issues_json,is_complete,missing_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (source_id, as_of.isoformat(timespec="seconds"), utc, kind, revision, plan["supersedes_id"], _json(frozen_fx), _json(issues), not missing, _json(missing), _now())).lastrowid
        for record in records:
            conn.execute("INSERT INTO positions VALUES(?,?,?,?)", (snapshot_id, record["account_id"], record["security_id"], _json(record)))
    return {"snapshot_id": snapshot_id, "status": plan["status"],
            "revision": revision, "is_complete": not missing, "issues": issues,
            "sha256": sha, "source_path": archive}


def _ratio(numerator, denominator):
    return numerator / denominator if denominator > 0 else None


def _missing_official_months(history):
    if not history:
        return []
    months = [row["as_of"][:7] for row in history]
    first, last = min(months), max(months)
    available = {row["as_of"][:7] for row in history
                 if row["kind"] in ("baseline", "monthly") and row["is_complete"]}
    year, month = map(int, first.split("-"))
    result = []
    while f"{year:04d}-{month:02d}" <= last:
        key = f"{year:04d}-{month:02d}"
        if key not in available:
            result.append(key)
        year, month = (year+1, 1) if month == 12 else (year, month+1)
    return result


def _convert(cad, usd, fx):
    r, s = _decimal(fx["usd_cad"]), _decimal(fx["usd_twd"])
    return {"native_cad": cad, "native_usd": usd, "total_cad": cad + usd * r,
            "total_usd": cad / r + usd, "total_twd": (cad / r + usd) * s}


def _summary(records, fx):
    sums = defaultdict(lambda: ZERO)
    for record in records:
        currency = record["currency"].lower()
        sums["native_" + currency] += _decimal(record["market_native"])
        if record["security_type"] == "CURRENCY":
            sums["cash_native_" + currency] += _decimal(record["market_native"])
        else:
            sums["book_native_" + currency] += _decimal(record["book_native"])
            sums["unrealized_native_" + currency] += _decimal(record["unrealized_native"])
    result = _convert(sums["native_cad"], sums["native_usd"], fx)
    for key in ("cash_native_cad", "cash_native_usd", "book_native_cad", "book_native_usd", "unrealized_native_cad", "unrealized_native_usd"):
        result[key] = sums[key]
    result["cash_cad"] = _convert(sums["cash_native_cad"], sums["cash_native_usd"], fx)["total_cad"]
    result["cash_ratio"] = _ratio(result["cash_cad"], result["total_cad"])
    return result


def _view(conn, snapshot):
    fx = json.loads(snapshot["fx_json"])
    records = [json.loads(row["payload_json"]) for row in conn.execute("SELECT payload_json FROM positions WHERE snapshot_id=? ORDER BY account_id,security_id", (snapshot["id"],))]
    totals = _summary(records, fx)
    account_records = defaultdict(list)
    for record in records:
        account_records[record["account_id"]].append(record)
    accounts = []
    for aid, group in account_records.items():
        account = dict(conn.execute("SELECT * FROM accounts WHERE account_id=?", (aid,)).fetchone())
        account.update(_summary(group, fx))
        account["position_count"] = sum(r["security_type"] != "CURRENCY" for r in group)
        account["security_count"] = account["position_count"]
        account["portfolio_weight"] = _ratio(account["total_cad"], totals["total_cad"])
        accounts.append(account)
    accounts.sort(key=lambda a: (ACCOUNT_ORDER.get(a["account_type"], 99), a["label"], a["account_id"]))
    account_lookup = {a["account_id"]: a for a in accounts}
    for record in records:
        for key in ("quantity", "price", "book_native", "book_cad", "market_native", "unrealized_native"):
            record[key] = _decimal(record[key])
        values = _convert(record["market_native"] if record["currency"] == "CAD" else ZERO, record["market_native"] if record["currency"] == "USD" else ZERO, fx)
        record.update({"market_cad": values["total_cad"], "market_usd": values["total_usd"], "market_twd": values["total_twd"],
                       "avg_cost": _ratio(record["book_native"], record["quantity"]),
                       "unrealized_pct": _ratio(record["unrealized_native"], record["book_native"]),
                       "account_weight": _ratio(values["total_cad"], account_lookup[record["account_id"]]["total_cad"]),
                       "portfolio_weight": _ratio(values["total_cad"], totals["total_cad"]),
                       "account_label": account_lookup[record["account_id"]]["label"]})
    positions = [r for r in records if r["security_type"] != "CURRENCY"]
    cash = [r for r in records if r["security_type"] == "CURRENCY"]
    grouped = defaultdict(list)
    for record in positions:
        grouped[record["security_id"]].append(record)
    securities = []
    for sid, group in grouped.items():
        security = dict(group[0])
        security.update({"account_id": None, "account_type": "ALL", "account_label": "全部帳戶", "account_weight": None,
                         "account_count": len(group), "held_account_ids": [r["account_id"] for r in group]})
        for key in ("quantity", "book_native", "book_cad", "market_native", "unrealized_native", "market_cad", "market_usd", "market_twd"):
            security[key] = sum((r[key] for r in group), ZERO)
        security["avg_cost"] = _ratio(security["book_native"], security["quantity"])
        security["price"] = _ratio(security["market_native"], security["quantity"])
        security["unrealized_pct"] = _ratio(security["unrealized_native"], security["book_native"])
        security["portfolio_weight"] = _ratio(security["market_cad"], totals["total_cad"])
        securities.append(security)
    securities.sort(key=lambda r: (-r["market_cad"], r["security_id"]))
    return {"fx": fx, "accounts": accounts, "positions": positions, "securities": securities, "cash_rows": cash, "totals": totals}


def _active_snapshots(conn, until=None):
    query = "SELECT * FROM snapshots WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY as_of_utc)"
    params = ()
    if until:
        query += " AND as_of_utc<=?"
        params = (until,)
    return conn.execute(query + " ORDER BY as_of_utc,id", params).fetchall()


def _changes(previous, current, prior_snapshot, current_snapshot):
    result = {"available": False, "reason": "尚無適用的前期完整快照。", "previous_snapshot_id": None, "previous_as_of": None, "current_as_of": current_snapshot["as_of"], "totals": {}, "accounts": [], "positions": []}
    if previous is None:
        return result
    result["previous_snapshot_id"] = prior_snapshot["id"]
    result["previous_as_of"] = prior_snapshot["as_of"]
    if not prior_snapshot["is_complete"] or not current_snapshot["is_complete"]:
        result["reason"] = "本期或前期缺少已知帳戶，暫不計算完整比較。"
        return result
    if {a["account_id"] for a in previous["accounts"]} != {a["account_id"] for a in current["accounts"]}:
        result["reason"] = "帳戶範圍改變，暫不視為相同組合的成長比較。"
        return result
    result.update({"available": True, "reason": "資產值變化含資金流及匯率；不是期間投資報酬。"})
    for currency in ("cad", "usd", "twd"):
        key = "total_" + currency
        opening, closing = previous["totals"][key], current["totals"][key]
        result["totals"][key] = {"previous": opening, "current": closing, "change": closing - opening, "change_pct": _ratio(closing - opening, opening)}
    prior_accounts = {a["account_id"]: a for a in previous["accounts"]}
    for account in current["accounts"]:
        old = prior_accounts[account["account_id"]]
        result["accounts"].append({"account_id": account["account_id"], "label": account["label"], "previous_cad": old["total_cad"], "current_cad": account["total_cad"], "change_cad": account["total_cad"] - old["total_cad"], "weight_change": account["portfolio_weight"] - old["portfolio_weight"]})
    old = {(p["account_id"], p["security_id"]): p for p in previous["positions"]}
    new = {(p["account_id"], p["security_id"]): p for p in current["positions"]}
    for key in sorted(set(old) | set(new)):
        p, q = old.get(key), new.get(key)
        row = q or p
        result["positions"].append({"account_id": row["account_id"], "account_label": row["account_label"], "security_id": row["security_id"], "symbol": row["symbol"], "currency": row["currency"], "status": "new" if p is None else "removed" if q is None else "held", "previous_quantity": p["quantity"] if p else ZERO, "quantity": q["quantity"] if q else ZERO, "quantity_change": (q["quantity"] if q else ZERO) - (p["quantity"] if p else ZERO), "market_change_cad": (q["market_cad"] if q else ZERO) - (p["market_cad"] if p else ZERO), "price_change": q["price"] - p["price"] if p and q else None, "weight_change": (q["portfolio_weight"] if q else ZERO) - (p["portfolio_weight"] if p else ZERO)})
    return result


def _xirr(flows):
    """Conservative annualized IRR: suppress ambiguous sign-changing schedules."""
    grouped = defaultdict(lambda: ZERO)
    for day, amount in flows:
        grouped[day] += amount
    items = [(day, amount) for day, amount in sorted(grouped.items()) if amount]
    if len(items) < 2 or items[-1][0] <= items[0][0]:
        return None, "insufficient_dates"
    signs = [amount > 0 for _, amount in items]
    if sum(a != b for a, b in zip(signs, signs[1:])) != 1:
        return None, "ambiguous_cash_flow_signs"
    start = items[0][0]
    exponents = [D((day - start).days) / D(365) for day, _ in items]
    def npv(rate):
        return sum((amount / ((D(1) + rate) ** exponent) for (_, amount), exponent in zip(items, exponents)), ZERO)
    low, high = D("-0.999999999"), D(1)
    left = npv(low)
    right = npv(high)
    while left * right > 0 and high < D("1000000000"):
        high = high * 2 + 1
        right = npv(high)
    if left * right > 0:
        return None, "no_bracketed_solution"
    for _ in range(160):
        mid = (low + high) / 2
        value = npv(mid)
        if abs(value) < D("0.000000001") or high - low < D("0.000000000001"):
            return mid, "calculated"
        if left * value <= 0:
            high = mid
        else:
            low, left = mid, value
    return (low + high) / 2, "calculated"


def mark_flow_period(project: Path, start_date: str, end_date: str, status: str,
                     account_id: str = "portfolio"):
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if start >= end or status not in ("partial", "complete", "no_external"):
        raise ValueError("Need increasing dates and partial/complete/no_external status")
    with _connection(project) as conn:
        if account_id != "portfolio" and not conn.execute("SELECT 1 FROM accounts WHERE account_id=?", (account_id,)).fetchone():
            raise ValueError("Unknown account ID")
        record_id = conn.execute("INSERT INTO flow_periods(start_date,end_date,account_id,status,created_at) VALUES(?,?,?,?,?)", (start_date, end_date, account_id, status, _now())).lastrowid
    return {"id": record_id, "start_date": start_date, "end_date": end_date, "account_id": account_id, "status": status}


def import_cash_flows(project: Path, csv_path: Path):
    raw = Path(csv_path).read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = {"date", "account_id", "flow_type", "currency", "amount"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("Cash-flow CSV requires date, account_id, flow_type, currency, amount")
    rows = []
    pending_by_id = {}
    with _connection(project) as conn:
        for source in reader:
            row = {key: (value or "").strip() for key, value in source.items() if key is not None}
            if not any(row.values()):
                continue
            day = date.fromisoformat(row["date"])
            if not conn.execute("SELECT 1 FROM accounts WHERE account_id=?", (row["account_id"],)).fetchone():
                raise ValueError("Cash flow references an unknown account")
            if row["flow_type"] not in ("deposit", "withdrawal", "transfer_in", "transfer_out", "income", "fee", "internal"):
                raise ValueError("Unsupported cash-flow type")
            if row["currency"] not in ("CAD", "USD") or _decimal(row["amount"]) <= 0:
                raise ValueError("Cash-flow amount must be positive CAD or USD")
            amount = _decimal(row["amount"])
            if row["currency"] == "CAD":
                amount_cad = amount
            elif row.get("usd_cad"):
                rate = _decimal(row["usd_cad"])
                if rate <= 0 or not row.get("fx_date") or not row.get("fx_source"):
                    raise ValueError("USD flow conversion requires positive rate, fx_date, fx_source")
                if date.fromisoformat(row["fx_date"]) > day:
                    raise ValueError("Cash-flow FX date cannot be in the future")
                amount_cad = amount * rate
            elif row.get("amount_cad"):
                amount_cad = _decimal(row["amount_cad"])
                if amount_cad <= 0 or not row.get("fx_source"):
                    raise ValueError("Explicit USD flow CAD value requires positive amount and source")
            else:
                raise ValueError("USD flow needs date-specific FX or an explicit sourced CAD value")
            if row.get("amount_cad") and abs(_decimal(row["amount_cad"]) - amount_cad) > TOLERANCE:
                raise ValueError("Cash-flow CAD value disagrees with rate")
            if row["flow_type"].startswith("transfer_") and not row.get("transfer_id"):
                raise ValueError("Transfers require a pairing transfer_id")
            row.update({"amount": _string(amount), "amount_cad": _string(amount_cad)})
            semantic = _hash(_json({key: value for key, value in row.items() if key != "flow_id"}).encode())
            row["flow_id"] = row.get("flow_id") or "f_" + semantic[:24]
            pending = pending_by_id.get(row["flow_id"])
            if pending is not None and pending != row:
                raise ValueError("Conflicting duplicate flow ID within the same CSV")
            pending_by_id[row["flow_id"]] = row
            existing = conn.execute("SELECT payload_json FROM cash_flows WHERE flow_id=?", (row["flow_id"],)).fetchone()
            if existing and json.loads(existing[0]) != row:
                raise ValueError("Conflicting existing flow ID; automatic cash-flow corrections are not supported")
            rows.append(row)
        if not rows:
            raise ValueError("Empty cash-flow CSV; confirm no flows through mark_flow_period")
        sha, semantic = _hash(raw), _hash(_json(sorted(rows, key=lambda r: r["flow_id"])).encode())
        source = conn.execute("SELECT id FROM sources WHERE sha256=?", (sha,)).fetchone()
        if source:
            return {"status": "duplicate", "imported": 0, "sha256": sha}
        archive = _archive(project, csv_path, raw, "activity", date.fromisoformat(min(r["date"] for r in rows)))
        sid = conn.execute("INSERT INTO sources(sha256,semantic_hash,filename,path,row_count,imported_at) VALUES(?,?,?,?,?,?)", (sha, semantic, Path(csv_path).name, archive, len(rows), _now())).lastrowid
        imported = 0
        for row in rows:
            cursor = conn.execute("INSERT OR IGNORE INTO cash_flows VALUES(?,?,?,?,?,?,?,?,?)", (row["flow_id"], sid, row["date"], row["account_id"], row["flow_type"], row["amount_cad"], row.get("transfer_id") or None, _json(row), _now()))
            imported += cursor.rowcount
    return {"status": "imported", "imported": imported, "sha256": sha, "source_path": archive}


def _periods(conn, snapshots, views):
    if len(snapshots) < 2:
        return []
    current = snapshots[-1]
    pairs = [snapshots[-2]]
    if snapshots[0]["id"] != snapshots[-2]["id"]:
        pairs.append(snapshots[0])
    result = []
    for opening in pairs:
        start = datetime.fromisoformat(opening["as_of"]).date()
        end = datetime.fromisoformat(current["as_of"]).date()
        first, last = views[opening["id"]], views[current["id"]]
        first_accounts = {a["account_id"]: a for a in first["accounts"]}
        last_accounts = {a["account_id"]: a for a in last["accounts"]}
        flows = [json.loads(r[0]) for r in conn.execute("SELECT payload_json FROM cash_flows WHERE flow_date>? AND flow_date<=? ORDER BY flow_date,flow_id", (start.isoformat(), end.isoformat()))]
        pairs_by_id = defaultdict(list)
        for flow in flows:
            if flow["flow_type"].startswith("transfer_"):
                pairs_by_id[flow["transfer_id"]].append(flow)
        bad_transfers = any(len(group) != 2 or {f["flow_type"] for f in group} != {"transfer_in", "transfer_out"} or group[0]["account_id"] == group[1]["account_id"] or group[0]["date"] != group[1]["date"] or abs(_decimal(group[0]["amount_cad"]) - _decimal(group[1]["amount_cad"])) > TOLERANCE for group in pairs_by_id.values())
        scopes = ["portfolio"] + sorted(set(first_accounts) & set(last_accounts))
        for scope in scopes:
            period = {"scope": "portfolio" if scope == "portfolio" else "account", "account_id": None if scope == "portfolio" else scope, "start_as_of": opening["as_of"], "end_as_of": current["as_of"], "status": "not_provided", "available": False, "opening_cad": None, "closing_cad": None, "net_flow_cad": None, "investment_gain_cad": None, "modified_dietz": None, "xirr": None, "xirr_status": "unavailable"}
            coverage_status, coverage = _flow_coverage(conn, start, end, scope)
            period["status"] = coverage_status
            scope_unchanged = set(first_accounts) == set(last_accounts)
            if end <= start or (scope == "portfolio" and (not opening["is_complete"] or not current["is_complete"] or not scope_unchanged)):
                period["status"] = "incomplete_snapshot_or_scope"
            elif bad_transfers:
                period["status"] = "unmatched_transfers"
            elif coverage_status in ("complete", "no_external"):
                period_flows = []
                for flow in flows:
                    if scope != "portfolio" and flow["account_id"] != scope:
                        continue
                    kind = flow["flow_type"]
                    if kind in ("deposit", "withdrawal") or (scope != "portfolio" and kind in ("transfer_in", "transfer_out")):
                        signed = _decimal(flow["amount_cad"]) * (1 if kind in ("deposit", "transfer_in") else -1)
                        period_flows.append((date.fromisoformat(flow["date"]), signed))
                contradicts_no_external = False
                for left, right, declaration in coverage:
                    if declaration["status"] != "no_external":
                        continue
                    for flow in flows:
                        day = date.fromisoformat(flow["date"])
                        if not (left < day <= right) or (scope != "portfolio" and flow["account_id"] != scope):
                            continue
                        # Global no-external allows internal account transfers;
                        # an account-specific declaration excludes its transfers.
                        relevant = flow["flow_type"] in ("deposit", "withdrawal") or (
                            scope != "portfolio" and declaration["account_id"] != "portfolio"
                            and flow["flow_type"] in ("transfer_in", "transfer_out"))
                        contradicts_no_external |= relevant
                if contradicts_no_external:
                    period["status"] = "no_external_conflicts_with_flows"
                else:
                    opening_value = first["totals"]["total_cad"] if scope == "portfolio" else first_accounts[scope]["total_cad"]
                    closing_value = last["totals"]["total_cad"] if scope == "portfolio" else last_accounts[scope]["total_cad"]
                    net = sum((amount for _, amount in period_flows), ZERO)
                    gain = closing_value - opening_value - net
                    days = D((end - start).days)
                    weighted = sum((amount * D((end - day).days) / days for day, amount in period_flows), ZERO)
                    xirr, xirr_status = _xirr([(start, -opening_value), *((day, -amount) for day, amount in period_flows), (end, closing_value)])
                    period.update({"available": True, "opening_cad": opening_value, "closing_cad": closing_value, "net_flow_cad": net, "investment_gain_cad": gain, "modified_dietz": _ratio(gain, opening_value + weighted), "xirr": xirr, "xirr_status": xirr_status})
                    if scope != "portfolio" and coverage_status == "no_external" and period_flows:
                        period["status"] = "complete"
            result.append(period)
    return result


def _flow_coverage(conn, start, end, scope):
    """Resolve explicit declarations on each segment, allowing monthly unions.

    Latest declarations override earlier declarations within the same scope.
    Account-specific declarations override a portfolio-wide declaration.
    A missing segment never becomes implicitly complete.
    """
    records = list(conn.execute("SELECT * FROM flow_periods WHERE end_date>? AND start_date<? AND account_id IN (?, 'portfolio')", (start.isoformat(), end.isoformat(), scope)))
    boundaries = {start, end}
    for record in records:
        boundaries.add(max(start, date.fromisoformat(record["start_date"])))
        boundaries.add(min(end, date.fromisoformat(record["end_date"])))
    ordered = sorted(boundaries)
    segments = []
    statuses = []
    for left, right in zip(ordered, ordered[1:]):
        applicable = [r for r in records if date.fromisoformat(r["start_date"]) <= left and date.fromisoformat(r["end_date"]) >= right]
        if not applicable:
            statuses.append("not_provided")
            continue
        declaration = max(applicable, key=lambda r: (r["account_id"] == scope, r["id"]))
        statuses.append(declaration["status"])
        segments.append((left, right, declaration))
    if not statuses or "not_provided" in statuses:
        return "not_provided", segments
    if "partial" in statuses:
        return "partial", segments
    return ("no_external" if all(status == "no_external" for status in statuses) else "complete"), segments


def _flow_views(conn, until):
    result = []
    for record in conn.execute("SELECT f.payload_json,a.label,a.account_type,s.path,s.filename,s.sha256 FROM cash_flows f JOIN accounts a ON a.account_id=f.account_id JOIN sources s ON s.id=f.source_id WHERE f.flow_date<=? ORDER BY f.flow_date,f.flow_id", (until,)):
        flow = json.loads(record["payload_json"])
        flow.update({"account_label": record["label"], "account_type": record["account_type"],
                     "source_path": record["path"], "source_filename": record["filename"],
                     "source_sha256": record["sha256"]})
        result.append(flow)
    return result


def make_payload(project: Path, snapshot_id: int | None = None) -> dict:
    from .source_ingestion import require_report_projection
    require_report_projection(project)
    with _connection(project) as conn:
        snapshot = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone() if snapshot_id is not None else conn.execute("SELECT * FROM snapshots ORDER BY as_of_utc DESC,revision DESC LIMIT 1").fetchone()
        if not snapshot:
            raise ValueError("No matching holdings snapshot")
        snapshots = _active_snapshots(conn, snapshot["as_of_utc"])
        # Explicit historic revisions remain reproducible even after a correction.
        snapshots = [s for s in snapshots if s["as_of_utc"] != snapshot["as_of_utc"]] + [snapshot]
        views = {s["id"]: _view(conn, s) for s in snapshots}
        view = views[snapshot["id"]]
        previous_snapshot = snapshots[-2] if len(snapshots) > 1 else None
        previous = views[previous_snapshot["id"]] if previous_snapshot else None
        source = dict(conn.execute("SELECT * FROM sources WHERE id=?", (snapshot["source_id"],)).fetchone())
        issues = json.loads(snapshot["issues_json"])
        source_path = Path(project) / source["path"]
        source["integrity_ok"] = source_path.exists() and _hash(source_path.read_bytes()) == source["sha256"]
        if not source["integrity_ok"]:
            issues.append(_issue("source_integrity", "原始來源遺失或雜湊不符；本報告採資料庫保存值，需核對來源備份。", severity="error"))
        securities, accounts, totals = view["securities"], view["accounts"], view["totals"]
        types = defaultdict(list)
        for record in view["positions"] + view["cash_rows"]:
            types[record["security_type"]].append(record)
        type_labels = {"EQUITY": "直接個股", "EXCHANGE_TRADED_FUND": "ETF", "CURRENCY": "現金"}
        instrument_types = [{"security_type": kind, "label": type_labels.get(kind, kind), "total_cad": sum((r["market_cad"] for r in group), ZERO), "weight": _ratio(sum((r["market_cad"] for r in group), ZERO), totals["total_cad"]), "position_count": len(group), "security_count": len({r["security_id"] for r in group})} for kind, group in sorted(types.items())]
        rows = []
        record_groups = defaultdict(list)
        for record in view["positions"] + view["cash_rows"]:
            record_groups[record["security_id"]].append(record)
        for sid, group in record_groups.items():
            cells = {r["account_id"]: r["market_cad"] for r in group}
            rows.append({"security_id": sid, "symbol": group[0]["symbol"], "currency": group[0]["currency"], "is_cash": group[0]["security_type"] == "CURRENCY", "values": {a["account_id"]: cells.get(a["account_id"], ZERO) for a in accounts}, "weights": {a["account_id"]: _ratio(cells.get(a["account_id"], ZERO), a["total_cad"]) for a in accounts}, "total_cad": sum(cells.values(), ZERO)})
        rows.sort(key=lambda r: (r["is_cash"], -r["total_cad"], r["security_id"]))
        concentration = {"largest": None, "top3_weight": ZERO, "top5_weight": ZERO, "top3_cad": ZERO, "top5_cad": ZERO}
        if securities:
            largest = securities[0]
            concentration["largest"] = {"symbol": largest["symbol"], "currency": largest["currency"], "total_cad": largest["market_cad"], "weight": largest["portfolio_weight"]}
        for count in (3, 5):
            total = sum((r["market_cad"] for r in securities[:count]), ZERO)
            concentration[f"top{count}_cad"] = total
            concentration[f"top{count}_weight"] = _ratio(total, totals["total_cad"])
        findings = [f"本期共 {len(accounts)} 個帳戶、{len(securities)} 個不同證券、{len(view['positions'])} 筆證券持倉及 {len(view['cash_rows'])} 筆現金。", "交易幣別與工具類型分類不代表 ETF 底層貨幣、產業或地區曝險。", "未實現損益不含已賣出持倉及完整收入；不是期間或年化投資報酬。"]
        if securities:
            findings.insert(1, f"最大合併持倉為 {securities[0]['symbol']}；集中度依整體資產市值計算，分母包含現金。")
        if len(snapshots) == 1:
            findings.append("已建立追蹤基準；尚無第二期真實快照，不產生成長或期間報酬。")
        if not snapshot["is_complete"]:
            findings.append("本期缺少已知帳戶；總值僅代表已提供資料，不視為完整總資產。")
        official_by_month = {}
        current_month = snapshot["as_of"][:7]
        for candidate in snapshots:
            if candidate["kind"] in ("baseline", "monthly") and candidate["is_complete"]:
                official_by_month[candidate["as_of"][:7]] = candidate
        previous_official = next((official_by_month[month] for month in sorted(official_by_month, reverse=True) if month < current_month), None)
        baseline = snapshots[0] if len(snapshots) > 1 else None
        comparisons = {
            "previous": _changes(previous, view, previous_snapshot, snapshot),
            "previous_month": _changes(views[previous_official["id"]] if previous_official else None, view, previous_official, snapshot),
            "baseline": _changes(views[baseline["id"]] if baseline else None, view, baseline, snapshot),
        }
        payload = {"meta": {"snapshot_id": snapshot["id"], "as_of": snapshot["as_of"], "generated_at": _now(), "kind": snapshot["kind"], "revision": snapshot["revision"], "is_complete": bool(snapshot["is_complete"]), "missing_account_ids": json.loads(snapshot["missing_json"]), "account_count": len(accounts), "security_count": len(securities), "position_count": len(view["positions"]), "cash_row_count": len(view["cash_rows"]), "baseline_as_of": snapshots[0]["as_of"], "base_currency": "CAD", "display_currencies": ["CAD", "USD", "TWD"]}, "source": source, **view,
                   "instrument_types": instrument_types, "matrix": {"accounts": [{"account_id": a["account_id"], "label": a["label"]} for a in accounts], "rows": rows}, "concentration": concentration,
                   "history": [{"snapshot_id": s["id"], "as_of": s["as_of"], "kind": s["kind"], "revision": s["revision"], "is_complete": bool(s["is_complete"]), "totals": views[s["id"]]["totals"], "accounts": views[s["id"]]["accounts"]} for s in snapshots],
                   "changes": comparisons["previous"], "comparisons": comparisons,
                   "cash_flows": _flow_views(conn, datetime.fromisoformat(snapshot["as_of"]).date().isoformat()), "periods": _periods(conn, snapshots, views), "issues": issues, "findings": findings}
        payload["meta"]["official_snapshot_ids"] = [s["id"] for _, s in sorted(official_by_month.items())]
        payload["meta"]["history_snapshot_ids"] = [s["id"] for s in snapshots]
        payload["meta"]["missing_official_months"] = _missing_official_months(payload["history"])
    return _serialize(payload)
