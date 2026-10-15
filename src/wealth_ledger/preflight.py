"""Offline import simulation in a disposable project; never commit live state."""
from .i18n import tr, LabelCatalog, localized, sheet_title, legacy_text
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile

from .core import initialize, inspect_holdings, import_holdings
from .crypto import import_bull_orders
from .fx import read_saved_rates
from .operations import fingerprint
from .prices import parse_time, read_saved_quote
from .wallet import add_balance, make_crypto_view, has_bull
from .wallet_reports import quantity_basis_label, display_time
from .workflow import identify_inputs, select_context, LOCAL

INPUT_ERRORS = (ValueError, OSError, KeyError, TypeError, InvalidOperation, csv.Error, sqlite3.DatabaseError)


def _snapshot(project, stage):
    """Copy only financial evidence needed by importers; SQLite source is read-only."""
    initialize(stage)
    db = project / "data/db/portfolio.sqlite3"
    if db.exists():
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(stage / "data/db/portfolio.sqlite3")) as target:
            source.backup(target)
    for name in ("config", "data/fx", "data/prices", "data/raw/holdings", "data/raw/activity",
                 "data/raw/crypto", "data/raw/reference"):
        source = project / name
        if source.exists():
            shutil.copytree(source, stage / name, dirs_exist_ok=True)
    pointer = project / "reports/latest.json"
    if pointer.exists():
        relative = json.loads(pointer.read_text(encoding="utf-8"))["path"]
        saved = project / relative / "data.json"
        if saved.exists():
            meta = json.loads(saved.read_text(encoding="utf-8"))["meta"]
            target = stage / "reports/previous"
            target.mkdir(parents=True)
            (target / "data.json").write_text(json.dumps({"meta": meta}), encoding="utf-8")
            (stage / "reports/latest.json").write_text(json.dumps({"path": "reports/previous"}), encoding="utf-8")


def _safe_issues(issues):
    """Keep explanations without exposing temporary source/record identifiers."""
    return [{key: item[key] for key in ("code", "severity", "message") if key in item} for item in issues]


def _validate_request(request):
    paths = request.get("paths", [])
    balance = request.get("btc_balance")
    if request.get("resume_operation") or request.get("list_operations") or request.get("show_operation"):
        raise ValueError("Dry-run cannot be combined with operation query/resume modes")
    if request.get("snapshot_id") is not None and (paths or balance is not None):
        raise ValueError("--snapshot-id cannot include new inputs")
    if request.get("lookthrough_run_id") is not None:
        raise ValueError("Dry-run does not fetch or replay ETF analysis; omit --lookthrough-run-id")
    if balance is None and (request.get("btc_balance_as_of") or request.get("btc_balance_source")):
        raise ValueError("Balance time/source require --btc-balance")
    if request.get("wealthsimple_only") and (balance is not None or request.get("as_of") or request.get("price_file")):
        raise ValueError("Brokerage-only mode cannot include wallet/combined valuation inputs")
    if request.get("as_of"):
        parse_time(request["as_of"])


