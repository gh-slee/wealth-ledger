#!/usr/bin/env python3
"""Inspect and append/revise all-wallet BTC+LBTC equivalent observations."""
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from wealth_ledger.wallet_cli import run
from update import database_backup

if __name__ == "__main__":
    run(PROJECT, "balance", database_backup)
