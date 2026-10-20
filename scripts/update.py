#!/usr/bin/env python3
"""Automatically import either supported CSV or both and publish a reproducible report bundle."""

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from wealth_ledger.cli import make_parser, run_main
from wealth_ledger.application import ApplicationService

def main():
    parser = make_parser(PROJECT, description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, help="Financial CSV exports; native mode supports Wealthsimple/Bull, --source-parsers uses enabled trusted adapters")
    parser.add_argument("--input", type=Path, help="Alias for one financial CSV input; detection follows the selected import mode")
    parser.add_argument("--kind", choices=["baseline", "monthly", "interim"], default="monthly")
    parser.add_argument("--fx-file", type=Path, help="Verified six-field exchange-rate JSON override")
    parser.add_argument("--snapshot-id", type=int)
    parser.add_argument("--bull-input", type=Path, help="Bull Bitcoin cumulative or incremental orders CSV")
    parser.add_argument("--bull-opening-file", type=Path, help="Explicit zero opening assumptions JSON for the first Bull import")
    parser.add_argument("--btc-price-file", type=Path, help="Verified timestamp-specific BTC-USD one-minute quote JSON")
    parser.add_argument("--valuation-as-of", help="Timezone-aware combined valuation timestamp; stale broker holdings remain explicitly labeled")
    parser.add_argument("--wealthsimple-only", action="store_true", help="Regenerate brokerage-only reports without the saved crypto ledger")
    parser.add_argument("--lookthrough-run-id",type=int,help="Replay saved company analysis for an identical portfolio valuation; no issuer network requests")
    parser.add_argument("--btc-balance", help="Optional all-wallet BTC+LBTC equivalent quantity, at most eight decimals")
    parser.add_argument("--btc-balance-as-of", help="Timezone-aware wallet observation timestamp; defaults to execution time")
    parser.add_argument("--btc-balance-source", help="Human-readable balance source, default user_reported_total")
    parser.add_argument("--resume-operation", help="Resume committed report inputs without repeating balance/CSV imports")
    parser.add_argument("--list-operations", action="store_true", help="Read saved operation states without modifying data")
    parser.add_argument("--show-operation", help="Read a saved operation by ID")
    parser.add_argument("--dry-run", action="store_true", help="Offline input preview in a disposable project; never commit or publish")
    parser.add_argument("--json", action="store_true", help="Print machine-readable dry-run JSON instead of the Traditional Chinese summary")
    parser.add_argument("--btc-cost-policy", choices=("actual_only", "bull_average_proxy"), help="Explicit BTC report cost policy; defaults to private local setting or actual_only")
    from wealth_ledger.source_import_cli import add_arguments
    add_arguments(parser)
    args = parser.parse_args()
    service = ApplicationService(parser.workspace)
    selected_locale = parser.locale
    paths=[*args.files,*([args.input] if args.input else []),*([args.bull_input] if args.bull_input else [])]
    if args.source_parsers or args.confirm_source_preview:
        from wealth_ledger.source_import_cli import run
        return run(args, service, paths, selected_locale, parser)
    if any((args.plan_directory,args.source_bindings,args.source_context,args.source_config,args.source_select,
            args.source_period_start,args.fetch_source_references,args.approval_sha256)):
        parser.error("Source options require --source-parsers or --confirm-source-preview")
    modes = sum(bool(x) for x in (args.resume_operation, args.list_operations, args.show_operation))
    new_input = bool(paths or args.btc_balance is not None or args.btc_balance_as_of or args.btc_balance_source)
    special = bool(args.snapshot_id is not None or args.fx_file or args.bull_opening_file or args.btc_price_file
                   or args.valuation_as_of or args.wealthsimple_only or args.lookthrough_run_id is not None
                   or args.kind != "monthly" or args.btc_cost_policy is not None or getattr(args, "locale", None) is not None)
    if args.json and not args.dry_run:
        parser.error("--json is only available with --dry-run; normal update output is unchanged")
    if args.dry_run and (modes or args.lookthrough_run_id is not None):
        parser.error("--dry-run cannot include operation query/resume or ETF replay modes")
    if modes > 1 or modes and (new_input or special):
        parser.error("Operation query/resume modes are exclusive and cannot include new inputs/options")
    if args.lookthrough_run_id is not None and new_input:
        parser.error("--lookthrough-run-id only replays identical saved valuations without new inputs")
    if args.snapshot_id is not None and new_input:
        parser.error("--snapshot-id cannot include new inputs")
    if args.wealthsimple_only and (args.btc_balance is not None or args.btc_balance_as_of or args.btc_balance_source
                                  or args.bull_input or args.valuation_as_of or args.btc_price_file):
        parser.error("Brokerage-only mode cannot include wallet/Bull or combined valuation inputs")
    if args.btc_balance is None and (args.btc_balance_as_of or args.btc_balance_source):
        parser.error("Balance time/source require --btc-balance")
    request = {"paths": [str(p.expanduser().resolve()) for p in paths], "kind": args.kind,
               "snapshot_id": args.snapshot_id, "fx_file": str(args.fx_file) if args.fx_file else None,
               "opening_file": str(args.bull_opening_file) if args.bull_opening_file else None,
               "price_file": str(args.btc_price_file) if args.btc_price_file else None,
               "as_of": args.valuation_as_of, "wealthsimple_only": args.wealthsimple_only,
               "lookthrough_run_id": args.lookthrough_run_id, "btc_balance": args.btc_balance,
               "btc_balance_as_of": args.btc_balance_as_of, "btc_balance_source": args.btc_balance_source,
               "btc_cost_policy": args.btc_cost_policy, "report_locale": selected_locale}
    if args.dry_run:
        from wealth_ledger.preflight import render_preview
        result = service.preview(request)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_preview(result, locale=selected_locale))
        return 2 if result["status"] == "blocked" else 0
    try:
        if args.list_operations or args.show_operation:
            result = service.operation(args.show_operation) if args.show_operation else service.operations()
        else:
            result = service.update(request, resume=args.resume_operation)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(run_main(main, PROJECT) or 0)