def preview_update(project, request, *, now=None):
    """Return a safe, JSON-serializable preview; no live IDs or financial writes."""
    project = Path(project).resolve()
    now = now or datetime.now(timezone.utc)
    result = {"mode": "dry_run", "schema_version": 1, "execution_at": now.isoformat(),
              "status": "blocked", "sources": {}, "checks": [], "blockers": [],
              "pending_checks": ["latest_official_etf_data", "report_generation_and_validation"],
              "valuation_as_of": None, "btc": None, "simulation_complete": False,
              "network_used": False, "live_data_changed": False,
              "formal_import_required": True}

    def block(component, exc):
        result["blockers"].append({"component": component, "message": tr('message.3c80aefd1063'), "detail": str(exc)})

    def reference(name, value):
        status = "available" if value is not None else "pending"
        result["checks"].append({"name": name, "status": status})
        if value is None:
            result["pending_checks"].append(name)
        return value

    try:
        if now.tzinfo is None:
            raise ValueError("Execution time requires a timezone")
        _validate_request(request)
        from .settings import btc_cost_policy, report_locale
        result["report_locale"] = report_locale(project, request.get("report_locale"))
        result["btc_cost_policy"] = btc_cost_policy(project, request.get("btc_cost_policy"))
        if (project / "work/update.lock").exists():
            raise ValueError("Another update owns work/update.lock; wait before previewing")
        initial_fingerprint = fingerprint(project)
        identified = identify_inputs(request.get("paths", []))
        if request.get("wealthsimple_only") and "bullbitcoin" in identified:
            raise ValueError("Brokerage-only mode cannot include a Bull CSV")
        with tempfile.TemporaryDirectory(prefix="wealth-ledger-preview-") as directory:
            stage = Path(directory) / "project"
            _snapshot(project, stage)
            input_hashes = {}
            inputs = {}
            for provider, path in identified.items():
                raw = path.read_bytes()
                input_hashes[path] = hashlib.sha256(raw).hexdigest()
                target = stage / "work/inputs" / provider / path.name
                target.parent.mkdir(parents=True)
                target.write_bytes(raw)
                inputs[provider] = target
            overrides = {}
            for key in ("fx_file", "opening_file", "price_file"):
                if request.get(key):
                    path = Path(request[key]).expanduser().resolve()
                    raw = path.read_bytes()
                    input_hashes[path] = hashlib.sha256(raw).hexdigest()
                    json.loads(raw)
                    target = stage / "work/overrides" / key
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(raw)
                    overrides[key] = target
            accepted = {"sources": {}, "detected_inputs": {key: str(path) for key, path in inputs.items()}}
            base_override = None
            if "wealthsimple" in inputs:
                try:
                    plan = inspect_holdings(stage, inputs["wealthsimple"], request.get("kind", "monthly"))
                    date = parse_time(plan["as_of"]).astimezone(LOCAL).date().isoformat()
                    rates = reference("holdings_fx", read_saved_rates(stage, date, overrides.get("fx_file")))
                    if rates is not None:
                        accepted["sources"]["wealthsimple"] = import_holdings(stage, inputs["wealthsimple"], request.get("kind", "monthly"), rates)
                    else:
                        accepted["sources"]["wealthsimple"] = {"status": plan["status"]}
                        if plan["status"] == "duplicate":
                            accepted["sources"]["wealthsimple"]["snapshot_id"] = plan["snapshot_id"]
                        else:
                            base_override = {"meta": {"as_of": plan["as_of"], "snapshot_id": None}}
                    result["sources"]["wealthsimple"] = {
                        "status": plan["status"], "filename": inputs["wealthsimple"].name,
                        "as_of": plan["as_of"], "row_count": plan["rows"], "kind": plan["kind"],
                        "account_count": plan["account_count"], "accounts": plan["accounts"],
                        "is_complete": plan["is_complete"], "missing_account_count": len(plan["missing_accounts"]),
                        "issues": _safe_issues(accepted["sources"]["wealthsimple"].get("issues", plan["issues"])),
                        "input_sha256": input_hashes[identified["wealthsimple"]]}
                except INPUT_ERRORS as exc:
                    block("wealthsimple", exc)
            if "bullbitcoin" in inputs:
                try:
                    path = overrides.get("opening_file", stage / "config/bull-opening.json")
                    opening = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
                    imported = import_bull_orders(stage, inputs["bullbitcoin"], opening_assumption=opening)
                    accepted["sources"]["bullbitcoin"] = imported
                    view = make_crypto_view(stage, now.isoformat(), strict=False)
                    result["sources"]["bullbitcoin"] = {
                        key: imported[key] for key in ("status", "new_orders", "revised_orders", "unchanged_orders", "duplicate_rows")}
                    result["sources"]["bullbitcoin"].update(
                        filename=inputs["bullbitcoin"].name,
                        latest_completed_at=view["source"]["latest_completed_at"],
                        input_sha256=input_hashes[identified["bullbitcoin"]])
                except INPUT_ERRORS as exc:
                    block("bullbitcoin", exc)
            if request.get("btc_balance") is not None:
                try:
                    balance = add_balance(stage, request["btc_balance"], request.get("btc_balance_as_of") or now.isoformat(),
                                          source=request.get("btc_balance_source") or "user_reported_total",
                                          time_basis="explicit" if request.get("btc_balance_as_of") else "execution_time", now=now.isoformat())
                    accepted["sources"]["wallet"] = balance
                    result["sources"]["wallet"] = {key: balance[key] for key in (
                        "status", "quantity_btc", "as_of", "time_basis", "recorded_expected_btc", "recorded_residual_btc")}
                except INPUT_ERRORS as exc:
                    block("wallet", exc)
            if not result["blockers"]:
                try:
                    context = select_context(stage, accepted, snapshot_id=request.get("snapshot_id"),
                                             as_of=request.get("as_of"), now=now, base_override=base_override)
                    if request.get("wealthsimple_only"):
                        if context["base"] is None:
                            raise ValueError("No Wealthsimple holdings for brokerage-only report")
                        context["has_crypto"] = False
                        context["target"] = context["base"]["meta"]["as_of"]
                    if not context["target"]:
                        raise ValueError("No holdings available; provide a supported CSV or BTC balance")
                    if not context["has_crypto"] and not request.get("wealthsimple_only") and (request.get("as_of") or request.get("price_file")):
                        raise ValueError("Combined valuation options require an imported Bull ledger or wallet balance")
                    target = context["target"]
                    if "wallet" in result["sources"]:
                        result["sources"]["wallet"]["included_at_cutoff"] = parse_time(result["sources"]["wallet"]["as_of"]) <= parse_time(target)
                    result["valuation_as_of"] = target
                    result["simulation_complete"] = True
                    result["holdings_as_of"] = context["base"]["meta"]["as_of"] if context["base"] else None
                    result["source_usage"] = {
                        "wealthsimple": "provided" if "wealthsimple" in inputs else "carried_forward" if context["base"] else "not_available",
                        "bullbitcoin": "provided" if "bullbitcoin" in inputs else "carried_forward" if has_bull(stage) else "not_available"}
                    if context["has_crypto"]:
                        crypto = make_crypto_view(stage, target)
                        if Decimal(crypto["cash_cad"]) < 0:
                            raise ValueError("Bull cash ledger is negative; supply missing funding before publishing a combined total")
                        wallet = crypto.get("wallet", {})
                        result["btc"] = {"quantity_btc": crypto["btc_equivalent_qty"], "quantity_basis": quantity_basis_label(crypto),
                                         "unresolved_count": wallet.get("unresolved_count", 0),
                                         "opening_overlap": wallet.get("opening_overlap", False),
                                         "issues": _safe_issues(crypto["issues"]),
                                         "reconciliations": [{key: row[key] for key in ("as_of", "reported_btc", "expected_btc", "residual_btc", "status", "status_label")} for row in wallet.get("reconciliations", [])]}
                        if wallet.get("anchor"):
                            result["btc"]["anchor_as_of"] = wallet["anchor"]["as_of"]
                        quote = reference("btc_price", read_saved_quote(stage, target, overrides.get("price_file")))
                        if quote is not None and overrides.get("price_file") and not quote.get("evidence_sha256"):
                            raise ValueError("Verified BTC quote requires an evidence reference hash")
                    date = parse_time(target).astimezone(LOCAL).date().isoformat()
                    base = context["base"]
                    rates = base.get("fx") if base and base.get("fx") and date == parse_time(base["meta"]["as_of"]).astimezone(LOCAL).date().isoformat() and not overrides.get("fx_file") else read_saved_rates(stage, date, overrides.get("fx_file"))
                    reference("valuation_fx", rates)
                except INPUT_ERRORS as exc:
                    block("context_or_reference", exc)
            if fingerprint(project) != initial_fingerprint:
                block("concurrent_change", ValueError("Live inputs changed during preview; run it again"))
            for path, digest in input_hashes.items():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    block("input_changed", ValueError(f"Input changed during preview: {path.name}"))
        result["simulation_complete"] = not result["blockers"] and bool(result["valuation_as_of"]) and "holdings_fx" not in result["pending_checks"]
        result["status"] = "blocked" if result["blockers"] else "pending_reference" if any(check["status"] == "pending" for check in result["checks"]) else "checked"
    except INPUT_ERRORS as exc:
        block("request_or_snapshot", exc)
    result["pending_checks"] = list(dict.fromkeys(result["pending_checks"]))
    return result


