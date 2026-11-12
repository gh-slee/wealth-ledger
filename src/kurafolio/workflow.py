"""Detect either export and choose a dated, reproducible report automatically."""
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import sqlite3
from zoneinfo import ZoneInfo

from .core import REQUIRED as HOLDINGS_COLUMNS, initialize, import_holdings, make_payload, _parse_holdings
from .crypto import REQUIRED as BULL_COLUMNS, import_bull_orders
from .wallet import make_crypto_view, has_bull, has_wallet, add_balance, quantity, timestamp
from .fx import resolve_rates
from .prices import parse_time
from .combined import make_combined_payload

LOCAL = ZoneInfo("America/Toronto")


def validate_update_request(request, *, preview=False):
    """Shared structural request checks before preview or mutating services."""
    paths = request.get("paths", [])
    balance = request.get("btc_balance")
    if request.get("resume_operation") or request.get("list_operations") or request.get("show_operation"):
        raise ValueError("Dry-run cannot be combined with operation query/resume modes")
    if request.get("snapshot_id") is not None and (paths or balance is not None):
        raise ValueError("--snapshot-id cannot include new inputs")
    if preview and request.get("lookthrough_run_id") is not None:
        raise ValueError("Dry-run does not fetch or replay ETF analysis; omit --lookthrough-run-id")
    if balance is None and (request.get("btc_balance_as_of") or request.get("btc_balance_source")):
        raise ValueError("Balance time/source require --btc-balance")
    if request.get("wealthsimple_only") and (balance is not None or request.get("as_of") or request.get("price_file")):
        raise ValueError("Brokerage-only mode cannot include wallet/combined valuation inputs")
    if request.get("kind", "monthly") not in {"baseline", "monthly", "interim"}:
        raise ValueError("Unsupported snapshot kind")
    if request.get("lookthrough_run_id") is not None and (paths or balance is not None):
        raise ValueError("ETF replay cannot include new inputs")
    if request.get("as_of"):
        parse_time(request["as_of"])



def identify_inputs(paths):
    identified = {}
    seen = set()
    for item in paths:
        path = Path(item).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream), [])
        header = [value.strip() for value in header]
        if not header or len(header) != len(set(header)):
            raise ValueError(f"Empty or duplicate CSV header: {path.name}")
        matches = [provider for provider,columns in (("wealthsimple",HOLDINGS_COLUMNS),("bullbitcoin",BULL_COLUMNS))
                   if set(columns).issubset(header)]
        if len(matches) != 1:
            raise ValueError(f"Unsupported or ambiguous CSV format: {path.name}")
        provider = matches[0]
        if provider in identified:
            raise ValueError(f"Only one {provider} CSV can be supplied per update")
        identified[provider] = path
    return identified


