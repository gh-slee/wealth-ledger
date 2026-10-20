"""Synthetic source report jobs, exact approvals, scoped reads, exports and recovery."""
from contextlib import closing
from datetime import date
from decimal import Decimal
import io
import json
from pathlib import Path
import shutil
import time
from unittest.mock import patch
import unittest
import zipfile

import test_web as foundation
import test_web_source_submission as submission
from test_source_legacy_projection import FX, AT, START, quote
from test_source_projection import hashes
from test_source_publication import publisher_receipt
from wealth_ledger import operations
from wealth_ledger.source_context_pipeline import context_document
from wealth_ledger.source_submission import parse_bindings

if submission.AVAILABLE:
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.worker import execute_job, execute_isolated, reconcile
    from wealth_ledger.web.source_reports import plan_directory
    from wealth_ledger.web.backups import backup_instance, restore_instance
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.storage import Store


@unittest.skipUnless(submission.AVAILABLE, "Optional Web dependencies are not installed")
class SourceReportWebTests(unittest.TestCase):
    setUp = foundation.WebTests.setUp
    bootstrap = foundation.WebTests.bootstrap
    login = foundation.WebTests.login
    mutate = foundation.WebTests.mutate
    portfolio = foundation.WebTests.portfolio

    def prepare(self, *, actual=False):
        submission.WebSubmissionTests.prepare(self, actual=actual)
        if not actual:
            item = patch("wealth_ledger.web.source_reports.environment_fingerprint", return_value="a" * 64)
            item.start(); self.addCleanup(item.stop)
        self.body["valuation"] = {"as_of": AT, "period_start": START, "generated_at": AT,
                                  "fx": FX, "report_locale": "en-CA"}

    def preview(self, *, body=None, key="synthetic-source-report-preview", expected=202, execute=True):
        response = self.mutate("POST", self.prefix + "/source-report-previews", body=self.body if body is None else body,
                               headers={"Idempotency-Key": key})
        self.assertEqual(response.status_code, expected, response.text)
        if expected != 202: return response.json()
        if execute: execute_job(self.settings, response.json()["id"])
        return self.jobs.view(self.jobs.get(self.pid, response.json()["id"]))

    def confirm(self, preview, *, expected=202, key="synthetic-source-report-confirm", execute=True, changes=None):
        response = self.mutate("POST", self.prefix + "/source-reports", body={"preview_id": preview["id"],
            "approval_sha256": preview["result"].get("approval_sha256", "0" * 64), **(changes or {})},
            headers={"Idempotency-Key": key})
        self.assertEqual(response.status_code, expected, response.text)
        if expected != 202: return response.json()
        if execute:
            with patch("wealth_ledger.lookthrough.attach_analysis"), patch("wealth_ledger.publishing.publish", side_effect=publisher_receipt):
                execute_job(self.settings, response.json()["id"])
        return self.jobs.view(self.jobs.get(self.pid, response.json()["id"]))

    def view(self, job, locale="en-CA"):
        response = self.client.get(self.prefix + "/reports/" + job["id"], params={"locale": locale})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_preview_is_readonly_exact_approval_and_one_report_per_preview(self):
        self.prepare(); before = hashes(self.project); preview = self.preview()
        self.assertEqual(preview["status"], "ready", preview["error_code"])
        self.assertEqual(hashes(self.project), before)
        self.assertEqual(self.preview()["id"], preview["id"])
        self.confirm(preview, changes={"approval_sha256": "0" * 64}, expected=409)
        bypass = self.mutate("POST", self.prefix + "/jobs", body={"preview_id": preview["id"]},
                             headers={"Idempotency-Key": "bypass-source-report-digest"})
        self.assertEqual(bypass.status_code, 409)
        self.assertEqual(bypass.json()["error"]["code"], "approval_required")
        job = self.confirm(preview)
        self.assertEqual(job["status"], "published", job["error_code"])
        self.assertEqual(job["core_operation_id"], "OP-" + preview["id"])
        self.assertEqual(self.confirm(preview, key="another-key-same-source-preview")["id"], job["id"])
        self.assertEqual(len(operations.list_operations(self.project)), 1)
        self.assertEqual(len(self.client.get(self.prefix + "/reports").json()["reports"]), 1)

    def test_missing_mapping_requires_new_review_and_cannot_confirm(self):
        self.prepare(); preview = self.preview(body={**self.body, "bindings": []})
        self.assertEqual(preview["result"]["status"], "mapping_required")
        self.assertFalse(plan_directory(self.store, self.pid, preview["id"]).exists())
        self.confirm(preview, expected=409)
        self.assertFalse((self.project / "data/db/portfolio.sqlite3").exists())
        job = self.confirm(self.preview(key="reviewed-source-bindings"))
        self.assertEqual(job["status"], "published")

    def test_auth_csrf_closed_schema_scope_and_bounded_decimal_inputs(self):
        self.prepare(); preview = self.preview()
        response = self.client.post(self.prefix + "/source-reports", json={"preview_id": preview["id"], "approval_sha256": preview["result"]["approval_sha256"]})
        self.assertEqual(response.status_code, 403)
        self.preview(body={**self.body, "module": "untrusted:factory"}, expected=422)
        self.preview(body={**self.body, "valuation": {**self.body["valuation"], "fx": {"usd_cad": 1.5}}}, key="numeric-source-fx-rejected", expected=422)
        self.preview(body={**self.body, "upload_ids": [self.uploads[0], self.uploads[0]]}, key="duplicate-source-upload", expected=422)
        other = self.portfolio("Another synthetic ledger")
        response = self.mutate("POST", "/api/v1/portfolios/" + other + "/source-reports", body={"preview_id": preview["id"], "approval_sha256": preview["result"]["approval_sha256"]}, headers={"Idempotency-Key": "cross-source-report-confirm"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(operations.list_operations(self.project), [])

    def test_changed_settings_configuration_environment_and_expiry_reject_before_commit(self):
        for reason in ("settings", "configuration", "environment", "expiry"):
            with self.subTest(reason=reason):
                self.prepare(); preview = self.preview()
                if reason == "settings":
                    (self.project / "config/local.toml").write_text("[reporting]\nlocale='zh-TW'\n")
                elif reason == "configuration":
                    config = self.root / "admin/source-parsers.json"; config.write_text('{"schema_version":1,"enabled":[],"bindings":[]}\n')
                    self.addCleanup(lambda: config.unlink(missing_ok=True))
                elif reason == "environment":
                    item = patch("wealth_ledger.web.source_reports.environment_fingerprint", return_value="b" * 64)
                    item.start(); self.addCleanup(item.stop)
                else:
                    self.now[0] += 25 * 3600; self.login()
                self.confirm(preview, expected=409)
                self.assertEqual(operations.list_operations(self.project), [])
                # Each subcase uses a fresh portfolio; reset only synthetic config.
                (self.root / "admin/source-parsers.json").unlink(missing_ok=True)

    def test_queued_commit_rechecks_state_and_preserves_financial_mutual_exclusion(self):
        self.prepare(); preview = self.preview(); job = self.confirm(preview, execute=False)
        other = self.preview(key="another-source-preview")
        self.confirm(other, key="concurrent-source-confirm", expected=409)
        (self.project / "config/local.toml").write_text("[reporting]\nlocale='zh-TW'\n")
        execute_job(self.settings, job["id"])
        saved = self.jobs.get(self.pid, job["id"])
        self.assertEqual(saved["status"], "blocked")
        self.assertEqual(operations.list_operations(self.project), [])

    def test_saved_facts_report_needs_no_new_csv_and_no_fabricated_source_or_zero_total(self):
        self.prepare()
        body = {"valuation": self.body["valuation"]}
        preview = self.preview(body=body)
        self.assertEqual(preview["status"], "ready")
        job = self.confirm(preview); view = self.view(job)
        self.assertEqual(view["source_dates"], [])
        self.assertIsNone(view["totals"]["total_cad"])
        self.assertIsNone(view["btc"])
        self.assertIsNone(view["source_basis"]["complete_portfolio_returns"])
        self.assertEqual(view["data_status"], "observed_subtotal")

    def test_actual_isolated_parser_and_three_format_publication_read_and_exports(self):
        self.prepare(actual=True); preview = self.preview(execute=False)
        self.assertEqual(execute_isolated(self.settings, preview["id"]), 0)
        preview = self.jobs.view(self.jobs.get(self.pid, preview["id"]))
        self.assertEqual(preview["status"], "ready", preview["error_code"])
        job = self.confirm(preview, execute=False)
        from examples.demo import synthetic_fund
        from wealth_ledger.lookthrough import attach_analysis
        original = attach_analysis
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network")), patch("wealth_ledger.lookthrough.attach_analysis", side_effect=lambda root, payload: original(root, payload, fetcher=synthetic_fund)):
            execute_job(self.settings, job["id"])
        job = self.jobs.view(self.jobs.get(self.pid, job["id"]))
        self.assertEqual(job["status"], "published", job["error_code"])
        before = hashes(self.project)
        for locale in ("en-CA", "zh-TW", "zh-CN"):
            with patch("wealth_ledger.source_publication.make_source_payload", side_effect=AssertionError("No revaluation")):
                view = self.view(job, locale)
            self.assertTrue(view["findings"])
            self.assertFalse(any(text.startswith("source_report.") for text in view["findings"]))
            self.assertIsNone(view["btc"]["quantity_btc"])
            self.assertTrue(view["holdings"][0]["source_id"])
            self.assertEqual(view["source_basis"]["source_valuation_id"], 1)
            self.assertFalse(view["is_complete"])
            self.assertIsNone(view["btc"]["monthly"][0]["contribution_cad"])
        for dataset in ("holdings", "accounts", "history", "cash_flows", "btc_monthly"):
            response = self.client.get(self.prefix + "/reports/" + job["id"] + "/export", params={"dataset": dataset, "format": "json"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["source_basis"]["scope"], "valued_observed_rows_not_complete_wealth")
        response = self.client.get(self.prefix + "/reports/" + job["id"] + "/bundle.zip")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in ("portfolio.ods", "report.md", "report.pdf"): self.assertIn(name, archive.namelist())
        self.assertEqual(hashes(self.project), before)

    def test_report_failure_resumes_same_payload_without_uploads_plan_config_or_parser(self):
        self.prepare(); preview = self.preview(); job = self.confirm(preview, execute=False)
        with patch("wealth_ledger.lookthrough.attach_analysis"), patch("wealth_ledger.publishing.publish", side_effect=RuntimeError):
            execute_job(self.settings, job["id"])
        self.assertEqual(self.jobs.get(self.pid, job["id"])["status"], "report_failed")
        shutil.rmtree(plan_directory(self.store, self.pid, preview["id"]))
        shutil.rmtree(self.root / "uploads" / self.pid)
        response = self.mutate("POST", self.prefix + "/jobs/" + job["id"] + "/resume")
        self.assertEqual(response.status_code, 202, response.text)
        with patch("wealth_ledger.source_submission.parse_sources", side_effect=AssertionError("No parser")), patch("wealth_ledger.source_publication.make_source_payload", side_effect=AssertionError("No revaluation")), patch("wealth_ledger.lookthrough.attach_analysis", side_effect=AssertionError("No analysis refresh")), patch("wealth_ledger.publishing.publish", side_effect=publisher_receipt):
            execute_job(self.settings, job["id"])
        self.assertEqual(self.jobs.get(self.pid, job["id"])["status"], "published")
        self.assertEqual(len(operations.list_operations(self.project)), 1)

    def test_core_publication_survives_registry_interruption_and_reconciles_without_second_report(self):
        self.prepare(); preview = self.preview(); job = self.confirm(preview, execute=False)
        with patch("wealth_ledger.lookthrough.attach_analysis"), patch("wealth_ledger.publishing.publish", side_effect=publisher_receipt), patch("wealth_ledger.web.worker.publish_registry", side_effect=RuntimeError):
            execute_job(self.settings, job["id"])
        self.assertEqual(operations.get(self.project, job["core_operation_id"])["status"], "published")
        self.assertEqual(self.jobs.get(self.pid, job["id"])["status"], "needs_review")
        self.jobs.state(job["id"], "running")
        with patch("wealth_ledger.publishing.publish", side_effect=AssertionError("No second report")):
            reconcile(self.store)
        self.assertEqual(self.jobs.get(self.pid, job["id"])["status"], "published")
        self.assertEqual(len(list((self.project / "reports").glob("*/r*/manifest.json"))), 1)

    def test_full_backup_empty_restore_retains_registry_reads_exports_and_source_receipts(self):
        self.prepare(); preview = self.preview(); job = self.confirm(preview)
        before = self.view(job)
        archive = self.root.parent / "synthetic-source-report-web.zip"
        backup_instance(self.settings, archive)
        target = WebSettings(self.root.parent / "restored-source-report-web")
        restore_instance(target, archive)
        store = Store(target)
        from wealth_ledger.web.reports import Publications
        from wealth_ledger.web.exports import export_data
        with patch("wealth_ledger.source_publication.make_source_payload", side_effect=AssertionError("No revalue")):
            self.assertEqual(Publications(store).view(self.pid, job["id"], "en-CA"), before)
            exported = export_data(store, self.pid, job["id"], "history")
        self.assertEqual(exported["source_basis"]["source_valuation_id"], 1)
        self.assertEqual(exported["rows"][0]["revision"], 1)

    def test_corrupt_frozen_preview_or_publication_blocks_commit_or_download(self):
        self.prepare(); preview = self.preview()
        path = plan_directory(self.store, self.pid, preview["id"]) / "configuration.json"
        path.chmod(0o600); path.write_bytes(b"{}")
        self.confirm(preview, expected=409)
        job = self.confirm(self.preview(key="intact-source-preview"))
        saved = operations.get(self.project, job["core_operation_id"])
        folder = Path(saved["output"]["output"])
        (folder / "data.json").write_bytes(b"{}")
        response = self.client.get(self.prefix + "/reports/" + job["id"])
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(str(self.root), response.text)

    def test_wallet_only_report_preserves_observation_date_without_inventing_broker_sources(self):
        self.prepare()
        from wealth_ledger.wallet import add_balance
        add_balance(self.project, "0.01234567", AT, now=AT)
        body = {"valuation": {**self.body["valuation"], "btc_price": quote()}}
        job = self.confirm(self.preview(body=body)); view = self.view(job)
        self.assertEqual([r["provider"] for r in view["source_dates"]], ["wallet"])
        from wealth_ledger.prices import parse_time
        self.assertEqual(parse_time(view["source_dates"][0]["as_of"]), parse_time(AT))
        self.assertEqual(Decimal(view["btc"]["quantity_btc"]), Decimal("0.01234567"))
        self.assertEqual(Decimal(view["btc"]["valuation"]["unit_price_cad"]), Decimal(quote()["close"]) * Decimal(FX["usd_cad"]))
        self.assertIsNone(view["btc"]["actual_full_cost_cad"])
        self.assertFalse(any(r["source_provider"] == "wealthsimple" for r in view["holdings"]))

    def test_interrupted_preview_and_unproven_financial_start_never_reexecute(self):
        self.prepare(); preview = self.preview(execute=False)
        self.jobs.state(preview["id"], "running"); reconcile(self.store)
        self.assertEqual(self.jobs.get(self.pid, preview["id"])["status"], "interrupted")
        ready = self.preview(key="fresh-after-interruption"); job = self.confirm(ready, execute=False)
        operations.start(self.project, {"type": "synthetic-unproven-start"}, operation_id=job["core_operation_id"])
        with patch("wealth_ledger.source_publication.confirm_source_report", side_effect=AssertionError("No duplicate commit")):
            execute_job(self.settings, job["id"])
        self.assertEqual(self.jobs.get(self.pid, job["id"])["status"], "needs_review")

    def test_restore_invalidates_unexecuted_previews_and_confirmations(self):
        self.prepare(); preview = self.preview(); job = self.confirm(preview, execute=False)
        archive = self.root.parent / "synthetic-pending-source-web.zip"
        backup_instance(self.settings, archive)
        target = WebSettings(self.root.parent / "restored-pending-source-web")
        restore_instance(target, archive); jobs = Jobs(Store(target))
        self.assertEqual(jobs.get(self.pid, preview["id"])["status"], "interrupted")
        self.assertEqual(jobs.get(self.pid, job["id"])["status"], "needs_review")
        _, project = Store(target).portfolio(self.pid)
        self.assertEqual(operations.list_operations(project), [])

    def test_third_provider_read_projection_preserves_identity_and_unknowns(self):
        self.prepare(); job = self.confirm(self.preview())
        from wealth_ledger.source_publication import frozen_report
        from wealth_ledger.web.source_report_views import source_view
        from wealth_ledger.i18n import presentation_context, display_payload
        payload = frozen_report(self.project, operations.get(self.project, job["core_operation_id"]))
        for row in payload["source_projection"]["accounts"]: row["provider"] = "third-synthetic-provider"
        for row in payload["positions"] + payload["cash_rows"]: row["source_provider"] = "third-synthetic-provider"
        with presentation_context("en-CA"):
            view = source_view(display_payload(payload), {}, "en-CA")
        self.assertEqual({row["provider"] for row in view["source_dates"]}, {"third-synthetic-provider"})
        self.assertEqual({row["source_provider"] for row in view["holdings"]}, {"third-synthetic-provider"})
        self.assertIsNone(view["btc"]["quantity_btc"])

    def test_restore_retains_proven_committed_report_retry_without_old_preview(self):
        self.prepare(); preview = self.preview(); job = self.confirm(preview, execute=False)
        with patch("wealth_ledger.lookthrough.attach_analysis"), patch("wealth_ledger.publishing.publish", side_effect=RuntimeError):
            execute_job(self.settings, job["id"])
        self.assertEqual(self.jobs.get(self.pid, job["id"])["status"], "report_failed")
        self.jobs.resume(self.pid, job["id"])
        shutil.rmtree(plan_directory(self.store, self.pid, preview["id"]))
        archive = self.root.parent / "synthetic-committed-source-web.zip"
        backup_instance(self.settings, archive)
        target = WebSettings(self.root.parent / "restored-committed-source-web")
        restore_instance(target, archive); jobs = Jobs(Store(target))
        self.assertEqual(jobs.get(self.pid, job["id"])["status"], "queued")
        with patch("wealth_ledger.source_publication.make_source_payload", side_effect=AssertionError("No revalue")), patch("wealth_ledger.lookthrough.attach_analysis", side_effect=AssertionError("No analysis")), patch("wealth_ledger.publishing.publish", side_effect=publisher_receipt):
            execute_job(target, job["id"])
        self.assertEqual(jobs.get(self.pid, job["id"])["status"], "published")
