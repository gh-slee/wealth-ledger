"""Immutable Bull Bitcoin order ledger, without wallet-balance inference.

This adapter uses the standard library and shares the portfolio SQLite file.
It adds only crypto-prefixed tables. Completed orders reconstruct acquisition
quantities; they are not wallet confirmations or month-end valuations.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

from .source_formats import (BULL_REQUIRED as REQUIRED, NETWORKS, METHODS,
    _number, _time, _complete, _account_id, _order_key)

PROVIDER = "bullbitcoin"
ZERO = Decimal("0")
IMMUTABLE = (
    "order_type", "payin_amount", "payin_currency", "payout_amount",
    "payout_currency", "payin_method", "payout_method", "network",
    "created_at", "completed_at",
)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _text(number):
    value = format(number, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def monthly_purchase_price(row):
    """Effective CAD per delivered BTC equivalent for completed monthly buys."""
    with localcontext() as context:
        context.prec = 80
        quantity = Decimal(str(row["buy_btc_equivalent_qty"]))
        return Decimal(str(row["buy_cost_cad"])) / quantity if quantity > ZERO else None


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _assumptions(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Opening assumptions must be explicit metadata")
    for key in ("btc", "lbtc", "cad"):
        if key not in value or Decimal(_number(value[key])) != ZERO:
            raise ValueError("This adapter requires explicit zero BTC, LBTC and CAD opening assumptions")
    if not str(value.get("basis", "")).strip() or not str(value.get("confirmed_by", "")).strip():
        raise ValueError("Opening assumptions require basis and confirmed_by")
    return {**value, "btc": "0", "lbtc": "0", "cad": "0"}


def _parse(path, source_account):
    from .source_formats import parse_bull
    return parse_bull(Path(path).read_bytes(), source_account)


def _readonly(project):
    db = Path(project) / "data/db/portfolio.sqlite3"
    if not db.exists():
        return None
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has_tables(conn):
    return conn is not None and conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='crypto_accounts'").fetchone() is not None


def _existing(conn, source_account):
    if not _has_tables(conn):
        return None, [], {}
    account = conn.execute("SELECT * FROM crypto_accounts WHERE provider=? AND source_account=?",
                           (PROVIDER, source_account)).fetchone()
    sources = conn.execute("SELECT * FROM crypto_sources WHERE provider=? AND source_account=? ORDER BY id",
                           (PROVIDER, source_account)).fetchall()
    rows = conn.execute("""SELECT r.* FROM crypto_order_revisions r
        WHERE r.provider=? AND r.source_account=? AND r.revision=(
          SELECT MAX(v.revision) FROM crypto_order_revisions v WHERE v.order_key=r.order_key)""",
                        (PROVIDER, source_account)).fetchall()
    return account, sources, {row["order_key"]: row for row in rows}


def _check(existing, orders):
    additions, revisions, unchanged = [], [], 0
    for order in orders:
        old = existing.get(order["order_key"])
        if old is None:
            additions.append(order)
            continue
        old_order = json.loads(old["payload_json"])
        if old_order == order:
            unchanged += 1
            continue
        if _complete(old_order):
            if not _complete(order) or any(old_order[key] != order[key] for key in IMMUTABLE):
                raise ValueError("Completed order economics/timestamps cannot be changed or reverted")
        revisions.append(order)
    return additions, revisions, unchanged


def _initialize(project):
    db = Path(project) / "data/db/portfolio.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS crypto_accounts(
        account_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
        source_account TEXT NOT NULL, opening_json TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(provider,source_account));
      CREATE TABLE IF NOT EXISTS crypto_sources(
        id INTEGER PRIMARY KEY, provider TEXT NOT NULL, source_account TEXT NOT NULL,
        sha256 TEXT NOT NULL, semantic_hash TEXT NOT NULL, filename TEXT NOT NULL,
        path TEXT NOT NULL, row_count INTEGER NOT NULL, imported_at TEXT NOT NULL,
        first_created_at TEXT NOT NULL, last_created_at TEXT NOT NULL,
        first_completed_at TEXT, last_completed_at TEXT,
        UNIQUE(provider,source_account,sha256));
      CREATE TABLE IF NOT EXISTS crypto_order_revisions(
        id INTEGER PRIMARY KEY, order_key TEXT NOT NULL, provider TEXT NOT NULL,
        source_account TEXT NOT NULL, revision INTEGER NOT NULL,
        source_id INTEGER NOT NULL REFERENCES crypto_sources(id),
        content_hash TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(order_key,revision));
      CREATE INDEX IF NOT EXISTS crypto_order_lookup ON crypto_order_revisions(order_key,revision);
    """)
    db.chmod(0o600)
    return conn


