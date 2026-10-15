#!/usr/bin/env python3
"""Import dated flows or explicitly record coverage; then regenerate a report."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from wealth_ledger.cli import make_parser, run_main
from wealth_ledger.settings import ensure_report_locale_setting
from wealth_ledger.operations import project_lock
from wealth_ledger.core import import_cash_flows, mark_flow_period, make_payload
from update import database_backup


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
    if args.command == "accounts":
        result = [{key: row[key] for key in ("account_id", "label", "masked_number")}
                  for row in make_payload(PROJECT)["accounts"]]
    else:
        with project_lock(PROJECT):
            ensure_report_locale_setting(PROJECT)
            database_backup("before-flows")
            if args.command == "import":
                result = import_cash_flows(PROJECT, args.file)
            else:
                result = mark_flow_period(PROJECT, args.start, args.end, args.status, args.account)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(run_main(main, PROJECT))
