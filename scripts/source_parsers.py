#!/usr/bin/env python3
"""Checkout entry point for the shared, installed source-plan CLI."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wealth_ledger.source_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
