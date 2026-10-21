"""Invented old publications retain bytes and gain separate migration evidence."""
from contextlib import closing
from datetime import datetime
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

import test_web as foundation
import test_web_adoption as adoption_tests
from wealth_ledger.operations import fingerprint

if foundation.AVAILABLE:
    from fastapi.testclient import TestClient
    from wealth_ledger.web.adoption import prepare_adoption, confirm_adoption, verify_portfolio
    from wealth_ledger.web.backups import backup_instance, restore_instance, validate_instance, database_info
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.storage import Store, WebError
    from wealth_ledger.web.jobs import digest
    from wealth_ledger.web.api import create_app
    from wealth_ledger.web.report_evidence import inspect_report, ZIP_EVIDENCE

ROOT = Path(__file__).resolve().parents[1]


def legacy_manifest(payload):
    """An independently authored pre-checksum schema, not a stripped real report."""
    return {"snapshot_id": payload["meta"]["snapshot_id"], "snapshot_as_of": payload["meta"]["as_of"],
            "report_generated_at": "2024-02-02T12:00:00-05:00", "import": {},
            "workbook_validation": {"generator": "python_odf_direct"},
            "reporting": {"markdown": "report.md", "pdf": "report.pdf", "charts": ["charts/allocation.png"]},
            "database_backup": None}


