#!/usr/bin/env python3
"""Export only API types using a disposable owner, never a real instance."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from wealth_ledger.web.api import create_app
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.storage import prepare_instance, Store
    with tempfile.TemporaryDirectory(prefix="wealth-ledger-schema-") as directory:
        settings = WebSettings(Path(directory)/"instance")
        prepare_instance(settings)
        # The schema factory only requires an owner record; no login is attempted.
        Store(settings).set_owner("schema", "non-authenticating-schema-placeholder")
        value = create_app(settings).openapi()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
