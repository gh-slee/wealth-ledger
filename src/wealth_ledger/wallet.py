"""Append-only BTC-equivalent observations, events, and interval reconciliation."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from .crypto import _time, _now, _json, _account_id, _readonly, _has_tables

from .wallet_reconciliation import SCOPE, SIGNS, STATUS_LABELS, sats, btc, reconcile_wallet

def quantity(value, *, positive=False):
    try:
        with localcontext() as context:
            context.prec = 100
            number = Decimal(str(value))
            units = number * 100000000
            if (not number.is_finite() or number < 0 or (positive and number == 0)
                    or units != units.to_integral_value()):
                raise ValueError("BTC quantity requires nonnegative satoshi precision (positive for events)")
            return format(number, ".8f")
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid BTC quantity") from exc


def timestamp(value, now=None):
    result = _time(value)
    if result > _time(now or _now()):
        raise ValueError("Observation/event timestamp cannot be in the future")
    return result


def _connect(project):
    from .core import initialize
    initialize(project)
    conn = sqlite3.connect(Path(project) / "data/db/portfolio.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS wallet_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT UNIQUE,
        kind TEXT NOT NULL CHECK(kind IN ('balance','event')), scope TEXT NOT NULL,
        source TEXT, reference TEXT, UNIQUE(kind,scope,source,reference));
      CREATE TABLE IF NOT EXISTS wallet_revisions(
        record_id TEXT NOT NULL REFERENCES wallet_records(record_id), revision INTEGER NOT NULL,
        payload_json TEXT NOT NULL, source_path TEXT NOT NULL, sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(record_id,revision));
      CREATE TABLE IF NOT EXISTS wallet_links(
        event_id TEXT NOT NULL, event_revision INTEGER NOT NULL,
        balance_id TEXT NOT NULL REFERENCES wallet_records(record_id),
        previous_balance_id TEXT REFERENCES wallet_records(record_id),
        PRIMARY KEY(event_id,event_revision),
        FOREIGN KEY(event_id,event_revision) REFERENCES wallet_revisions(record_id,revision));
      CREATE TABLE IF NOT EXISTS wallet_balance_slots(
        scope TEXT NOT NULL, as_of TEXT NOT NULL,
        record_id TEXT NOT NULL UNIQUE REFERENCES wallet_records(record_id),
        PRIMARY KEY(scope,as_of));
    """)
    return conn


def records(project, kind=None, *, include_void=True):
    conn = _readonly(project)
    try:
        if conn is None or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='wallet_records'").fetchone():
            return []
        rows = conn.execute("""SELECT r.kind, v.* FROM wallet_records r JOIN wallet_revisions v
            ON r.record_id=v.record_id WHERE v.revision=(SELECT MAX(x.revision)
            FROM wallet_revisions x WHERE x.record_id=v.record_id) ORDER BY r.id""").fetchall()
        result = []
        for row in rows:
            value = json.loads(row["payload_json"])
            if kind and row["kind"] != kind or not include_void and value.get("void"):
                continue
            path = Path(project) / row["source_path"]
            result.append({**value, "record_id": row["record_id"], "revision": row["revision"],
                           "source_path": row["source_path"], "sha256": row["sha256"],
                           "integrity_ok": (value.get('record_id') == row['record_id'] and value.get('revision') == row['revision']
                               and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
                               and hashlib.sha256((_json(value)+'\n').encode()).hexdigest() == row['sha256'])})
        return result
    finally:
        if conn:
            conn.close()


def get_record(project, record_id):
    item = next((row for row in records(project) if row["record_id"] == record_id), None)
    if not item:
        raise ValueError(f"Unknown wallet record ID: {record_id}")
    return item


def has_wallet(project):
    return bool(records(project))


def has_bull(project):
    conn = _readonly(project)
    try:
        return bool(_has_tables(conn) and conn.execute(
            "SELECT 1 FROM crypto_accounts WHERE source_account='bullbitcoin-main'").fetchone())
    finally:
        if conn:
            conn.close()


def _base(project, cutoff):
    if has_bull(project):
        from .crypto import make_crypto_view
        return make_crypto_view(project, cutoff)
    return {
        "meta": {"provider": "wallet", "source_account": "bullbitcoin-main",
                 "account_id": _account_id("bullbitcoin-main"), "as_of": cutoff,
                 "quantity_status": "wallet_only_unknown_history", "completed_order_count": 0,
                 "pending_order_count": 0, "excluded_after_cutoff_count": 0},
        **{key: "0" for key in ("qty_btc", "qty_lbtc", "btc_equivalent_qty", "cash_cad",
                               "total_buy_cost_cad", "total_funding_cad", "purchased_btc_equivalent_qty", "opening_btc_equivalent_qty")},
        "totals": {}, "orders": [], "monthly": [], "opening": None,
        "assumptions": {"btc": None, "lbtc": None, "cad": None,
                        "basis": "No acquisition history supplied", "confirmed_by": "not_provided"},
        "source": {"sources": [], "earliest_created_at": None, "latest_completed_at": None},
        "coverage": {"status": "unknown_history", "absence_outside_range_confirmed": False}, "issues": [],
    }