@unittest.skipUnless(foundation.AVAILABLE, "Optional Web dependencies are not installed")
class LegacyAdoptionTests(unittest.TestCase):
    setUp = foundation.WebTests.setUp
    bootstrap = foundation.WebTests.bootstrap
    login = foundation.WebTests.login
    mutate = foundation.WebTests.mutate
    portfolio = foundation.WebTests.portfolio
    hashes = adoption_tests.AdoptionTests.hashes

    def prepare(self):
        adoption_tests.AdoptionTests.prepare(self)
        self.plan.unlink()
        self.folder = next(self.legacy.glob("reports/*/manifest.json")).parent
        self.payload = json.loads((self.folder / "data.json").read_text())
        self.manifest = legacy_manifest(self.payload)
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))
        self.before = self.hashes()
        return self.new_plan()

    def new_plan(self, *, allow=True):
        result = prepare_adoption(self.settings, self.legacy, "Invented legacy ledger", self.plan,
                                  allow_legacy_reports=allow)
        self.pid, self.sha = result["portfolio_id"], result["plan_sha256"]
        return result

    def confirm(self):
        return confirm_adoption(self.settings, self.plan, self.sha)

    def test_legacy_saved_sections_are_read_without_rewriting_or_revaluing(self):
        self.prepare()
        text = "# Synthetic legacy report\n\n## Original overview\n\n| Unit | Value |\n| --- | --- |\n| CAD | " + self.payload["totals"]["total_cad"] + " |\n\n![Original allocation](charts/allocation.png)\n\n## Original method\n\nOriginal assumptions remain frozen.\n"
        (self.folder / "report.md").write_text(text)
        self.before = self.hashes()
        self.plan.unlink(); self.new_plan(); self.confirm()
        report = self.client.get(f"/api/v1/portfolios/{self.pid}/reports").json()["reports"][0]["id"]
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network")):
            response = self.client.get(f"/api/v1/portfolios/{self.pid}/reports/{report}/document")
        self.assertEqual(response.status_code, 200, response.text)
        document = response.json()
        self.assertEqual(document["report"]["verification_basis"], "migration_capture")
        self.assertEqual(document["sections"][0]["title"], "Original overview")
        self.assertEqual(document["sections"][0]["blocks"][0]["rows"][0][1], self.payload["totals"]["total_cad"])
        self.assertIsNotNone(document["sections"][0]["blocks"][1]["artifact_id"])
        self.assertEqual(self.hashes(), self.before)

    def test_explicit_acceptance_keeps_originals_ids_locales_exports_and_frozen_formats(self):
        result = self.prepare()
        self.assertEqual(result["legacy_reports"], 1)
        plan = json.loads(self.plan.read_text());evidence = plan["bundles"][0]["evidence"]
        self.assertEqual(evidence["basis"], "migration_capture")
        self.assertEqual(evidence["files"]["manifest.json"]["sha256"], hashlib.sha256((self.folder / "manifest.json").read_bytes()).hexdigest())
        with patch("urllib.request.urlopen", side_effect=AssertionError("No recalculation or network")):
            self.confirm()
            self.assertEqual(self.confirm()["status"], "already_adopted")
        self.assertEqual(self.hashes(), self.before)
        _, target = self.store.portfolio(self.pid)
        self.assertEqual(fingerprint(target), fingerprint(self.legacy))
        self.assertEqual(database_info(target / "data/db/portfolio.sqlite3"), database_info(self.legacy / "data/db/portfolio.sqlite3"))
        editions = self.client.get(f"/api/v1/portfolios/{self.pid}/reports").json()["reports"]
        self.assertEqual(editions[0]["verification_basis"], "migration_capture")
        self.assertEqual(editions[0]["published_at"],datetime.fromisoformat(self.manifest["report_generated_at"]).timestamp())
        self.report = editions[0]["id"];prefix = f"/api/v1/portfolios/{self.pid}/reports/{self.report}"
        for locale in ("en-CA", "zh-TW", "zh-CN"):
            response = self.client.get(prefix, params={"locale": locale})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["totals"], self.payload["totals"])
        document_response = self.client.get(prefix + "/document")
        # This fixture intentionally contains only an artifact placeholder, not a document.
        self.assertEqual(document_response.status_code, 409)
        self.assertEqual(document_response.json()["error"]["code"], "report_document_unavailable")
        exported = self.client.get(prefix + "/export", params={"dataset": "holdings", "format": "json"})
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["verification_basis"],"migration_capture")
        self.assertEqual(exported.json()["rows"][0]["market_cad"], self.payload["positions"][0]["market_cad"])
        response = self.client.get(prefix + "/bundle.zip")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            proof = json.loads(archive.read(ZIP_EVIDENCE))
            self.assertEqual(proof["evidence"], evidence)
            self.assertEqual(set(archive.namelist()), set(evidence["files"]) | {ZIP_EVIDENCE})
            for name in evidence["files"]:
                self.assertEqual(archive.read(name), (self.folder / name).read_bytes())
        for item in editions[0]["artifacts"]:
            response = self.client.get(f"/api/v1/portfolios/{self.pid}/artifacts/{item['id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, (self.folder / item["filename"]).read_bytes() if item["filename"] in {"data.json", "manifest.json", "report.md", "report.pdf", "portfolio.ods"} else (self.folder / "charts" / item["filename"]).read_bytes())
        self.assertEqual(self.hashes(), self.before)

    def test_legacy_requires_explicit_preview_flag_and_modern_partial_markers_never_fall_back(self):
        self.prepare();self.plan.unlink()
        with self.assertRaisesRegex(ValueError, "allow-legacy-reports"):
            self.new_plan(allow=False)
        self.assertFalse(self.plan.exists())
        for field, value in (("data_sha256", "0" * 64), ("bundle_files", {}), ("previous_latest", None),
                             ("financial_fingerprint", "0" * 64), ("localization", {})):
            with self.subTest(field=field):
                (self.folder / "manifest.json").write_text(json.dumps({**self.manifest, field: value}))
                with self.assertRaises(ValueError):
                    self.new_plan()
                self.assertFalse(self.plan.exists())

    def test_unknown_shape_cutoff_snapshot_paths_missing_files_and_links_fail_closed(self):
        self.prepare();self.plan.unlink()
        for replacement in ({**self.manifest, "future_schema": 99},
                            {**self.manifest, "snapshot_id": True},
                            {**self.manifest, "snapshot_as_of": "2024-02-03T12:00:00-05:00"},
                            {**self.manifest, "reporting": {"markdown": "../escape", "pdf": "report.pdf"}},
                            {**self.manifest, "reporting": {"markdown": "report.md", "pdf": "report.pdf", "charts": ["missing.png"]}}):
            (self.folder / "manifest.json").write_text(json.dumps(replacement))
            with self.assertRaises(ValueError):self.new_plan()
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))
        original = (self.folder / "report.pdf").read_bytes();(self.folder / "report.pdf").unlink()
        with self.assertRaises(ValueError):self.new_plan()
        (self.folder / "report.pdf").write_bytes(original)
        (self.folder / "unexpected.png").symlink_to(self.folder / "charts/allocation.png")
        with self.assertRaises((ValueError, WebError)):self.new_plan()

    def test_changed_legacy_file_or_reviewed_plan_never_reuses_capture(self):
        self.prepare()
        (self.folder / "report.pdf").write_bytes(b"changed synthetic PDF")
        with self.assertRaisesRegex(ValueError, "Source changed"):self.confirm()
        self.assertFalse((self.root / "portfolios" / self.pid).exists())
        self.assertEqual(len(self.store.portfolios()), 1)

    def test_mixed_modern_and_legacy_editions_register_independently(self):
        self.prepare();self.plan.unlink()
        modern = self.folder.parent / "modern";shutil.copytree(self.folder, modern)
        files = {p.relative_to(modern).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in modern.rglob("*") if p.is_file() and p.name != "manifest.json"}
        (modern / "manifest.json").write_text(json.dumps({"snapshot_id": self.payload["meta"]["snapshot_id"],
            "import": {}, "data_sha256": files["data.json"], "bundle_files": files}))
        result = self.new_plan();self.assertEqual(result["legacy_reports"], 1)
        self.confirm()
        rows = self.client.get(f"/api/v1/portfolios/{self.pid}/reports").json()["reports"]
        self.assertEqual({r["verification_basis"] for r in rows}, {"migration_capture", "publication_manifest"})
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(self.client.get(f"/api/v1/portfolios/{self.pid}/reports/{row['id']}/bundle.zip").status_code, 200)

    def test_backup_restore_retains_receipt_sessions_expire_and_all_legacy_downloads_work(self):
        self.prepare();self.confirm()
        archive = self.root.parent / "legacy-backup.zip";backup_instance(self.settings, archive)
        restored_settings = WebSettings(self.root.parent / "restored-legacy");restore_instance(restored_settings, archive)
        restored = Store(restored_settings);_, project = restored.portfolio(self.pid)
        self.assertEqual(fingerprint(project), fingerprint(self.legacy))
        with TestClient(create_app(restored_settings), base_url=foundation.ORIGIN) as client:
            self.login(client)
            editions = client.get(f"/api/v1/portfolios/{self.pid}/reports").json()["reports"]
            for row in editions:
                prefix = f"/api/v1/portfolios/{self.pid}/reports/{row['id']}"
                self.assertEqual(client.get(prefix).status_code, 200)
                self.assertEqual(client.get(prefix + "/bundle.zip").status_code, 200)
                self.assertEqual(client.get(prefix + "/export", params={"dataset":"history", "format":"json"}).status_code, 200)
        self.assertEqual(self.hashes(), self.before)

    def test_missing_tampered_or_cross_portfolio_evidence_blocks_views_downloads_and_backup(self):
        self.prepare();self.confirm()
        editions = self.client.get(f"/api/v1/portfolios/{self.pid}/reports").json()["reports"]
        row = editions[0];receipt = self.root / "admin/adoptions" / (self.pid + ".json")
        raw = receipt.read_bytes();original = json.loads(raw)
        for value in (None, {**original, "version": 999}, {**original, "legacy_reports": []},
                      {**original, "portfolio_id": "f" * 32},
                      {**original, "legacy_reports": {}},
                      {**original, "legacy_reports": {k: {**v, "basis":"historical_proof"} for k,v in original["legacy_reports"].items()}}):
            if value is None:receipt.unlink()
            else:receipt.write_text(json.dumps(value))
            prefix = f"/api/v1/portfolios/{self.pid}"
            self.assertEqual(self.client.get(prefix + f"/reports/{row['id']}").status_code, 409)
            self.assertEqual(self.client.get(prefix + f"/reports/{row['id']}/bundle.zip").status_code, 409)
            self.assertEqual(self.client.get(prefix + f"/artifacts/{row['artifacts'][0]['id']}").status_code, 409)
            with self.assertRaises((ValueError,WebError)):validate_instance(self.root)
            receipt.write_bytes(raw)

    def test_registry_tampering_scope_additions_and_manifest_changes_block_access(self):
        self.prepare();self.confirm()
        _,project = self.store.portfolio(self.pid)
        row = self.client.get(f"/api/v1/portfolios/{self.pid}/reports").json()["reports"][0]
        folder = project / self.folder.relative_to(self.legacy)
        extra = folder / "extra.json";extra.write_text("{}")
        prefix = f"/api/v1/portfolios/{self.pid}/reports/{row['id']}"
        self.assertEqual(self.client.get(prefix).status_code, 409);extra.unlink()
        with self.store.transaction() as conn:
            conn.execute("UPDATE artifacts SET sha256=? WHERE portfolio_id=? AND relative_path LIKE '%/report.pdf'", ("0"*64,self.pid))
        self.assertEqual(self.client.get(prefix).status_code, 409)
        with self.assertRaises((ValueError,WebError)):validate_instance(self.root)

    def test_interrupted_legacy_install_recovers_same_identity_without_rewriting_source(self):
        self.prepare()
        target = adoption_tests.AdoptionTests.interrupted_copy(self)
        result = self.confirm()
        self.assertEqual(result["portfolio_id"], self.pid)
        self.assertEqual(self.confirm()["status"], "already_adopted")
        self.assertEqual(self.hashes(), self.before)
        self.assertTrue(target.is_dir())

    def test_cli_documents_explicit_option_and_rejects_legacy_without_it(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/web.py"), "adopt-preview", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0);self.assertIn("--allow-legacy-reports", result.stdout)

    def test_duplicate_keys_non_objects_and_reserved_zip_evidence_fail_before_adoption(self):
        self.prepare();self.plan.unlink()
        for raw in ('[]', '{"snapshot_id":1,"snapshot_id":2}', '{"import":[]}'):
            (self.folder / "manifest.json").write_text(raw)
            with self.assertRaises(ValueError):self.new_plan()
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))
        (self.folder / ZIP_EVIDENCE).write_text("{}")
        with self.assertRaisesRegex(ValueError,"Unsupported"):self.new_plan()

    def test_same_size_payload_changes_and_missing_evidence_never_get_recaptured(self):
        self.prepare();self.confirm()
        _,project=self.store.portfolio(self.pid)
        row=self.client.get(f"/api/v1/portfolios/{self.pid}/reports").json()["reports"][0]
        folder=project/self.folder.relative_to(self.legacy)
        pdf=folder/"report.pdf";original=pdf.read_bytes();pdf.write_bytes(b"X"*len(original))
        artifact=next(a for a in row["artifacts"] if a["filename"]=="report.pdf")
        prefix=f"/api/v1/portfolios/{self.pid}"
        self.assertEqual(self.client.get(prefix+f"/artifacts/{artifact['id']}").status_code,409)
        self.assertEqual(self.client.get(prefix+f"/reports/{row['id']}/bundle.zip").status_code,409)
        with self.assertRaises((ValueError,WebError)):validate_instance(self.root)
        pdf.write_bytes(original)
        receipt=self.root/"admin/adoptions"/(self.pid+".json")
        data=json.loads(receipt.read_text());data['verification_captured_at']='2024-03-01T12:00:00-05:00'
        receipt.write_text(json.dumps(data))
        self.assertEqual(self.client.get(prefix+f"/reports/{row['id']}").status_code,409)
