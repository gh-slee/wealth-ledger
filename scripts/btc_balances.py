#!/usr/bin/env python3
"""Inspect and append/revise all-wallet BTC+LBTC equivalent observations."""
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from wealth_ledger.wallet_cli import run
from wealth_ledger.cli import run_main

if __name__ == "__main__":
    sys.exit(run_main(lambda: run(PROJECT, "balance"), PROJECT) or 0)