def _write(conn, project, kind, value, *, record_id=None):
    if record_id is None:
        index = conn.execute("INSERT INTO wallet_records(kind,scope,source,reference) VALUES(?,?,?,?)",
                             (kind, SCOPE, value.get("source") if kind == "event" else None,
                              value.get("reference") if kind == "event" else None)).lastrowid
        record_id = ("B" if kind == "balance" else "E") + f"{index:06d}"
        conn.execute("UPDATE wallet_records SET record_id=? WHERE id=?", (record_id, index))
    revision = conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM wallet_revisions WHERE record_id=?", (record_id,)).fetchone()[0]
    value = {**value, "record_id": record_id, "revision": revision}
    for key in ("source_path", "sha256", "integrity_ok"):
        value.pop(key, None)
    raw = (_json(value) + "\n").encode()
    sha = hashlib.sha256(raw).hexdigest()
    directory = Path(project) / "data/raw/crypto/wallet" / datetime.now(timezone.utc).strftime("%Y/%m")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record_id}-r{revision}-{sha[:16]}.json"
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("Wallet archive collision")
    if not path.exists():
        path.write_bytes(raw)
    path.chmod(0o400)
    conn.execute("INSERT INTO wallet_revisions VALUES(?,?,?,?,?,?)",
                 (record_id, revision, _json(value), str(path.relative_to(project)), sha, _now()))
    if kind=='event' and value.get('balance_id'):
        conn.execute('INSERT INTO wallet_links VALUES(?,?,?,?)',
                     (record_id,revision,value['balance_id'],value.get('linked_previous_balance_id')))
    if kind=='balance':
        if value.get('void'):
            conn.execute('DELETE FROM wallet_balance_slots WHERE record_id=?',(record_id,))
        else:
            conn.execute('INSERT INTO wallet_balance_slots VALUES(?,?,?) ON CONFLICT(record_id) DO NOTHING',
                         (SCOPE,value['as_of'],record_id))
    return {**value, "source_path": str(path.relative_to(project)), "sha256": sha, "integrity_ok": True}


def _replacement(project, kind, replaced):
    if replaced:
        row = get_record(project, replaced)
        if row["kind"] != kind or not row.get("void"):
            raise ValueError("Replacement ID must name a void record of the same kind and scope")


def add_balance(project, amount, as_of, *, source="user_reported_total", time_basis="explicit",
                replaces=None, now=None):
    value = quantity(amount)
    instant = timestamp(as_of, now)
    source = str(source).strip()
    if not source:
        raise ValueError("Balance source cannot be blank")
    _replacement(project, "balance", replaces)
    for old in records(project, "balance", include_void=False):
        if old["as_of"] == instant:
            if old["quantity_btc"] != value or old["source"] != source:
                raise ValueError(f"Same-time balance conflict; explicitly revise {old['record_id']}")
            return {**old, "status": "duplicate"}
    from .wallet_basis import declaration_basis
    basis = declaration_basis(project, instant)
    expected = basis["expected_btc"]
    payload = {"kind": "balance", "scope": SCOPE, "quantity_btc": value, "as_of": instant,
               "original_as_of": str(as_of), "source": source, "time_basis": time_basis,
               "verification": "user_reported", "void": False, "replaces": replaces,
               "unknown_prior_history": not basis["acquisition_history_known"],
               "recorded_expected_btc": expected,
               "recorded_residual_btc": btc(sats(value)-sats(expected)) if expected is not None else None}
    if basis["calculation_basis"] is not None:
        payload["calculation_basis"] = basis["calculation_basis"]
    conn = _connect(project)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            return {**_write(conn, project, "balance", payload), "status": "recorded"}
    finally:
        conn.close()


def _validate_link(project, event, balance_id):
    balances = sorted(records(project, "balance", include_void=False), key=lambda row: row["as_of"])
    target = next((b for b in balances if b["record_id"] == balance_id), None)
    if not target:
        raise ValueError(f"Unknown or void balance ID: {balance_id}")
    index = balances.index(target)
    previous = balances[index-1] if index else None
    from .wallet_basis import declaration_basis
    earliest = declaration_basis(project, target["as_of"])["history_start"]
    earliest = _time(earliest) if earliest else None
    lower = previous["as_of"] if previous else earliest
    time = event["occurred_at"]
    outside = time > target["as_of"] or (previous is not None and time <= lower) or (not previous and lower and time < lower)
    if outside:
        raise ValueError(f"Event outside balance {balance_id} interval: {lower or 'unknown beginning'} to {target['as_of']}; choose an applicable ID or omit the link")
    return previous["record_id"] if previous else None


