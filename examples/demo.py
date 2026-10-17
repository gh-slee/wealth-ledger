#!/usr/bin/env python3
"""Render a synthetic offline report in an isolated temporary ledger."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from wealth_ledger.core import import_holdings
from wealth_ledger.crypto import import_bull_orders
from wealth_ledger.combined import make_combined_payload
from wealth_ledger.fund_sources import holding
from wealth_ledger.lookthrough import attach_analysis, portfolio_signature
from wealth_ledger.lookthrough_reports import write_exports as write_analysis_exports
from wealth_ledger import reporting
from wealth_ledger.reporting import generate_reports
from wealth_ledger.report_checks import validate_report_presentation
from wealth_ledger.validation import validate_formula_caches
from wealth_ledger.wallet_reports import write_exports as write_wallet_exports
from wealth_ledger.workbook import build_workbook, verify_workbook


def synthetic_fund(fund_id, directory):
    """Supply invented analysis data, explicitly not current official holdings."""
    return {
        "fund_id": fund_id, "status": "ok", "as_of": "2024-01-31",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "issuer": "SYNTHETIC DEMONSTRATION", "latest_checked": False,
        "official_url": "https://example.test/synthetic-etf-holdings",
        "evidence": [],
        "rows": [
            holding("Synthetic Alpha Corporation", 60, ticker="DEMO-A", country="CA", gics_sector="Industrials"),
            holding("Synthetic Beta Corporation", 35, ticker="DEMO-B", country="US", gics_sector="Information Technology"),
            holding("Synthetic cash", 5, "cash"),
        ],
    }


def run_demo(output: Path, btc_cost_policy: str, locale="en-CA") -> dict:
    """Keep all synthetic database, source and history writes outside real state."""
    output = output.resolve()
    if output.exists():
        raise ValueError("Demo output already exists; choose a new path to avoid overwriting files")
    data = PROJECT / "examples/data"
    fx = json.loads((data / "fx.json").read_text(encoding="utf-8"))
    quote_path = data / "btc-price.json"
    quote = json.loads(quote_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="wealth-ledger-synthetic-demo-") as temporary:
        ledger = Path(temporary) / "ledger"
        (ledger / "config").mkdir(parents=True)
        shutil.copyfile(PROJECT / "config/company-aliases.json", ledger / "config/company-aliases.json")
        (ledger / "config/local.toml").write_text(
            f'[reporting]\nbtc_cost_policy = "{btc_cost_policy}"\n', encoding="utf-8")
        opening = json.loads((PROJECT / "config/bull-opening.example.json").read_text(encoding="utf-8"))
        # Any accidental production HTTP invocation fails instead of going online.
        with patch("urllib.request.urlopen", side_effect=AssertionError("Offline demo forbids network")), \
             patch("wealth_ledger.prices.urlopen", side_effect=AssertionError("Offline demo forbids network")), \
             patch("wealth_ledger.fund_sources.Client.get", side_effect=AssertionError("Offline demo forbids network")):
            import_holdings(ledger, data / "wealthsimple-holdings.csv", "baseline", fx)
            import_bull_orders(ledger, data / "bull-orders.csv", opening_assumption=opening)
            payload = make_combined_payload(ledger, as_of=quote["as_of"], price_file=quote_path, fx=fx)
            attach_analysis(ledger, payload, fetcher=synthetic_fund)
            payload["lookthrough"]["mode"] = "synthetic_demo"
            notice = {"en-CA": "SYNTHETIC OFFLINE DEMO: all holdings, prices, amounts and ETF constituents are invented; not live data or formal analysis.", "zh-TW": "合成離線示範：所有金額、持倉、價格與 ETF 成分均為虛構；不是行情或正式分析。", "zh-CN": "合成离线演示：所有金额、持仓、价格与 ETF 成分均为虚构；不是行情或正式分析。"}[locale]
            payload["issues"].append({"severity": "info", "code": "synthetic_demo", "message": notice})
            bundle = Path(temporary) / "bundle"
            original_sections = reporting._sections
            def marked_sections(value, charts):
                sections = original_sections(value, charts)
                for section in sections:
                    section.introduction.insert(0, notice)
                return sections
            with patch("wealth_ledger.reporting._sections", side_effect=marked_sections):
                artifacts = generate_reports(payload, bundle, locale=locale)
            build_workbook(payload, bundle / "portfolio.ods", chart_images=artifacts["charts"], locale=locale)
            write_analysis_exports(payload, bundle)
            write_wallet_exports(payload, bundle)
            formula_checks = validate_formula_caches(bundle / "portfolio.ods")
            workbook_checks = verify_workbook(bundle / "portfolio.ods", payload["totals"]["total_cad"], locale=locale)
            presentation_checks = validate_report_presentation(payload, bundle, locale=locale)
        (bundle / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {
            "data_kind": "synthetic_offline_demo_only", "locale": locale, "btc_cost_policy": btc_cost_policy,
            "localization": artifacts["localization"],
            "data_sha256": hashlib.sha256((bundle / "data.json").read_bytes()).hexdigest(),
            "financial_fingerprint": portfolio_signature(payload),
            "report_as_of": payload["meta"]["as_of"], "total_cad": payload["totals"]["total_cad"],
            "formula_validation": formula_checks, "workbook_validation": workbook_checks,
            "presentation_validation": presentation_checks,
            "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.iterdir() if p.is_file()},
            "notice": "All financial values and ETF holdings are invented. No live data or user ledger is accessed.",
        }
        (bundle / "demo-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (bundle / "SYNTHETIC-DEMO.txt").write_text(
            "SYNTHETIC OFFLINE DEMO: all amounts, orders, holdings, prices and ETF constituents are invented; not market data or formal analysis.\n",
            encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle, output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "work/demo",
                        help="New output directory; existing directories are never overwritten")
    parser.add_argument("--btc-cost-policy", choices=("actual_only", "bull_average_proxy"), default="actual_only")
    parser.add_argument("--locale", choices=("en-CA", "zh-TW", "zh-CN"), default="en-CA")
    args = parser.parse_args()
    try:
        result = run_demo(args.output, args.btc_cost_policy, args.locale)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output": str(args.output.resolve()), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
