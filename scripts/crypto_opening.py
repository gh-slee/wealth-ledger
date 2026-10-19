#!/usr/bin/env python3
"""Record or inspect user-declared, unknown-cost pre-tracking BTC holdings."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'src'))
from wealth_ledger.cli import make_parser, run_main
from wealth_ledger.crypto_opening import import_opening, latest_opening
from wealth_ledger.application import ApplicationService


def main():
    parser=make_parser(PROJECT, description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    command=sub.add_parser('import');command.add_argument('file',type=Path)
    sub.add_parser('show')
    args=parser.parse_args()
    project = parser.workspace.workspace_root
    service = ApplicationService(parser.workspace)
    try:
        if args.command=='import':
            result = service.record(vars(args), lambda stage: import_opening(stage, args.file),
                                    label="before-crypto-opening")
        else:
            result=latest_opening(project)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    raise SystemExit(run_main(main, PROJECT))