def add_event(project, *, type, quantity_btc, occurred_at, source, reference, balance_id=None,
              replaces=None, now=None):
    if type not in SIGNS:
        raise ValueError("Unsupported BTC event type")
    amount = quantity(quantity_btc, positive=True)
    instant = timestamp(occurred_at, now)
    source, reference = str(source).strip(), str(reference).strip()
    if not source or not reference:
        raise ValueError("Event requires source and unique reference")
    if source.casefold().replace(" ", "") in ("bull", "bullbitcoin"):
        raise ValueError("Import Bull purchases through the order CSV, not a manual event")
    _replacement(project, "event", replaces)
    value = {"kind": "event", "scope": SCOPE, "type": type, "quantity_btc": amount,
             "occurred_at": instant, "original_occurred_at": str(occurred_at),
             "source": source, "reference": reference, "balance_id": balance_id,
             "verification": "user_declared", "void": False, "replaces": replaces}
    value["linked_previous_balance_id"] = _validate_link(project, value, balance_id) if balance_id else None
    for old in records(project, "event"):
        if (old["source"], old["reference"]) == (source, reference):
            if old.get("void"):
                raise ValueError(f"Reference belongs to void event {old['record_id']}; use a new reference with an explicit replacement")
            if any(old.get(k) != value.get(k) for k in ("type", "quantity_btc", "occurred_at", "balance_id")):
                raise ValueError(f"Event reference conflict; explicitly revise or link {old['record_id']}")
            return {**old, "status": "duplicate"}
    from .wallet_basis import has_canonical_sources, declaration_basis
    if has_canonical_sources(project):
        value["calculation_basis"] = declaration_basis(project, instant)["calculation_basis"]
    conn = _connect(project)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            return {**_write(conn, project, "event", value), "status": "recorded"}
    finally:
        conn.close()


def revise(project, record_id, *, expected_revision, reason, action="revise", **changes):
    if action not in ('revise','void','link','unlink'):
        raise ValueError('Unknown wallet revision action')
    row = get_record(project, record_id)
    if row["revision"] != expected_revision or row.get("void"):
        raise ValueError("Stale revision or void record; inspect current state before changing it")
    if not str(reason).strip():
        raise ValueError("Revision requires a reason")
    value = {**row, "reason": reason, "action": action}
    if action == "void":
        value["void"] = True
    else:
        allowed = {"quantity_btc", "source"} if row["kind"] == "balance" else {"quantity_btc", "type", "occurred_at"}
        if action in ("link", "unlink") and row["kind"] == "event":
            allowed = {"balance_id"}
            if action == "link" and row.get("balance_id"):
                raise ValueError("Unlink the existing attribution before relinking")
        if any(key not in allowed for key in changes):
            raise ValueError("Identity fields cannot be revised; void and explicitly replace")
        if not changes:
            raise ValueError("Provide a change to revise")
        value.update(changes)
        value["quantity_btc"] = quantity(value["quantity_btc"], positive=row["kind"] == "event")
        if row["kind"] == "balance" and not str(value["source"]).strip():
            raise ValueError("Balance source cannot be blank")
        if row["kind"] == "event":
            if value["type"] not in SIGNS:
                raise ValueError("Unsupported BTC event type")
            value["occurred_at"] = timestamp(value["occurred_at"])
            value["linked_previous_balance_id"] = _validate_link(project, value, value["balance_id"]) if value.get("balance_id") else None
    from .wallet_basis import has_canonical_sources, declaration_basis
    if has_canonical_sources(project):
        declaration_basis(project, value.get("as_of") or value["occurred_at"])
    conn = _connect(project)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT MAX(revision) FROM wallet_revisions WHERE record_id=?", (record_id,)).fetchone()[0]
            if current != expected_revision:
                raise ValueError("Revision changed concurrently")
            return {**_write(conn, project, row["kind"], value, record_id=record_id), "status": action}
    finally:
        conn.close()


def import_events(project, path, *, now=None):
    from .operations import atomic_data
    path = Path(path)
    raw = path.read_bytes()
    import io
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = ("source", "reference", "type", "occurred_at", "quantity_btc", "balance_id")
    if reader.fieldnames != list(required):
        raise ValueError("BTC events CSV requires exactly: " + ",".join(required))
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("Empty or malformed BTC event batch")
    def apply(stage):
        results = [add_event(stage, **{**row, "balance_id": row["balance_id"] or None}, now=now) for row in rows]
        sha = hashlib.sha256(raw).hexdigest()
        directory = stage / "data/raw/crypto/wallet" / datetime.now(timezone.utc).strftime("%Y/%m")
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"events-{sha}.csv"
        if not target.exists():
            target.write_bytes(raw)
        if target.read_bytes() != raw:
            raise ValueError("Event batch archive collision")
        target.chmod(0o400)
        return {"status": "imported", "events": results, "source_path": str(target.relative_to(stage)), "sha256": sha}
    return atomic_data(project, apply)


