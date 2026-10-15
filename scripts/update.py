#!/usr/bin/env python3
"""Automatically import either supported CSV or both and publish a reproducible report bundle."""

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import json
import hashlib
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from wealth_ledger.cli import make_parser, run_main
from wealth_ledger.workflow import identify_inputs, prepare_update
from wealth_ledger import operations
from zoneinfo import ZoneInfo

def database_backup(label):
    source = PROJECT / "data/db/portfolio.sqlite3"
    if not source.exists():
        return None
    directory = PROJECT / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y%m%d-%H%M%S-%f")
    target = directory / f"portfolio-{stamp}-{label}.sqlite3"
    with sqlite3.connect(source) as original, sqlite3.connect(target) as copied:
        original.backup(copied)
    target.chmod(0o600)
    return str(target.relative_to(PROJECT))


def verify_ods(path, payload=None, chart_images=None, locale=None):
    namespace = {
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
        "xlink": "http://www.w3.org/1999/xlink",
    }
    errors = {"#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A", "#NUM!", "#SPILL!", "#CALC!"}
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
        sheets = [sheet.get(f"{{{namespace['table']}}}name") for sheet in root.findall(".//table:table", namespace)]
        formula_count = 0
        numeric_values = []
        for cell in root.findall(".//table:table-cell", namespace):
            formula_count += bool(cell.get(f"{{{namespace['table']}}}formula"))
            value_type = cell.get(f"{{{namespace['office']}}}value-type")
            numeric = cell.get(f"{{{namespace['office']}}}value")
            if numeric is not None:
                numeric_values.append(Decimal(numeric))
            text = "".join(cell.itertext()).strip()
            if value_type == "error" or text in errors or re.fullmatch(r"Err:\s*\d+", text):
                raise ValueError(f"Spreadsheet calculation error: {text}")
        charts = sum(bool(re.search(r"Object\s*\d+/content.xml$", name)) for name in archive.namelist())
        image_paths = [item.get(f"{{{namespace['xlink']}}}href")
                       for item in root.findall(".//draw:image", namespace)]
        image_bytes = []
        for image_path in image_paths:
            if not image_path or not image_path.startswith("Pictures/") or image_path not in archive.namelist():
                raise ValueError("ODS chart image is missing or references an external file")
            data = archive.read(image_path)
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("ODS chart image is not a PNG")
            image_bytes.append(data)
    if len(sheets) < 5 or formula_count == 0 or len(image_paths) < 8:
        raise ValueError("ODS workbook is missing expected worksheets, formulas, or embedded charts")
    if chart_images is not None:
        expected = Counter(Path(value).read_bytes() for value in chart_images.values())
        if Counter(image_bytes) != expected:
            raise ValueError("ODS chart images differ from this report's verified PNG assets")
    checked = 0
    if payload:
        for summary in [payload["totals"], *payload["accounts"]]:
            for key in ("total_cad", "total_usd", "total_twd"):
                expected = Decimal(summary[key])
                if not any(abs(value - expected) < Decimal("0.005") for value in numeric_values):
                    raise ValueError(f"ODS is missing the verified {key} summary value")
                checked += 1
    return {"sheets": sheets, "formula_count": formula_count, "native_chart_count": charts,
            "embedded_chart_count": len(image_paths), "calculation_errors": 0,
            "verified_three_currency_values": checked}