@localized
def render_preview(result):
    """Render the selected language without private order/wallet details."""
    source_labels = {"imported": tr('message.0006d696d8e1'), "revision": tr('message.f8950d4ecec5'), "duplicate": tr('message.6570e4bdc6d3')}
    labels = {"checked": tr('message.9d3781f1cf1b'), "pending_reference": tr('message.22fc51e94f33'), "blocked": tr('message.fec259e0a20c')}
    lines = [tr('message.3d96e1c84610'), tr('message.84ce8be41083', value0=labels[result['status']]),
             tr('message.9ba0ef23e9f6')]
    for provider, source in result["sources"].items():
        if provider == "wealthsimple":
            lines.append(tr('message.3a4ffe9f95f2', value0=source_labels[source['status']], value1=source['row_count'], value2=source['account_count'], value3=source['as_of']))
            lines.append(tr('message.1e4566916e37', value0=tr('message.088b27d0ed00') if source['is_complete'] else tr('message.abf099167903'), value1=source['missing_account_count']))
            for issue in source["issues"]:
                lines.append(tr('message.840b8d3f56c6') + legacy_text(issue["message"]))
        elif provider == "bullbitcoin":
            lines.append(tr('message.31bd8fc4e734', value0=source['new_orders'], value1=source['revised_orders'], value2=source['unchanged_orders'], value3=source['duplicate_rows']))
        else:
            expected = source["recorded_expected_btc"]
            residual = source["recorded_residual_btc"]
            lines.append(tr('message.cb36688b9c0e', value0=source['quantity_btc'], value1=display_time(source['as_of']), value2=tr('message.c7384dae966b') if source['time_basis'] == 'execution_time' else tr('message.c5fe661289d3')))
            lines.append(tr('message.e9ad29006522', value0=expected if expected is not None else tr('message.8d77d1b8cfcd'), value1=residual if residual is not None else tr('message.8d77d1b8cfcd')))
    if result.get("sources", {}).get("wallet", {}).get("included_at_cutoff") is False:
        lines.append(tr('message.62f060b7302e'))
    if result.get("valuation_as_of"):
        lines.append(tr('message.3612aea1751b') + result["valuation_as_of"])
        lines.append(tr('message.0772694efd38') + (result.get("holdings_as_of") or tr('message.be4f923bcf9f')))
    for source, usage in result.get("source_usage", {}).items():
        lines.append(tr('message.948032a28cfd', value0=source) + {"provided": tr('message.1a70223e2e0c'), "carried_forward": tr('message.58c03ac70438'), "not_available": tr('message.be4f923bcf9f')}[usage])
    if result["btc"]:
        lines.append(tr('message.9fb1ffb7179f', value0=result['btc']['quantity_btc'], value1=legacy_text(result['btc']['quantity_basis'])))
        lines.append(tr('message.e5ba636d00f2', value0=result['btc']['unresolved_count']))
        for issue in result["btc"]["issues"]:
            if issue.get("severity") == "warning":
                lines.append(tr('message.840b8d3f56c6') + legacy_text(issue["message"]))
    names = {"holdings_fx": tr('message.fa5c66a809a7'), "valuation_fx": tr('message.4df1309f131e'), "btc_price": tr('message.06a7177c08b5')}
    for check in result["checks"]:
        lines.append(names[check["name"]] + "：" + (tr('message.cf924e591ca3') if check["status"] == "available" else tr('message.3843564dfdeb')))
    for blocker in result["blockers"]:
        lines.append(tr('message.c9a25a3ccfcc', value0=blocker['component'], value1=legacy_text(blocker['message']), value2=legacy_text(blocker['detail'])))
    lines.extend([tr('message.4d3c374acc72'), tr('message.2f46635b0c3e')])
    return "\n".join(lines)
