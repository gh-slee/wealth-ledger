"""Bounded migration-time evidence for explicitly accepted legacy publications."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import PurePosixPath

from .storage import ARTIFACT_TYPES, MAX_ARTIFACT_BYTES, WebError, contained

MAX_BUNDLE = 256 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_RECEIPT = 16 * 1024 * 1024
FORMAT = "legacy-cli-report-v1"
BASIS = "migration_capture"
ZIP_EVIDENCE = "migration-verification.json"
REQUIRED = {"data.json", "report.md", "report.pdf", "portfolio.ods", "manifest.json"}
MODERN = {"bundle_files", "data_sha256", "financial_fingerprint", "previous_latest", "localization"}
LEGACY_REQUIRED = {"snapshot_id", "snapshot_as_of", "report_generated_at", "import",
                   "workbook_validation", "reporting", "database_backup"}
LEGACY_OPTIONAL = {"combined_observation_id", "wealthsimple_as_of", "lookthrough_run_id",
                   "lookthrough_mode", "quantity_status", "data_status", "source_updates",
                   "classification", "presentation_validation"}


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_object(raw):
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("Duplicate report evidence key")
            result[name] = value
        return result
    def constant(_):
        raise ValueError("Non-finite report evidence")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("Report evidence must be an object")
    return value


def timestamp(value):
    if not isinstance(value, str) or datetime.fromisoformat(value).utcoffset() is None:
        raise ValueError("Report timestamp must have an offset")


def members(project, relative, *, hashes):
    folder = contained(project, relative)
    if not relative.startswith("reports/") or not folder.is_dir():
        raise ValueError("Invalid publication directory")
    result = {}; total = 0
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        contained(folder, name)
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("Unsupported report entry")
        if path.is_dir():
            continue
        size = path.stat().st_size
        if path.suffix.lower() not in ARTIFACT_TYPES or size > MAX_ARTIFACT_BYTES or name == ZIP_EVIDENCE:
            raise ValueError("Unsupported report artifact")
        total += size
        if len(result) >= MAX_MEMBERS or total > MAX_BUNDLE:
            raise ValueError("Report bundle exceeds migration bounds")
        result[name] = {"bytes": size}
        if hashes:
            result[name]["sha256"] = file_digest(path)
    if not REQUIRED.issubset(result) or any(result[n]["bytes"] == 0 for n in REQUIRED):
        raise ValueError("Report bundle is incomplete")
    return result


def inspect_report(project, folder, operation, *, allow_legacy=False):
    try:
        return _inspect_report(project, folder, operation, allow_legacy=allow_legacy)
    except (KeyError, TypeError, AttributeError, RecursionError, UnicodeError) as exc:
        raise ValueError("Unsupported report evidence structure") from exc


def _inspect_report(project, folder, operation, *, allow_legacy=False):
    """Read-only inspection; never add checksums to an original historical manifest."""
    relative = folder.relative_to(project).as_posix()
    manifest_path = contained(project, relative + "/manifest.json")
    if manifest_path.stat().st_size > MAX_RECEIPT:
        raise ValueError("Report manifest exceeds the limit")
    manifest = json_object(manifest_path.read_bytes())
    legacy = not MODERN.intersection(manifest)
    if not legacy:
        from ..publishing import verify_bundle
        checked = verify_bundle(project, folder, operation)
        return {"relative": relative, "operation": operation,
                "as_of": json_object((folder / "data.json").read_bytes())["meta"]["as_of"],
                "snapshot_id": checked["snapshot_id"], "files": sorted(checked["bundle_files"]) + ["manifest.json"]}
    if not allow_legacy:
        raise ValueError("Legacy reports require explicit --allow-legacy-reports and reviewed migration evidence")
    if not LEGACY_REQUIRED.issubset(manifest) or set(manifest) - LEGACY_REQUIRED - LEGACY_OPTIONAL:
        raise ValueError("Unknown legacy report format")
    snapshot = manifest["snapshot_id"]
    if type(snapshot) is not int or snapshot < 0 or not isinstance(manifest["import"], dict):
        raise ValueError("Invalid legacy report identity")
    if manifest["import"].get("operation_id") != operation:
        raise ValueError("Legacy report operation linkage differs")
    timestamp(manifest["snapshot_as_of"]); timestamp(manifest["report_generated_at"])
    reporting = manifest["reporting"]
    if (not isinstance(reporting, dict) or reporting.get("markdown") != "report.md" or
            reporting.get("pdf") != "report.pdf" or not isinstance(manifest["workbook_validation"], dict)):
        raise ValueError("Unknown legacy report declaration")
    files = members(project, relative, hashes=True)
    for field in ("charts", "supplements"):
        paths = reporting.get(field, [])
        if not isinstance(paths, list) or any(not isinstance(p, str) or p not in files for p in paths):
            raise ValueError("Legacy report references missing artifacts")
    data = json_object((folder / "data.json").read_bytes())
    if not {"meta", "totals", "accounts", "positions"}.issubset(data):
        raise ValueError("Unsupported legacy report payload")
    meta = data["meta"]
    if meta.get("snapshot_id") != snapshot or meta.get("as_of") != manifest["snapshot_as_of"]:
        raise ValueError("Legacy report cutoff or snapshot differs")
    evidence = {"format": FORMAT, "version": 1, "basis": BASIS, "relative": relative,
                "snapshot_id": snapshot, "as_of": meta["as_of"], "published_at": manifest["report_generated_at"],
                "operation": operation, "files": files}
    return {"relative": relative, "operation": operation, "as_of": meta["as_of"],
            "snapshot_id": snapshot, "files": sorted(files), "evidence": evidence}


def legacy_evidence(store, portfolio, report):
    """Bind immutable artifact registrations to the reviewed adoption receipt."""
    try:
        return _legacy_evidence(store, portfolio, report)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, RecursionError) as exc:
        raise WebError(409, "report_integrity", "Migration verification evidence needs local review") from exc


def _legacy_evidence(store, portfolio, report):
    _, project = store.portfolio(portfolio)
    with closing(store.connect()) as conn:
        job = conn.execute("SELECT result_json FROM jobs WHERE id=? AND portfolio_id=? AND kind='update' AND status='published'",
                           (report, portfolio)).fetchone()
        if not job:
            return None
        registration = json_object(job["result_json"])
        if registration.get("adopted") is not True:
            if "legacy_evidence_sha256" in registration:
                raise ValueError("Legacy evidence requires adoption")
            return None
        artifacts = conn.execute("SELECT * FROM artifacts WHERE report_id=? AND portfolio_id=?", (report, portfolio)).fetchall()
    receipt_path = contained(store.root, "admin/adoptions/" + portfolio + ".json")
    if not receipt_path.is_file() or receipt_path.stat().st_size > MAX_RECEIPT:
        raise ValueError("Adoption receipt is missing or oversized")
    receipt = json_object(receipt_path.read_bytes())
    if receipt.get("version") != 1 or receipt.get("portfolio_id") != portfolio:
        raise ValueError("Adoption receipt scope differs")
    payloads = [a for a in artifacts if PurePosixPath(a["relative_path"]).name == "data.json"]
    if len(payloads) != 1:
        raise ValueError("Adopted publication payload scope differs")
    directory = PurePosixPath(payloads[0]["relative_path"]).parent.as_posix()
    evidence = receipt.get("legacy_reports", {}).get(directory)
    if evidence is None:
        if "legacy_evidence_sha256" in registration:
            raise ValueError("Legacy receipt evidence is missing")
        return None
    from .jobs import digest
    if (registration.get("legacy_evidence_sha256") != digest(evidence) or evidence.get("format") != FORMAT
            or evidence.get("version") != 1 or evidence.get("basis") != BASIS or evidence.get("relative") != directory
            or evidence.get("as_of") != registration["valuation_as_of"]
            or evidence.get("snapshot_id") != registration["snapshot_id"]
            or evidence.get("operation") != registration.get("source_operation_id")):
        raise ValueError("Legacy verification binding differs")
    if receipt["verification_captured_at"] != registration.get("legacy_capture_at"):
        raise ValueError("Migration capture date differs")
    timestamp(receipt["verification_captured_at"]); timestamp(evidence["published_at"])
    expected = evidence["files"]
    actual = members(project, directory, hashes=False)
    registered = {}
    for artifact in artifacts:
        path = PurePosixPath(artifact["relative_path"])
        if not path.is_relative_to(PurePosixPath(directory)):
            raise ValueError("Legacy registered scope differs")
        name = path.relative_to(directory).as_posix()
        if name in registered:
            raise ValueError("Duplicate legacy artifact")
        registered[name] = {"bytes": artifact["byte_size"], "sha256": artifact["sha256"]}
    if registered != expected or set(actual) != set(expected) or any(actual[n]["bytes"] != expected[n]["bytes"] for n in actual):
        raise ValueError("Legacy artifact scope or registry differs")
    if file_digest(contained(project, directory + "/manifest.json")) != expected["manifest.json"]["sha256"]:
        raise ValueError("Legacy manifest changed")
    return {"evidence": evidence, "captured_at": receipt["verification_captured_at"]}
