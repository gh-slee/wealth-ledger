#!/usr/bin/env python3
"""Render a new offline language edition from a saved report; never update the ledger or latest pointer"""
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from wealth_ledger.cli import make_parser, run_main
from wealth_ledger.editions import render_language_edition


def main():
    parser = make_parser(PROJECT, description=__doc__)
    parser.add_argument("--from-report", required=True, type=Path,
                        help="Saved report bundle containing data.json and manifest.json")
    parser.add_argument("--output", required=True, type=Path,
                        help="New output directory; existing paths are never overwritten")
    args = parser.parse_args()
    result = render_language_edition(args.from_report, args.output, parser.locale)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(run_main(main, PROJECT) or 0)
