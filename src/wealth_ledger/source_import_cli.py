"""Everyday CLI bridge to frozen parser preparation; no implicit confirmation."""
import json
from pathlib import Path
from .source_pipeline import bounded_read, _json
from .source_submission import parse_bindings


def add_arguments(parser):
    parser.add_argument("--source-parsers", action="store_true", help="Prepare a parser-based import for explicit approval; no automatic commit")
    parser.add_argument("--plan-directory", type=Path, help="New private frozen source-preview directory")
    parser.add_argument("--source-bindings", type=Path, help="Reviewed per-portfolio source account choices JSON")
    parser.add_argument("--source-context", type=Path, help="Optional schema_version/inputs JSON of per-file context overrides")
    parser.add_argument("--source-config", type=Path, help="Trusted host exact-version parser configuration")
    parser.add_argument("--source-select", action="append", default=[], help="Explicit enabled adapter selection SLOT=ADAPTER_ID")
    parser.add_argument("--source-period-start", help="Explicit offset-aware cash-flow analysis period start")
    parser.add_argument("--fetch-source-references", action="store_true", help="Explicitly fetch public dated FX/BTC references into private caches before preparing approval")
    parser.add_argument("--confirm-source-preview", type=Path, help="Confirm a previously reviewed frozen source preview")
    parser.add_argument("--approval-sha256", help="Exact reviewed source preview digest")


def run(args, service, paths, locale, parser):
    if args.confirm_source_preview:
        if (not args.approval_sha256 or args.source_parsers or paths or args.btc_balance is not None
                or args.resume_operation or args.dry_run or args.list_operations or args.show_operation
                or args.fx_file or args.btc_price_file or args.valuation_as_of or args.btc_cost_policy
                or args.snapshot_id is not None or args.bull_opening_file or args.wealthsimple_only
                or args.lookthrough_run_id is not None or args.source_bindings or args.source_context
                or args.plan_directory or args.source_period_start or args.fetch_source_references or args.source_select
                or args.btc_balance_as_of or args.btc_balance_source or args.kind != "monthly" or args.json):
            parser.error("Confirmation requires only the frozen preview, exact digest and matching host configuration")
        result = service.source_report_confirm(args.confirm_source_preview, args.approval_sha256, config_path=args.source_config)
    else:
        if (not args.plan_directory or args.approval_sha256 or args.resume_operation or args.list_operations
                or args.show_operation or args.snapshot_id is not None or args.lookthrough_run_id is not None
                or args.wealthsimple_only or args.bull_opening_file):
            parser.error("Parser preview requires --plan-directory and cannot include legacy/query/resume options")
        if args.dry_run and args.fetch_source_references:
            parser.error("Offline --dry-run cannot fetch references")
        options = []
        if args.source_context:
            document = _json(bounded_read(args.source_context,65536))
            if not isinstance(document,dict) or set(document)!={"schema_version","inputs"} or type(document['schema_version']) is not int or document['schema_version']!=1:
                raise ValueError("Invalid source context options")
            options = document['inputs']
        bindings = parse_bindings(_json(bounded_read(args.source_bindings,65536))) if args.source_bindings else ()
        selections = {}
        for entry in args.source_select:
            slot, adapter = entry.split('=',1)
            if slot in selections: raise ValueError("Duplicate parser selection")
            selections[slot] = adapter
        balance = None
        if args.btc_balance is not None:
            if not args.btc_balance_as_of: parser.error("Parser-based totals require an explicit observation timestamp")
            balance = {"quantity_btc":args.btc_balance,"as_of":args.btc_balance_as_of,"source":args.btc_balance_source or "user_reported_total"}
        elif args.btc_balance_as_of or args.btc_balance_source: parser.error("Balance context requires --btc-balance")
        result = service.source_import_preview(paths, directory=args.plan_directory, context_options=options, bindings=bindings,
            config_path=args.source_config,selections=selections,as_of=args.valuation_as_of,period_start=args.source_period_start,
            kind=args.kind,fx=_json(bounded_read(args.fx_file,65536)) if args.fx_file else None,
            btc_price=_json(bounded_read(args.btc_price_file,65536)) if args.btc_price_file else None,
            balance=balance, reference_policy="fetch_public" if args.fetch_source_references else "saved_only",
            report_locale=locale,btc_cost_policy=args.btc_cost_policy)
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
