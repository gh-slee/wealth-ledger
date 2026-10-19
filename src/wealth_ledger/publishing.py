"""Validated report bundles and SQLite backups, independent of CLI or HTTP."""

from contextlib import closing
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

from zoneinfo import ZoneInfo

def database_backup(project, label):
    project = Path(project)
    source = project / "data/db/portfolio.sqlite3"
    if not source.exists():
        return None
    directory = project / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y%m%d-%H%M%S-%f")
    target = directory / f"portfolio-{stamp}-{label}.sqlite3"
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original, closing(sqlite3.connect(target)) as copied:
        original.backup(copied)
    target.chmod(0o600)
    return str(target.relative_to(project))


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
                if summary[key] is None and payload.get("meta", {}).get("report_model") == "source-neutral-1":
                    continue
                expected = Decimal(summary[key])
                if not any(abs(value - expected) < Decimal("0.005") for value in numeric_values):
                    raise ValueError(f"ODS is missing the verified {key} summary value")
                checked += 1
    return {"sheets": sheets, "formula_count": formula_count, "native_chart_count": charts,
            "embedded_chart_count": len(image_paths), "calculation_errors": 0,
            "verified_three_currency_values": checked}



def _set_latest(project, target, snapshot_id):
    latest = project / "reports/latest"
    temporary = project / "reports/.latest-new"
    temporary.unlink(missing_ok=True)
    try:
        temporary.symlink_to(target.relative_to(latest.parent), target_is_directory=True)
        temporary.replace(latest)
    except OSError:
        temporary.unlink(missing_ok=True)
    pointer = project / "reports/.latest.json-new"
    pointer.write_text(json.dumps({"path": str(target.relative_to(project)), "snapshot_id": snapshot_id}, indent=2) + "\n", encoding="utf-8")
    pointer.replace(project / "reports/latest.json")


def verify_bundle(project, target, operation_id):
    """Verify every published byte before recovery or Web artifact registration."""
    project, target = Path(project).resolve(), Path(target)
    if target.is_symlink() or not target.resolve().is_relative_to(project / "reports"):
        raise ValueError("Invalid report bundle location")
    manifest = json.loads((target / "manifest.json").read_text())
    if manifest.get("import", {}).get("operation_id") != operation_id:
        raise ValueError("Report operation linkage differs")
    expected = manifest.get("bundle_files", {})
    required = {"data.json", "report.md", "report.pdf", "portfolio.ods"}
    if not required.issubset(expected):
        raise ValueError("Report recovery requires a complete checksummed bundle")
    actual = set()
    for path in target.rglob("*"):
        if path.is_symlink():
            raise ValueError("Report bundle contains a symlink")
        if path.is_file() and path.name != "manifest.json":
            name = path.relative_to(target).as_posix(); actual.add(name)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected.get(name):
                raise ValueError("Report artifact checksum differs")
    if actual != set(expected):
        raise ValueError("Report artifact scope differs")
    if manifest["data_sha256"] != expected["data.json"]:
        raise ValueError("Report payload checksum differs")
    return manifest


def recover_publication(project, operation_id):
    """Finish a proven bundle/pointer handoff; never create a second edition."""
    project = Path(project)
    matches = []
    for path in (project / "reports").glob("*/r*/manifest.json"):
        if path.is_symlink():
            raise ValueError("Unsafe report manifest")
        manifest = json.loads(path.read_text())
        if manifest.get("import", {}).get("operation_id") == operation_id:
            matches.append(path.parent)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("Multiple report bundles require local review")
    target = matches[0]
    manifest = verify_bundle(project, target, operation_id)
    pointer = project / "reports/latest.json"
    current = json.loads(pointer.read_text()) if pointer.exists() else None
    own = {"path": str(target.relative_to(project)), "snapshot_id": manifest["snapshot_id"]}
    if current not in (own, manifest.get("previous_latest")):
        raise ValueError("Latest report changed; publication recovery requires review")
    _set_latest(project, target, manifest["snapshot_id"])
    return {"output": str(target), "snapshot_id": manifest["snapshot_id"],
            "workbook": manifest["workbook_validation"]}

def publish(project, payload, import_result, lookthrough_run_id=None):
    project = Path(project)
    pointer = project / "reports/latest.json"
    previous_latest = json.loads(pointer.read_text()) if pointer.exists() else None
    from wealth_ledger.lookthrough import attach_analysis, portfolio_signature
    attach_analysis(project,payload,run_id=lookthrough_run_id)
    from wealth_ledger.reporting import generate_reports
    from wealth_ledger.i18n import LEGACY_LOCALE
    locale = payload.get("reporting", {}).get("locale", LEGACY_LOCALE)
    from wealth_ledger.workbook import build_workbook
    from wealth_ledger.validation import validate_formula_caches
    as_of = datetime.fromisoformat(payload["meta"]["as_of"])
    parent = project / "reports" / as_of.strftime("%Y-%m-%d_%H%M")
    parent.mkdir(parents=True, exist_ok=True)
    revisions = [int(p.name[1:]) for p in parent.glob("r[0-9]*") if p.is_dir() and p.name[1:].isdigit()]
    revision = max(revisions, default=0) + 1
    target = parent / f"r{revision:02d}"
    build = Path(tempfile.mkdtemp(prefix="report-", dir=project / "work"))
    output = build / "bundle"
    output.mkdir()
    try:
        payload_path = output / "data.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        from wealth_ledger.lookthrough_reports import write_exports
        write_exports(payload, output)
        from wealth_ledger.wallet_reports import write_exports as write_wallet_exports
        write_wallet_exports(payload, output)
        report_result = generate_reports(payload, output, locale=locale, cache_directory=project / "work/cache")
        ods = output / "portfolio.ods"
        build_workbook(payload, ods, chart_images=report_result["charts"], locale=locale)
        validation = {**verify_ods(ods, payload, report_result["charts"], locale=locale), **validate_formula_caches(ods),
                      "generator": "python_odf_direct", "chart_mode": "embedded_png"}
        for name in ("report.pdf", "report.md", "portfolio.ods"):
            if (output / name).stat().st_size == 0:
                raise ValueError(f"Empty report artifact: {name}")
        from wealth_ledger.report_checks import validate_report_presentation
        presentation_validation = validate_report_presentation(payload, output, locale=locale)
        backup = database_backup(project, "reported")
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
        manifest["previous_latest"] = previous_latest
        manifest["bundle_files"] = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted(output.rglob("*")) if p.is_file()}
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        shutil.move(str(output), target)
        for path in target.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
        _set_latest(project, target, payload["meta"]["snapshot_id"])
        return {"output": str(target), "snapshot_id": payload["meta"]["snapshot_id"], "workbook": validation, "build_directory": str(build)}
    except Exception:
        print(f"Build preserved for diagnosis: {build}", file=sys.stderr)
        raise