def publish(payload, import_result, lookthrough_run_id=None):
    from wealth_ledger.lookthrough import attach_analysis, portfolio_signature
    attach_analysis(PROJECT,payload,run_id=lookthrough_run_id)
    from wealth_ledger.reporting import generate_reports
    from wealth_ledger.i18n import LEGACY_LOCALE
    locale = payload.get("reporting", {}).get("locale", LEGACY_LOCALE)
    from wealth_ledger.workbook import build_workbook
    from wealth_ledger.validation import validate_formula_caches
    as_of = datetime.fromisoformat(payload["meta"]["as_of"])
    parent = PROJECT / "reports" / as_of.strftime("%Y-%m-%d_%H%M")
    parent.mkdir(parents=True, exist_ok=True)
    revisions = [int(p.name[1:]) for p in parent.glob("r[0-9]*") if p.is_dir() and p.name[1:].isdigit()]
    revision = max(revisions, default=0) + 1
    target = parent / f"r{revision:02d}"
    build = Path(tempfile.mkdtemp(prefix="report-", dir=PROJECT / "work"))
    output = build / "bundle"
    output.mkdir()
    try:
        payload_path = output / "data.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        from wealth_ledger.lookthrough_reports import write_exports
        write_exports(payload, output)
        from wealth_ledger.wallet_reports import write_exports as write_wallet_exports
        write_wallet_exports(payload, output)
        report_result = generate_reports(payload, output, locale=locale)
        ods = output / "portfolio.ods"
        build_workbook(payload, ods, chart_images=report_result["charts"], locale=locale)
        validation = {**verify_ods(ods, payload, report_result["charts"], locale=locale), **validate_formula_caches(ods),
                      "generator": "python_odf_direct", "chart_mode": "embedded_png"}
        for name in ("report.pdf", "report.md", "portfolio.ods"):
            if (output / name).stat().st_size == 0:
                raise ValueError(f"Empty report artifact: {name}")
        from wealth_ledger.report_checks import validate_report_presentation
        presentation_validation = validate_report_presentation(payload, output, locale=locale)
        backup = database_backup("reported")
        manifest = {
            "snapshot_id": payload["meta"]["snapshot_id"],
            "snapshot_as_of": payload["meta"]["as_of"],
            "combined_observation_id": payload["meta"].get("combined_observation_id"),
            "wealthsimple_as_of": payload["meta"].get("wealthsimple_as_of", payload["meta"]["as_of"]),
            "lookthrough_run_id": payload["lookthrough"]["run_id"],
            "lookthrough_mode": payload["lookthrough"]["mode"],
            "quantity_status": payload["meta"].get("quantity_status"),
            "data_status": payload["meta"].get("data_status"),
            "source_updates": payload["meta"].get("source_updates"),
            "localization": report_result["localization"],
            "data_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            "financial_fingerprint": portfolio_signature(payload),
            "report_generated_at": datetime.now(ZoneInfo("America/Toronto")).isoformat(),
            "import": import_result,
            "workbook_validation": validation,
            "presentation_validation": presentation_validation,
            "reporting": {"markdown": "report.md", "pdf": "report.pdf", "supplements": report_result["supplements"], "charts": sorted(str(p.relative_to(output)) for p in (output / "charts").glob("*.png"))},
            "database_backup": backup,
        }
        classification = payload["lookthrough"].get("classification")
        if classification:
            manifest["classification"] = {
                "version": classification["version"], "sector_scheme": classification["sector_scheme"],
                "status": classification["status"],
                "coverage": {dimension: {key: summary[key] for key in
                             ("equity_coverage", "investment_coverage", "as_of_min", "as_of_max")}
                             for dimension, summary in classification["dimensions"].items()},
                "exports": ["allocation-exposure.csv", "classification-detail.csv"],
            }
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        shutil.move(str(output), target)
        for path in target.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
        latest = PROJECT / "reports/latest"
        temporary_link = PROJECT / "reports/.latest-new"
        temporary_link.unlink(missing_ok=True)
        try:
            temporary_link.symlink_to(target.relative_to(latest.parent), target_is_directory=True)
            temporary_link.replace(latest)
        except OSError:
            temporary_link.unlink(missing_ok=True)
            # The dated bundle and JSON pointer work on platforms without symlink privileges.
        pointer = PROJECT / "reports/.latest.json-new"
        pointer.write_text(json.dumps({"path": str(target.relative_to(PROJECT)), "snapshot_id": payload["meta"]["snapshot_id"]}, indent=2) + "\n", encoding="utf-8")
        pointer.replace(PROJECT / "reports/latest.json")
        return {"output": str(target), "snapshot_id": payload["meta"]["snapshot_id"], "workbook": validation, "build_directory": str(build)}
    except Exception:
        print(f"Build preserved for diagnosis: {build}", file=sys.stderr)
        raise


