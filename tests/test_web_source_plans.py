"""Owner-scoped nonbooking parser plans, shared policy and backup expiration."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import unittest

import test_web as foundation
from test_source_pipeline import RAW, synthetic_plan

AVAILABLE = foundation.AVAILABLE and importlib.util.find_spec("huey") is not None
if AVAILABLE:
    from wealth_ledger.operations import fingerprint
    from wealth_ledger.source_pipeline import SourcePlanError, host_config
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.worker import execute_job, reconcile
    from wealth_ledger.web.backups import backup_instance, restore_instance
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.storage import Store


@unittest.skipUnless(AVAILABLE, "Optional Web dependencies are not installed")
class WebSourcePlanTests(unittest.TestCase):
    setUp = foundation.WebTests.setUp
    bootstrap = foundation.WebTests.bootstrap
    login = foundation.WebTests.login
    mutate = foundation.WebTests.mutate
    portfolio = foundation.WebTests.portfolio

    def prepare(self):
        self.login()
        self.pid = self.portfolio()
        self.prefix = "/api/v1/portfolios/" + self.pid
        _, self.project = self.store.portfolio(self.pid)
        self.before = fingerprint(self.project)
        self.jobs = Jobs(self.store)
        upload = self.client.post(self.prefix+"/uploads", params={"kind":"source_csv","filename":"invented.csv"},
            content=RAW, headers={"Origin":foundation.ORIGIN,"X-CSRF-Token":self.csrf,"Content-Type":"text/csv"})
        self.assertEqual(upload.status_code,201,upload.text)
        self.upload=upload.json()["id"]
        self.assertIsNone(upload.json()["provider"])

    def enqueue(self, *, body=None, key="synthetic-source-plan-key", expected=202):
        with patch("wealth_ledger.web.source_plans.environment_fingerprint",return_value="a"*64):
            response=self.mutate("POST",self.prefix+"/source-plans",
                body=body or {"upload_ids":[self.upload]},headers={"Idempotency-Key":key})
        self.assertEqual(response.status_code,expected,response.text)
        return response.json()

    def fake_runner(self, paths, *, config_path, selections, previous, expected_environment):
        self.assertEqual(expected_environment,"a"*64)
        result=synthetic_plan(raw=Path(paths[0]).read_bytes(),config=host_config(config_path),selections=selections)
        if previous is not None and previous["fingerprint"] != result["fingerprint"]:
            raise SourcePlanError("stale_plan")
        return result

    def execute(self, job):
        with patch("wealth_ledger.web.source_plans.plan_sources",side_effect=self.fake_runner):
            execute_job(self.settings,job["id"])
        return self.jobs.get(self.pid,job["id"])

    def test_owner_api_plan_matches_shared_policy_and_cannot_be_confirmed(self):
        self.prepare()
        job=self.enqueue()
        self.assertEqual(job["kind"],"source_plan")
        self.assertIsNone(job["core_operation_id"])
        row=self.execute(job)
        self.assertEqual(row["status"],"ready")
        result=json.loads(row["result_json"])
        self.assertEqual(result,synthetic_plan())
        self.assertFalse(result["ingestible"])
        confirm=self.mutate("POST",self.prefix+"/jobs",body={"preview_id":job["id"]},headers={"Idempotency-Key":"never-book-source-plan"})
        self.assertEqual(confirm.status_code,404)
        self.assertEqual(fingerprint(self.project),self.before)
        self.assertFalse((self.project/"data/db/portfolio.sqlite3").exists())

    def test_api_cannot_enable_code_and_normal_import_cannot_use_parser_upload(self):
        self.prepare()
        self.enqueue(body={"upload_ids":[self.upload],"module":"arbitrary:make"},expected=422)
        self.enqueue(body={"upload_ids":[self.upload],"config_path":"/untrusted/config"},expected=422)
        self.enqueue(body={"upload_ids":[self.upload],"selections":{"2":"demo"}},expected=422)
        self.enqueue(body={"upload_ids":[self.upload],"selections":{"1":"x"*201}},expected=422)
        regular=self.mutate("POST",self.prefix+"/previews",body={"upload_ids":[self.upload]},headers={"Idempotency-Key":"normal-import-rejected"})
        self.assertEqual(regular.status_code,422)

    def test_auth_csrf_portfolio_scope_upload_limits_and_idempotency(self):
        self.prepare()
        unauth=self.client.post(self.prefix+"/source-plans",json={"upload_ids":[self.upload]})
        self.assertEqual(unauth.status_code,403)
        other=self.portfolio("Other synthetic portfolio")
        scope=self.mutate("POST","/api/v1/portfolios/"+other+"/source-plans",body={"upload_ids":[self.upload]},headers={"Idempotency-Key":"cross-portfolio-reject"})
        self.assertEqual(scope.status_code,404)
        self.enqueue(body={"upload_ids":[self.upload,self.upload]},expected=422)
        first=self.enqueue()
        second=self.enqueue()
        self.assertEqual(first["id"],second["id"])
        self.enqueue(body={"upload_ids":[self.upload],"selections":{"1":"changed"}},expected=409)

    def test_host_config_change_after_queue_blocks_before_parser_executes(self):
        self.prepare()
        job=self.enqueue()
        (self.root/"admin/source-parsers.json").write_text('{"schema_version":1,"enabled":[],"bindings":[]}\n')
        with patch("wealth_ledger.web.source_plans.plan_sources",side_effect=AssertionError("Stale config executed")):
            execute_job(self.settings,job["id"])
        row=self.jobs.get(self.pid,job["id"])
        self.assertEqual((row["status"],row["error_code"]),("blocked","stale_plan"))

    def test_api_worker_environment_mismatch_is_blocked_in_real_child(self):
        self.prepare()
        job=self.enqueue()
        execute_job(self.settings,job["id"])
        row=self.jobs.get(self.pid,job["id"])
        self.assertEqual((row["status"],row["error_code"]),("blocked","stale_environment"))
        self.assertEqual(fingerprint(self.project),self.before)

    def test_explicit_revalidation_rejects_changed_normalized_plan(self):
        self.prepare()
        original=self.enqueue()
        self.execute(original)
        verify=self.enqueue(body={"upload_ids":[self.upload],"previous_plan_id":original["id"]},key="source-revalidate-same")
        self.assertEqual(self.execute(verify)["status"],"ready")
        changed=self.enqueue(body={"upload_ids":[self.upload],"previous_plan_id":original["id"],"selections":{"1":"synthetic.holdings"}},key="source-revalidate-different")
        row=self.execute(changed)
        self.assertEqual((row["status"],row["error_code"]),("blocked","stale_plan"))
        self.now[0]+=25*3600
        self.login()
        self.enqueue(body={"upload_ids":[self.upload],"previous_plan_id":original["id"]},key="source-revalidate-expired",expected=409)

    def test_interrupted_plan_never_gets_financial_resume(self):
        self.prepare()
        job=self.enqueue()
        self.assertTrue(self.jobs.claim(job["id"]))
        reconcile(self.store)
        row=self.jobs.get(self.pid,job["id"])
        self.assertEqual(row["status"],"interrupted")
        resume=self.mutate("POST",self.prefix+"/jobs/"+job["id"]+"/resume")
        self.assertEqual(resume.status_code,409)

    def test_real_external_plugin_has_identical_cli_and_web_plan(self):
        from functools import partial
        from test_source_pipeline import IsolatedPlanTests
        from wealth_ledger.source_pipeline import plan_sources
        IsolatedPlanTests.setUpClass()
        try:
            fixture=IsolatedPlanTests("test_real_child_loads_normalizes_revalidates_and_never_books")
            fixture.setUp()
            expected=fixture.plan()
            self.prepare()
            (self.root/"admin/source-parsers.json").write_bytes(fixture.config.read_bytes())
            with patch("wealth_ledger.web.source_plans.environment_fingerprint",return_value=expected["environment_sha256"]):
                response=self.mutate("POST",self.prefix+"/source-plans",body={"upload_ids":[self.upload]},headers={"Idempotency-Key":"real-external-parser-plan"})
            self.assertEqual(response.status_code,202,response.text)
            job=response.json()
            # Use the fixture's pinned isolated Python environment as the worker
            # executable; the actual shared runner/child/entry point are unmocked.
            with patch("wealth_ledger.web.source_plans.plan_sources",partial(plan_sources,python=fixture.python)):
                execute_job(self.settings,job["id"])
            row=self.jobs.get(self.pid,job["id"])
            self.assertEqual(row["status"],"ready",row["error_code"])
            self.assertEqual(json.loads(row["result_json"]),expected)
            self.assertEqual(fingerprint(self.project),self.before)
        finally:
            IsolatedPlanTests.tearDownClass()

    def test_backup_preserves_host_config_and_restore_expires_plan_without_loading(self):
        self.prepare()
        config=self.root/"admin/source-parsers.json"
        config.write_text('{"schema_version":1,"enabled":[],"bindings":[]}')
        job=self.enqueue()
        self.execute(job)
        archive=self.root.parent/"source-plan-backup.zip"
        backup_instance(self.settings,archive)
        target=WebSettings(self.root.parent/"restored-source-plan")
        with patch("wealth_ledger.source_registry.build_registry",side_effect=AssertionError("Restore loaded plugins")):
            restore_instance(target,archive)
        restored=Store(target)
        self.assertEqual((target.data_root/"admin/source-parsers.json").read_bytes(),config.read_bytes())
        row=Jobs(restored).get(self.pid,job["id"])
        self.assertEqual((row["status"],row["error_code"]),("interrupted","restore_preview_expired"))


if __name__ == "__main__": unittest.main()
