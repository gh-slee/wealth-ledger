"""Render new language editions from frozen bundles, without ledger/network I/O."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .i18n import normalize_locale, presentation_context, validate_catalogs


def render_language_edition(source, output, locale):
    source, output = Path(source).resolve(), Path(output).resolve()
    locale = normalize_locale(locale)
    validate_catalogs()
    if output.exists() or source == output or source in output.parents:
        raise ValueError("Choose a new output outside the saved source bundle")
    data_path = source / "data.json"
    manifest_path = source / "manifest.json"
    if not manifest_path.exists():
        manifest_path = source / "demo-manifest.json"
    if not data_path.is_file() or not manifest_path.is_file():
        raise ValueError("Saved language editions require data.json and a report manifest")
    raw, manifest_raw = data_path.read_bytes(), manifest_path.read_bytes()
    payload, saved_manifest = json.loads(raw), json.loads(manifest_raw)
    digest = hashlib.sha256(raw).hexdigest()
    expected = saved_manifest.get("data_sha256")
    if expected and expected != digest:
        raise ValueError("Saved report data hash mismatch")
    cutoff = saved_manifest.get("snapshot_as_of", saved_manifest.get("report_as_of"))
    if cutoff and cutoff != payload["meta"]["as_of"]:
        raise ValueError("Saved report manifest and valuation time differ")
    if "lookthrough" not in payload:
        raise ValueError("Saved report has no frozen ETF analysis; offline rendering cannot fetch it")
    run_id = saved_manifest.get("lookthrough_run_id")
    if run_id is not None and run_id != payload["lookthrough"].get("run_id"):
        raise ValueError("Saved report manifest and frozen analysis differ")
    from .lookthrough import portfolio_signature
    signature = portfolio_signature(payload)
    if saved_manifest.get("financial_fingerprint") not in (None, signature):
        raise ValueError("Saved report financial fingerprint mismatch")
    view = deepcopy(payload)
    rendered_at = datetime.now(timezone.utc).isoformat()
    view["meta"]["generated_at"] = rendered_at
    view.setdefault("reporting", {}).update(locale=locale, offline_language_edition=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="language-edition-", dir=output.parent) as temporary:
        bundle = Path(temporary) / "bundle"
        from .reporting import generate_reports
        from .workbook import build_workbook, verify_workbook
        from .validation import validate_formula_caches
        from .report_checks import validate_report_presentation
        from .lookthrough_reports import write_exports
        from .wallet_reports import write_exports as write_wallet_exports
        artifacts = generate_reports(view, bundle, locale=locale)
        build_workbook(view, bundle / "portfolio.ods", chart_images=artifacts["charts"], locale=locale)
        checks = {**verify_workbook(bundle / "portfolio.ods", view["totals"]["total_cad"], locale=locale),
                  **validate_formula_caches(bundle / "portfolio.ods")}
        presentation = validate_report_presentation(view, bundle, locale=locale)
        # Exports and saved financial data retain source language and schema.
        write_exports(payload, bundle)
        write_wallet_exports(payload, bundle)
        (bundle / "data.json").write_bytes(raw)
        with presentation_context(locale) as context:
            localization = context.metadata()
        manifest = {
            "schema_version": 1, "edition_kind": "offline_language_edition",
            "snapshot_id": payload["meta"].get("snapshot_id"), "snapshot_as_of": payload["meta"]["as_of"],
            "combined_observation_id": payload["meta"].get("combined_observation_id"),
            "lookthrough_run_id": payload["lookthrough"].get("run_id"),
            "report_generated_at": rendered_at, "localization": localization,
            "data_sha256": digest, "financial_fingerprint": signature,
            "source_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "source_integrity_basis": "saved_checksum" if expected else "legacy_metadata_consistency",
            "source_lookthrough_mode": payload["lookthrough"].get("mode"),
            "workbook_validation": checks, "presentation_validation": presentation,
            "network_used": False, "ledger_changed": False, "latest_changed": False,
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if data_path.read_bytes() != raw or manifest_path.read_bytes() != manifest_raw:
            raise ValueError("Saved source bundle changed during rendering")
        shutil.copytree(bundle, output)
    return {"output": str(output), **manifest}