def main():
    parser = make_parser(PROJECT, description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, help="One Wealthsimple or Bull CSV, or one of each; formats are detected automatically")
    parser.add_argument("--input", type=Path, help="CSV input alias; Wealthsimple or Bull format is detected automatically")
    parser.add_argument("--kind", choices=["baseline", "monthly", "interim"], default="monthly")
    parser.add_argument("--fx-file", type=Path, help="Verified six-field exchange-rate JSON override")
    parser.add_argument("--snapshot-id", type=int)
    parser.add_argument("--bull-input", type=Path, help="Bull Bitcoin cumulative or incremental orders CSV")
    parser.add_argument("--bull-opening-file", type=Path, help="Explicit zero opening assumptions JSON for the first Bull import")
    parser.add_argument("--btc-price-file", type=Path, help="Verified timestamp-specific BTC-USD one-minute quote JSON")
    parser.add_argument("--valuation-as-of", help="Timezone-aware combined valuation timestamp; stale broker holdings remain explicitly labeled")
    parser.add_argument("--wealthsimple-only", action="store_true", help="Regenerate brokerage-only reports without the saved crypto ledger")
    parser.add_argument("--lookthrough-run-id",type=int,help="Replay saved company analysis for an identical portfolio valuation; no issuer network requests")
    parser.add_argument("--btc-balance", help="Optional all-wallet BTC+LBTC equivalent quantity, at most eight decimals")
    parser.add_argument("--btc-balance-as-of", help="Timezone-aware wallet observation timestamp; defaults to execution time")
    parser.add_argument("--btc-balance-source", help="Human-readable balance source, default user_reported_total")
    parser.add_argument("--resume-operation", help="Resume committed report inputs without repeating balance/CSV imports")
    parser.add_argument("--list-operations", action="store_true", help="Read saved operation states without modifying data")
    parser.add_argument("--show-operation", help="Read a saved operation by ID")
    parser.add_argument("--dry-run", action="store_true", help="Offline input preview in a disposable project; never commit or publish")
    parser.add_argument("--json", action="store_true", help="Print machine-readable dry-run JSON instead of the Traditional Chinese summary")
    parser.add_argument("--btc-cost-policy", choices=("actual_only", "bull_average_proxy"), help="Explicit BTC report cost policy; defaults to private local setting or actual_only")
    args = parser.parse_args()
    from wealth_ledger.settings import report_locale
    selected_locale = parser.locale
    paths=[*args.files,*([args.input] if args.input else []),*([args.bull_input] if args.bull_input else [])]
    modes = sum(bool(x) for x in (args.resume_operation, args.list_operations, args.show_operation))
    new_input = bool(paths or args.btc_balance is not None or args.btc_balance_as_of or args.btc_balance_source)
    special = bool(args.snapshot_id is not None or args.fx_file or args.bull_opening_file or args.btc_price_file
                   or args.valuation_as_of or args.wealthsimple_only or args.lookthrough_run_id is not None
                   or args.kind != "monthly" or args.btc_cost_policy is not None or getattr(args, "locale", None) is not None)
    if args.json and not args.dry_run:
        parser.error("--json is only available with --dry-run; normal update output is unchanged")
    if args.dry_run and (modes or args.lookthrough_run_id is not None):
        parser.error("--dry-run cannot include operation query/resume or ETF replay modes")
    if modes > 1 or modes and (new_input or special):
        parser.error("Operation query/resume modes are exclusive and cannot include new inputs/options")
    if args.lookthrough_run_id is not None and new_input:
        parser.error("--lookthrough-run-id only replays identical saved valuations without new inputs")
    if args.snapshot_id is not None and new_input:
        parser.error("--snapshot-id cannot include new inputs")
    if args.wealthsimple_only and (args.btc_balance is not None or args.btc_balance_as_of or args.btc_balance_source
                                  or args.bull_input or args.valuation_as_of or args.btc_price_file):
        parser.error("Brokerage-only mode cannot include wallet/Bull or combined valuation inputs")
    if args.btc_balance is None and (args.btc_balance_as_of or args.btc_balance_source):
        parser.error("Balance time/source require --btc-balance")
    request = {"paths": [str(p.expanduser().resolve()) for p in paths], "kind": args.kind,
               "snapshot_id": args.snapshot_id, "fx_file": str(args.fx_file) if args.fx_file else None,
               "opening_file": str(args.bull_opening_file) if args.bull_opening_file else None,
               "price_file": str(args.btc_price_file) if args.btc_price_file else None,
               "as_of": args.valuation_as_of, "wealthsimple_only": args.wealthsimple_only,
               "lookthrough_run_id": args.lookthrough_run_id, "btc_balance": args.btc_balance,
               "btc_balance_as_of": args.btc_balance_as_of, "btc_balance_source": args.btc_balance_source,
               "btc_cost_policy": args.btc_cost_policy, "report_locale": selected_locale}
    if args.dry_run:
        from wealth_ledger.preflight import preview_update, render_preview
        result = preview_update(PROJECT, request)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_preview(result, locale=selected_locale))
        return 2 if result["status"] == "blocked" else 0
    try:
        if args.list_operations or args.show_operation:
            result = operations.get(PROJECT, args.show_operation) if args.show_operation else operations.list_operations(PROJECT)
        else:
            identified = identify_inputs(paths)
            if args.wealthsimple_only and "bullbitcoin" in identified:
                raise ValueError("Brokerage-only mode cannot include a Bull CSV")
            with operations.project_lock(PROJECT):
                database_backup("before-auto-update")
                result = operations.execute_update(PROJECT, request, publish, resume=args.resume_operation)
            pending = [r["operation_id"] for r in operations.list_operations(PROJECT)
                       if r["status"] in ("data_committed", "report_failed")]
            if pending:
                result["pending_report_operations"] = pending
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(run_main(main, PROJECT) or 0)