def _stored_observation(project, *, as_of=None):
    db = Path(project)/"data/db/portfolio.sqlite3"
    if not db.exists():
        return None
    if as_of is None:
        pointer = Path(project)/"reports/latest.json"
        if pointer.exists():
            bundle = json.loads(pointer.read_text(encoding="utf-8"))["path"]
            saved = Path(project)/bundle/"data.json"
            if saved.is_file():
                as_of = json.loads(saved.read_text(encoding="utf-8"))["meta"]["as_of"]
    with sqlite3.connect(db) as conn:
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE name='combined_observations'").fetchone()
        if not table:
            return None
        if as_of:
            row = conn.execute("SELECT payload_json FROM combined_observations WHERE as_of_utc=? ORDER BY revision DESC LIMIT 1",
                               (parse_time(as_of).isoformat(),)).fetchone()
        else:
            row = conn.execute("SELECT payload_json FROM combined_observations ORDER BY as_of_utc DESC,revision DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None


def choose_valuation_as_of(*, wealthsimple_as_of, inputs, results, latest_bull_completed,
                           previous, now, explicit=None, historical_selection=False):
    """Order timestamps are transaction dates; execution time is a valuation date."""
    if explicit:
        return parse_time(explicit).astimezone(LOCAL).isoformat()
    if "wealthsimple" in inputs or historical_selection:
        if wealthsimple_as_of and ("bullbitcoin" not in inputs or not latest_bull_completed or parse_time(latest_bull_completed)<=parse_time(wealthsimple_as_of)):
            return wealthsimple_as_of
        if historical_selection and wealthsimple_as_of:
            return wealthsimple_as_of
    if not inputs:
        old = previous["as_of"] if previous else None
        if old and (not wealthsimple_as_of or parse_time(old)>=parse_time(wealthsimple_as_of)):
            return old
        return wealthsimple_as_of or now.replace(second=0,microsecond=0).astimezone(LOCAL).isoformat()
    unchanged = all(result.get("status")=="duplicate" for result in results.values())
    if unchanged and previous:
        old = parse_time(previous["as_of"])
        same_day = old.astimezone(LOCAL).date()==now.astimezone(LOCAL).date()
        old_is_applicable = not wealthsimple_as_of or old>=parse_time(wealthsimple_as_of)
        if same_day and old_is_applicable:
            return previous["as_of"]
    return now.replace(second=0,microsecond=0).astimezone(LOCAL).isoformat()


def ingest_inputs(project, paths=(), *, kind="monthly", fx_file=None, opening_file=None,
                  btc_balance=None, btc_balance_as_of=None, btc_balance_source=None, now=None):
    """Validate/import into a staging project before the report phase."""
    project = Path(project)
    now = now or datetime.now(timezone.utc)
    inputs = identify_inputs(paths)
    parsed = _parse_holdings(inputs["wealthsimple"])[1] if "wealthsimple" in inputs else None
    if btc_balance is not None:
        quantity(btc_balance)
        timestamp(btc_balance_as_of or now.isoformat(), now.isoformat())
    elif btc_balance_as_of or btc_balance_source:
        raise ValueError("Balance time/source require --btc-balance")
    initialize(project)
    results = {}
    if parsed:
        rates = resolve_rates(project, parsed.astimezone(LOCAL).date().isoformat(), fx_file)
        results["wealthsimple"] = import_holdings(project, inputs["wealthsimple"], kind, rates)
    if "bullbitcoin" in inputs:
        opening_path = Path(opening_file) if opening_file else project / "config/bull-opening.json"
        opening = json.loads(opening_path.read_text(encoding="utf-8")) if opening_path.exists() else None
        results["bullbitcoin"] = import_bull_orders(project, inputs["bullbitcoin"], opening_assumption=opening)
    if btc_balance is not None:
        results["wallet"] = add_balance(project, btc_balance, btc_balance_as_of or now.isoformat(),
            source=btc_balance_source or "user_reported_total",
            time_basis="explicit" if btc_balance_as_of else "execution_time", now=now.isoformat())
    return {"sources": results, "detected_inputs": {k: str(v) for k,v in inputs.items()}}


def select_context(project, accepted, *, snapshot_id=None, as_of=None, now=None, base_override=None):
    """Choose a cutoff before quote lookup so failed reports can retry it exactly."""
    now = now or datetime.now(timezone.utc)
    inputs, results = accepted["detected_inputs"], accepted["sources"]
    selected = results.get("wealthsimple", {}).get("snapshot_id", snapshot_id)
    previous = _stored_observation(project)
    with sqlite3.connect(Path(project)/"data/db/portfolio.sqlite3") as conn:
        has_ws = bool(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
        if as_of and has_ws and selected is None:
            eligible = conn.execute("SELECT id FROM snapshots WHERE as_of_utc<=? ORDER BY as_of_utc DESC,revision DESC LIMIT 1", (parse_time(as_of).isoformat(),)).fetchone()
            if not eligible:
                raise ValueError("No Wealthsimple snapshot exists at or before this historical cutoff")
            selected = eligible[0]
    base = base_override if base_override is not None else (make_payload(project, selected) if has_ws or selected is not None else None)
    has_crypto = has_bull(project) or has_wallet(project)
    if not has_crypto:
        return {"base": base, "selected": selected, "has_crypto": False, "target": base["meta"]["as_of"] if base else None}
    ws_as_of = base["meta"]["as_of"] if base else None
    bull = make_crypto_view(project, now.isoformat(), strict=False)
    target = choose_valuation_as_of(wealthsimple_as_of=ws_as_of, inputs=inputs, results=results,
        latest_bull_completed=bull["source"]["latest_completed_at"], previous=previous, now=now,
        explicit=as_of, historical_selection=snapshot_id is not None)
    if "wallet" in results and not as_of:
        candidates = [target, results["wallet"]["as_of"]]
        if previous:
            candidates.append(previous["as_of"])
        target = max(candidates, key=parse_time)
        target = parse_time(target).astimezone(LOCAL).isoformat()
    if base and parse_time(target) < parse_time(ws_as_of):
        raise ValueError("Combined valuation cannot predate its Wealthsimple holdings source")
    return {"base": base, "selected": selected, "has_crypto": True, "target": target}


def prepare_update(project, paths=(), *, kind="monthly", snapshot_id=None,
                   fx_file=None, opening_file=None, price_file=None, as_of=None,
                   wealthsimple_only=False, now=None, btc_balance=None,
                   btc_balance_as_of=None, btc_balance_source=None, accepted=None, btc_cost_policy=None):
    project = Path(project)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Execution time requires a timezone")
    if accepted is None:
        inputs = identify_inputs(paths)
        if wealthsimple_only and ("bullbitcoin" in inputs or as_of or price_file or btc_balance is not None):
            raise ValueError("Brokerage-only reports cannot include Bull/wallet or combined valuation options")
        if snapshot_id is not None and (inputs or btc_balance is not None):
            raise ValueError("--snapshot-id is for regenerating a saved observation, not importing inputs")
        accepted = ingest_inputs(project, paths, kind=kind, fx_file=fx_file, opening_file=opening_file,
            btc_balance=btc_balance, btc_balance_as_of=btc_balance_as_of, btc_balance_source=btc_balance_source, now=now)
    inputs, results = accepted["detected_inputs"], accepted["sources"]
    context = select_context(project, accepted, snapshot_id=snapshot_id, as_of=as_of, now=now)
    base, selected, target = context["base"], context["selected"], context["target"]
    if wealthsimple_only or not context["has_crypto"]:
        if base is None:
            raise ValueError("No holdings available; provide a supported CSV or BTC balance")
        if not wealthsimple_only and (as_of or price_file):
            raise ValueError("Combined valuation options require an imported Bull ledger or wallet balance")
        return base, {"status": "updated" if inputs else "regenerated", "sources": results,
                     "detected_inputs": list(inputs), "valuation_policy": "wealthsimple_as_of"}
    ws_as_of = base["meta"]["as_of"] if base else None
    bull = make_crypto_view(project, target)
    existing = _stored_observation(project, as_of=target)
    source_updates = {
        "wealthsimple": {"status": "provided" if "wealthsimple" in inputs else "carried_forward" if base else "not_available",
                         "holdings_as_of": ws_as_of, "filename": base["source"]["filename"] if base else None},
        "bullbitcoin": {"status": "provided" if "bullbitcoin" in inputs else "carried_forward" if has_bull(project) else "not_available",
                        "latest_completed_at": bull["source"]["latest_completed_at"],
                        "quantity_status": bull["meta"]["quantity_status"], "transaction_coverage_confirmed": False},
    }
    no_new_data = not results or all(r.get("status") == "duplicate" for r in results.values())
    if (no_new_data and existing and existing.get("source_updates")
            and existing.get("wealthsimple_snapshot_id") == (base["meta"]["snapshot_id"] if base else None)):
        source_updates = existing["source_updates"]
    source_updates["bullbitcoin"]["quantity_status"] = bull["meta"]["quantity_status"]
    if bull.get("wallet"):
        anchor = bull["wallet"]["anchor"]
        source_updates["wallet"] = {"status": "provided" if "wallet" in results else "carried_forward",
                                   "balance_id": anchor["record_id"] if anchor else None,
                                   "observed_at": anchor["as_of"] if anchor else None,
                                   "unresolved_count": bull["wallet"]["unresolved_count"]}
    target_date = parse_time(target).astimezone(LOCAL).date().isoformat()
    rates = base["fx"] if base and target_date == parse_time(ws_as_of).astimezone(LOCAL).date().isoformat() and not fx_file else resolve_rates(project, target_date, fx_file)
    payload = make_combined_payload(project, selected, as_of=target, price_file=price_file, fx=rates, source_updates=source_updates, btc_cost_policy=btc_cost_policy)
    return payload, {"status": "updated" if results else "regenerated", "sources": results,
                     "detected_inputs": list(inputs), "valuation_policy": "explicit" if as_of else "automatic",
                     "valuation_as_of": target, "execution_at": now.isoformat()}