def make_crypto_view(project, as_of, *, strict=True):
    """Value from the latest eligible observation; keep every earlier residual."""
    from .source_ingestion import require_report_projection
    require_report_projection(project)
    cutoff = _time(as_of)
    base = _base(project, cutoff)
    all_rows = records(project)
    changes = [{"occurred_at": row["completed_at"], "quantity_btc": btc(sats(row["buy_qty_btc"]) + sats(row["buy_qty_lbtc"]))}
               for row in base["orders"] if row["order_type"] == "Buy Bitcoin" and row["included_in_totals"]]
    purchases = [r for r in base["orders"] if r["order_type"] == "Buy Bitcoin" and r["included_in_totals"]]
    opening = base.get("opening")
    overlap = False
    if opening:
        conn = _readonly(project)
        try:
            source_ids = {s["id"] for s in opening["reference_sources"]}
            from .crypto import _complete
            reference_orders = {}
            for row in conn.execute("SELECT order_key,source_id,payload_json,revision FROM crypto_order_revisions ORDER BY revision"):
                if row[1] in source_ids:
                    reference_orders[row[0]] = json.loads(row[2])
            old_keys = {key for key, order in reference_orders.items() if _complete(order) and order['completed_at'] <= opening['reference_as_of']}
            overlap = any(p["order_key"] not in old_keys and p["completed_at"] <= opening["reference_as_of"] for p in purchases)
        finally:
            conn.close()
    if not all_rows and not overlap:
        return base
    result = reconcile_wallet(as_of=cutoff, changes=changes, rows=all_rows,
                              opening_quantity=base["opening_btc_equivalent_qty"],
                              acquisition_history_known=has_bull(project),
                              history_start=base["source"].get("earliest_created_at"), opening_overlap=overlap)
    wallet = result["wallet"]
    events = wallet["events"]
    current, anchor = result["current_sats"], wallet["anchor"]
    corrupt, conflicts = wallet["integrity_errors"], wallet["link_conflicts"]
    prehistory = wallet["prehistory_event_ids"]
    if strict and (current is None or current < 0 or corrupt):
        raise ValueError("BTC quantity cannot be valued: unknown pre-observation history, negative holdings, or corrupt wallet evidence")
    if strict and not anchor and (overlap or prehistory):
        raise ValueError("BTC opening/source overlap requires explicit reconciliation before valuation")
    base["wallet"] = wallet
    base["btc_equivalent_qty"] = btc(current) if current is not None else "0"
    base["totals"]["btc_equivalent_qty"] = base["btc_equivalent_qty"]
    base["meta"]["quantity_status"] = result["quantity_status"]
    base["meta"]["estimation_method"] = result["estimation_method"]
    base["meta"]["cost_unknown"] = bool(anchor or events or not has_bull(project) or overlap)
    base["issues"] = [r for r in base["issues"] if r["code"] != "order_derived_quantity"]
    base["issues"].append({"code": "wallet_reconciliation", "severity": "warning" if wallet["unresolved_count"] or conflicts or overlap else "info",
                           "message": f"BTC 使用獨立餘額／異動帳本；{wallet['unresolved_count']} 次觀測仍待釐清。算術相符不代表獨立錢包核驗，未知差額不當作費用或供款。"})
    if any(e['type'] in ('sale','external_in','external_out') for e in events):
        base['issues'].append({'code':'wallet_counterpart_coverage','severity':'warning',
                               'message':'出售／外部移轉僅登記 BTC 數量；收到的現金、對端資產及供款來源須另補。不自動創造現金或推定全部資產／資金流已涵蓋。'})
    if not has_bull(project):
        base['issues'].append({'code':'wallet_unknown_history','severity':'info',
                               'message':'尚無 Bull 購入／入金帳本；零值僅表示已提供訂單小計為零，歷史購入、供款、現金及成本並未確認為零。'})
    return base


def balance_detail(project, record_id):
    row = get_record(project, record_id)
    if row["kind"] != "balance":
        raise ValueError("Expected a balance ID")
    from .wallet_basis import declaration_basis
    basis = declaration_basis(project, row["as_of"])
    return {"record": row, "reconciliation": next((r for r in basis["wallet"].get("reconciliations", []) if r["balance_id"] == record_id), None),
            "revisions": revision_history(project, record_id)}


def revision_history(project, record_id):
    conn = _readonly(project)
    try:
        return [json.loads(row[0]) for row in conn.execute("SELECT payload_json FROM wallet_revisions WHERE record_id=? ORDER BY revision", (record_id,))] if conn else []
    finally:
        if conn:
            conn.close()
