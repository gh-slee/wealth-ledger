"""Shared parser-driven import preparation; defaults are frozen before approval."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile

from . import source_ingestion as ingestion
from .operations import project_lock
from .prices import parse_time
from .source_context_pipeline import parse_sources, contexts_from_document, context_document
from .source_pipeline import bounded_read, INPUT_BYTES
from .source_submission import SubmissionError, _all_bindings, mapping_review, _pending
from .source_publication import prepare_source_report, balance_input, _apply_balance
from .workspace import resolve_workspace

FX_KEYS = ("usd_cad", "usd_twd", "usd_cad_date", "usd_twd_date", "usd_cad_source", "usd_twd_source")
PRICE_KEYS = ("provider", "pair", "close", "as_of", "candle_start", "candle_end", "source_url")


def default_contexts(paths, options, now):
    if not isinstance(options, (tuple, list)) or options and len(options) != len(paths):
        raise SubmissionError("invalid_context")
    rows = []
    for path, choice in zip(paths, options or [{} for _ in paths]):
        if not isinstance(choice, dict) or set(choice) - {"account_alias", "source_timezone", "format_selection", "revisions", "scope_revisions"}:
            raise SubmissionError("invalid_context")
        raw = bounded_read(path, INPUT_BYTES)
        rows.append({"evidence_at": now, "source_reference": "sha256:" + hashlib.sha256(raw).hexdigest(), **choice})
    return contexts_from_document({"schema_version": 1, "inputs": rows}, len(paths)) if paths else ()


def prepare_import(project, paths=(), *, directory, context_options=(), bindings=(), config_path=None,
                   selections=None, as_of=None, period_start=None, kind="monthly", fx=None, btc_price=None,
                   balance=None, reference_policy="saved_only", report_locale=None, btc_cost_policy=None,
                   now=None, operation_id=None):
    """Prepare a reviewable source import, with no fact writes before confirmation.

    The opt-in fetch_public policy may fill date-bound private reference caches;
    ordinary preview uses only supplied/saved references and never downloads.
    """
    project = resolve_workspace(explicit=project).workspace_root
    now = parse_time(now or datetime.now(timezone.utc).isoformat()).isoformat()
    if reference_policy not in {"saved_only", "fetch_public"}: raise SubmissionError("invalid_reference_policy")
    if not paths and (context_options or bindings or selections): raise SubmissionError("invalid_source_scope")
    if balance is not None:
        if not isinstance(balance, dict) or set(balance) - {"quantity_btc", "as_of", "source"} or not {"quantity_btc", "as_of"} <= set(balance):
            raise SubmissionError("invalid_balance")
        balance = balance_input({**balance, "source": balance.get("source", "user_reported_total"), "recorded_at": now})
    with project_lock(project):
        _pending(project)
        contexts = default_contexts(paths, context_options, now)
        parsed = parse_sources(paths, contexts=contexts, config_path=config_path, selections=selections) if paths else None
        snapshots = [s.as_of for batch in parsed.batches for s in batch.snapshots] if parsed else []
        target = parse_time(as_of).isoformat() if as_of else (max(snapshots).isoformat() if snapshots and
            all(r.kind == "holdings" for batch in parsed.batches for r in batch.records) and balance is None else
            parse_time(now).replace(second=0, microsecond=0).isoformat())
        if parse_time(target) > parse_time(now): raise SubmissionError("future_valuation")
        if balance and parse_time(balance["as_of"]) > parse_time(target):
            if as_of: raise SubmissionError("balance_after_valuation")
            target = now
        start = parse_time(period_start).isoformat() if period_start else parse_time(target).replace(month=1,day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
        preparation = {"valuation_as_of": target, "period_start": start, "valuation_policy": "explicit" if as_of else
                       "incoming_holdings_time" if snapshots and target == max(snapshots).isoformat() else "execution_time",
                       "period_policy": "explicit" if period_start else "calendar_year_start", "reference_policy": reference_policy,
                       "contexts": context_document(contexts)["inputs"], "inputs": parsed.receipt["inputs"] if parsed else [],
                       "source_absence": "No new CSV is not evidence of no activity"}
        plan = None
        if parsed:
            try: effective = _all_bindings(project, parsed.batches, bindings)
            except SubmissionError as exc:
                if exc.code != "binding_required": raise
                return {"preparation": preparation, "preview": {"status": "mapping_required", "account_review": mapping_review(project, parsed.batches), "report_published": False}}
            plan = ingestion.prepare_ingestion(project, tuple(ingestion.SourceInput(b, r) for b,r in zip(parsed.batches,parsed.raw)), bindings=effective)
        from .preflight import _snapshot
        from .source_legacy_projection import project_compatible_sources
        with tempfile.TemporaryDirectory(prefix="source-import-defaults-") as temporary:
            stage = Path(temporary) / "portfolio"; _snapshot(project, stage)
            if plan: ingestion._apply(stage, plan)
            _apply_balance(stage, balance)
            # Later saved wallet/purchase evidence must not disappear behind an
            # older incoming holdings snapshot chosen by the default policy.
            current = project_compatible_sources(stage, as_of=now, period_start=start)
            later = [r["occurred_at"] for r in current["btc"]["purchases"]]
            later += [r["as_of"] for r in current["wallet"]["observations"]]
            if not as_of and any(parse_time(at) > parse_time(target) for at in later):
                target = now
                if not period_start:
                    start = parse_time(target).replace(month=1,day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
                preparation.update(valuation_as_of=target, period_start=start, valuation_policy="execution_time")
            model = project_compatible_sources(stage, as_of=target, period_start=start)
        from .fx import read_saved_rates, resolve_rates
        from .prices import read_saved_quote, resolve_btc_price
        day = parse_time(target).date().isoformat()
        rates = fx if fx is not None else (resolve_rates(project, day) if reference_policy == "fetch_public" else read_saved_rates(project, day))
        price = btc_price
        needs_price = model["btc"]["quantity_btc"] is not None and not model["btc"]["valuation_blocked"]
        if price is None and needs_price:
            price = resolve_btc_price(project, target) if reference_policy == "fetch_public" else read_saved_quote(project, target)
        missing = (["fx"] if rates is None else []) + (["btc_price"] if needs_price and price is None else [])
        if missing:
            return {"preparation": preparation, "preview": {"status": "reference_required", "missing_references": missing,
                    "account_review": [], "report_published": False}}
        try:
            valuation = {"as_of": target, "period_start": start, "generated_at": now, "kind": kind,
                         "fx": {key: rates[key] for key in FX_KEYS}}
            if price is not None: valuation["btc_price"] = {key: price[key] for key in PRICE_KEYS}
        except (KeyError, TypeError): raise SubmissionError("invalid_reference") from None
        if report_locale is not None: valuation["report_locale"] = report_locale
        if btc_cost_policy is not None: valuation["btc_cost_policy"] = btc_cost_policy
        result = prepare_source_report(project, paths, valuation=valuation, directory=directory, contexts=contexts,
            bindings=bindings, config_path=config_path, selections=selections, operation_id=operation_id, balance=balance, _parsed=parsed)
        return {"preparation": preparation, "preview": result}
