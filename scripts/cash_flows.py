#!/usr/bin/env python3
"""Import dated flows or explicitly record coverage; then regenerate a report."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from wealth_ledger.cli import make_parser, run_main
from wealth_ledger.core import import_cash_flows, mark_flow_period
from wealth_ledger.application import ApplicationService


def main():
    parser = make_parser(PROJECT, description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("accounts", help="List stable account IDs needed by the input template")
    import_command = commands.add_parser("import")
    import_command.add_argument("file", type=Path)
    confirm = commands.add_parser("coverage")
    confirm.add_argument("--start", required=True)
    confirm.add_argument("--end", required=True)
    confirm.add_argument("--status", choices=["partial", "complete", "no_external"], required=True)
    confirm.add_argument("--account", default="portfolio")
    args = parser.parse_args()
    service = ApplicationService(parser.workspace)
    if args.command == "accounts":
        result = service.accounts()
    else:
        def action(stage):
            if args.command == "import":
                return import_cash_flows(stage, args.file)
            return mark_flow_period(stage, args.start, args.end, args.status, args.account)
        result = service.record(vars(args), action, label="before-flows")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(run_main(main, PROJECT))