def _archive(project, csv_path, raw, sha, orders):
    latest = max(order["completed_at"] or order["created_at"] for order in orders)
    directory = Path(project) / "data/raw/crypto" / PROVIDER / latest[:4] / latest[5:7]
    directory.mkdir(parents=True, exist_ok=True)
    filename = Path(csv_path).name
    target = directory / filename
    if target.exists() and _hash(target.read_bytes()) != sha:
        target = directory / (Path(filename).stem + "-" + sha[:16] + Path(filename).suffix)
    if target.exists():
        if _hash(target.read_bytes()) != sha:
            raise ValueError("Archived source hash collision or corruption")
    else:
        with target.open("xb") as stream:
            stream.write(raw)
    target.chmod(0o400)
    return str(target.relative_to(project))


def import_bull_orders(project: Path, csv_path: Path, source_account="bullbitcoin-main", *, opening_assumption=None):
    """Archive an order export and append revisions after validating the full batch.

    The first import requires explicit zero opening assumptions. Reimporting an
    already-seen export is harmless, even after its pending orders completed.
    """
    project, csv_path = Path(project).resolve(), Path(csv_path)
    source_account = str(source_account).strip()
    if not source_account or len(source_account) > 160:
        raise ValueError("A stable source_account alias is required")
    supplied_assumptions = _assumptions(opening_assumption)
    raw, orders, row_count, duplicate_rows, semantic = _parse(csv_path, source_account)
    sha = _hash(raw)
    prior_conn = _readonly(project)
    try:
        account, sources, existing = _existing(prior_conn, source_account)
        assumptions = json.loads(account["opening_json"]) if account else supplied_assumptions
        if assumptions is None:
            raise ValueError("First import requires explicit zero opening assumptions")
        if supplied_assumptions is not None and supplied_assumptions != assumptions:
            raise ValueError("Stored opening assumptions cannot be silently changed")
        exact = next((source for source in sources if source["sha256"] == sha), None)
        if exact:
            return {"status": "duplicate", "source_id": exact["id"], "source_path": exact["path"],
                    "account_id": _account_id(source_account), "new_orders": 0, "revised_orders": 0,
                    "unchanged_orders": len(orders), "duplicate_rows": duplicate_rows}
        semantic_duplicate = next((source for source in sources if source["semantic_hash"] == semantic), None)
        if semantic_duplicate:
            additions, revisions, unchanged = [], [], len(orders)
        else:
            additions, revisions, unchanged = _check(existing, orders)
    finally:
        if prior_conn is not None:
            prior_conn.close()
    # Every input and stored-ID conflict above is checked before archive/DB writes.
    conn = _initialize(project)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            current_account, current_sources, current_existing = _existing(conn, source_account)
            if current_account and json.loads(current_account["opening_json"]) != assumptions:
                raise ValueError("Opening assumptions changed during import")
            if not semantic_duplicate:
                additions, revisions, unchanged = _check(current_existing, orders)
            archived = _archive(project, csv_path, raw, sha, orders)
            timestamp = _now()
            conn.execute("INSERT OR IGNORE INTO crypto_accounts VALUES(?,?,?,?,?)", (
                _account_id(source_account), PROVIDER, source_account, _json(assumptions), timestamp))
            completed = [order["completed_at"] for order in orders if _complete(order)]
            source_id = conn.execute("""INSERT INTO crypto_sources(
                provider,source_account,sha256,semantic_hash,filename,path,row_count,imported_at,
                first_created_at,last_created_at,first_completed_at,last_completed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    PROVIDER, source_account, sha, semantic, csv_path.name, archived, row_count, timestamp,
                    min(order["created_at"] for order in orders), max(order["created_at"] for order in orders),
                    min(completed) if completed else None, max(completed) if completed else None)).lastrowid
            for order in additions + revisions:
                previous = current_existing.get(order["order_key"])
                revision = previous["revision"] + 1 if previous else 1
                content = _json(order)
                conn.execute("""INSERT INTO crypto_order_revisions(
                    order_key,provider,source_account,revision,source_id,content_hash,payload_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (
                        order["order_key"], PROVIDER, source_account, revision, source_id,
                        _hash(content.encode()), content, timestamp))
        return {"status": "revision" if revisions else "imported" if additions else "duplicate",
                "source_id": source_id, "source_path": archived, "account_id": _account_id(source_account),
                "new_orders": len(additions), "revised_orders": len(revisions),
                "unchanged_orders": unchanged, "duplicate_rows": duplicate_rows}
    finally:
        conn.close()


def _source_view(project, source):
    result = {key: source[key] for key in (
        "id", "filename", "path", "sha256", "semantic_hash", "row_count", "imported_at",
        "first_created_at", "last_created_at", "first_completed_at", "last_completed_at")}
    path = Path(project) / source["path"]
    result["integrity_ok"] = path.exists() and _hash(path.read_bytes()) == source["sha256"]
    return result


def make_crypto_view(project: Path, as_ofISOtimestamp, source_account="bullbitcoin-main"):
    """Return completed-order acquisition totals through an inclusive UTC cutoff.

    Event months are grouped without adding empty months or holdings snapshots.
    Current quantities deliberately exclude unknown wallet/bridge fees.
    """
    project = Path(project).resolve()
    cutoff = _time(as_ofISOtimestamp)
    conn = _readonly(project)
    try:
        account, sources, existing = _existing(conn, source_account)
        if account is None:
            raise ValueError("No imported Bull source account")
        assumptions = json.loads(account["opening_json"])
        latest_orders = [json.loads(row["payload_json"]) for row in existing.values()]
    finally:
        if conn is not None:
            conn.close()
    included = sorted((order for order in latest_orders if _complete(order)
                       and order["completed_at"] <= cutoff),
                      key=lambda order: (order["completed_at"], order["order_key"]))
    totals = {key: ZERO for key in (
        "total_funding_cad", "total_buy_cost_cad", "qty_btc", "qty_lbtc", "btc_equivalent_qty", "cash_cad")}
    months = defaultdict(lambda: {key: ZERO for key in (
        "contribution_cad", "buy_cost_cad", "buy_qty_btc", "buy_qty_lbtc", "buy_btc_equivalent_qty")})
    cash_minimum = ZERO
    with localcontext() as context:
        context.prec = 80
        for order in included:
            amount = Decimal(order["payin_amount"])
            month = months[order["completed_at"][:7]]
            if order["order_type"] == "Funding":
                totals["total_funding_cad"] += amount
                totals["cash_cad"] += amount
                month["contribution_cad"] += amount
            else:
                asset = order["payout_currency"].lower()
                quantity = Decimal(order["payout_amount"])
                totals["total_buy_cost_cad"] += amount
                totals["cash_cad"] -= amount
                totals["qty_" + asset] += quantity
                month["buy_cost_cad"] += amount
                month["buy_qty_" + asset] += quantity
                month["buy_btc_equivalent_qty"] += quantity
            cash_minimum = min(cash_minimum, totals["cash_cad"])
        totals["btc_equivalent_qty"] = totals["qty_btc"] + totals["qty_lbtc"]
        monthly, cumulative_qty, cumulative_cash = [], ZERO, ZERO
        for month, values in sorted(months.items()):
            cumulative_qty += values["buy_btc_equivalent_qty"]
            cumulative_cash += values["contribution_cad"] - values["buy_cost_cad"]
            price = monthly_purchase_price(values)
            monthly.append({"month": month, **{key: _text(value) for key, value in values.items()},
                            "average_purchase_price_cad_per_btc": _text(price) if price is not None else None,
                            "cumulative_btc_equivalent_qty": _text(cumulative_qty),
                            "cash_cad": _text(cumulative_cash), "observation_type": "order_event_month"})
    public_orders = []
    for order in sorted(latest_orders, key=lambda row: (row["created_at"], row["order_key"])):
        if order["created_at"] > cutoff:
            continue
        is_included = _complete(order) and order["completed_at"] <= cutoff
        funding = order["order_type"] == "Funding"
        public_orders.append({
            **{key: order[key] for key in ("order_key", "order_type", "order_status", "payin_status",
                "payout_status", "created_at", "completed_at", "sent_at", "network")},
            "included_in_totals": is_included,
            "effect_type": "funding_origin_unclassified" if funding else "internal_purchase",
            "funding_cad": order["payin_amount"] if funding else "0",
            "buy_cost_cad": "0" if funding else order["payin_amount"],
            "buy_qty_btc": order["payout_amount"] if order["payout_currency"] == "BTC" else "0",
            "buy_qty_lbtc": order["payout_amount"] if order["payout_currency"] == "LBTC" else "0",
            "cash_effect_cad": order["payin_amount"] if funding else "-" + order["payin_amount"],
        })
    provenance = [_source_view(project, source) for source in sources]
    completed_times = [order["completed_at"] for order in latest_orders if _complete(order)]
    issues = [{"code": "order_derived_quantity", "severity": "info",
               "message": "BTC／LBTC 數量由已完成訂單推算；尚未扣除錢包轉帳或網路轉換費用，並非錢包確認餘額。"},
              {"code": "cash_opening_assumption", "severity": "info",
               "message": "CAD 餘額採期初為零的明示假設，由入金減購買支出推算，並非平台餘額確認。"},
              {"code": "order_range_not_coverage", "severity": "info",
               "message": "訂單日期範圍不證明範圍外沒有交易；月份表僅彙總已提供的交易，未建立缺月持倉觀測。"}]
    if cash_minimum < ZERO:
        issues.append({"code": "negative_cash_ledger", "severity": "warning",
                       "message": "按完成時間推算曾出現負 CAD 餘額；需檢查缺少入金或交割時間差。",
                       "minimum_cash_cad": _text(cash_minimum)})
    for source in provenance:
        if not source["integrity_ok"]:
            issues.append({"code": "crypto_source_integrity", "severity": "warning",
                           "message": "已封存 crypto 來源遺失或雜湊不符；帳本數值未自動改寫。", "source_id": source["id"]})
    from .crypto_opening import latest_opening
    opening = latest_opening(project, source_account, cutoff)
    purchased = totals['btc_equivalent_qty']
    opening_qty = Decimal(opening['opening_btc_equivalent_qty']) if opening else ZERO
    totals['purchased_btc_equivalent_qty'] = purchased
    totals['opening_btc_equivalent_qty'] = opening_qty
    totals['btc_equivalent_qty'] = purchased+opening_qty
    if opening:
        issues.append({'code':'pre_bull_opening_quantity','severity':'info',
                       'message':'使用者將總餘額減 Bull 累積購入的差額指定為使用 Bull 前的持倉；期初成本及歷史投入金額未知，未推定為新供款。'})
        if not opening['integrity_ok']:
            issues.append({'code':'crypto_opening_integrity','severity':'error','message':'期初聲明原始來源遺失或雜湊不符；需核對備份。'})
    serialized_totals = {key: _text(value) for key, value in totals.items()}
    return {
        "meta": {"provider": PROVIDER, "source_account": source_account, "account_id": account["account_id"],
                 "as_of": cutoff, "estimation_method": "declared_pre_bull_quantity_plus_completed_orders" if opening else "completed_orders_under_zero_opening_assumptions",
                 "quantity_status": "opening_plus_orders_unadjusted_for_wallet_fees" if opening else "order_derived_unadjusted_for_wallet_fees",
                 "completed_order_count": len(included),
                 "pending_order_count": sum(not _complete(order) and order["created_at"] <= cutoff for order in latest_orders),
                 "excluded_after_cutoff_count": sum(_complete(order) and order["completed_at"] > cutoff for order in latest_orders),
                 "monthly_observations_generated": False},
        **serialized_totals, "totals": serialized_totals, "monthly": monthly, "orders": public_orders,
        "assumptions": assumptions, "opening": opening,
        "source": {"sources": provenance,
                   "earliest_created_at": min(order["created_at"] for order in latest_orders),
                   "latest_completed_at": max(completed_times) if completed_times else None},
        "coverage": {"status": "provided_order_range_only", "absence_outside_range_confirmed": False,
                     "first_completed_at": min(completed_times) if completed_times else None,
                     "last_completed_at": max(completed_times) if completed_times else None,
                     "latest_imported_at": max(source["imported_at"] for source in provenance),
                     "missing_month_policy": "do_not_create_holdings_observations"},
        "issues": issues,
    }
