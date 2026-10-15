#!/usr/bin/env python3
"""Record or inspect user-declared, unknown-cost pre-Bull holdings."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'src'))
from wealth_ledger.cli import make_parser, run_main
from wealth_ledger.settings import ensure_report_locale_setting
from wealth_ledger.operations import project_lock
from wealth_ledger.crypto_opening import import_opening, latest_opening
from update import database_backup


def main():
    parser=make_parser(PROJECT, description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    command=sub.add_parser('import');command.add_argument('file',type=Path)
    sub.add_parser('show')
    args=parser.parse_args()
    try:
        if args.command=='import':
            with project_lock(PROJECT):
                ensure_report_locale_setting(PROJECT)
                database_backup('before-crypto-opening')
                result=import_opening(PROJECT,args.file)
        else:
            result=latest_opening(PROJECT)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    raise SystemExit(run_main(main, PROJECT))
