"""Owner-only context-aware plans share the real child and cannot book data."""
import importlib.util
import json
from unittest.mock import patch
import unittest

import test_web as foundation
from test_source_builtin import CONTEXT, ALIAS, fixture
from test_source_context_pipeline import CONTEXTS
from wealth_ledger.source_context_pipeline import context_document

AVAILABLE = foundation.AVAILABLE and importlib.util.find_spec("huey") is not None
if AVAILABLE:
    from wealth_ledger.operations import fingerprint
    from wealth_ledger.source_context_pipeline import plan_context_sources
    from wealth_ledger.source_environment import environment_fingerprint
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.worker import execute_job, reconcile


@unittest.skipUnless(AVAILABLE, "Optional Web dependencies are not installed")
class WebContextPlanTests(unittest.TestCase):
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
        self.uploads = []
        for name in ("wealthsimple-holdings.csv", "bull-orders.csv"):
            response = self.client.post(self.prefix + "/uploads", params={"kind":"source_csv", "filename":name},
                content=fixture(name), headers={"Origin":foundation.ORIGIN,"X-CSRF-Token":self.csrf,"Content-Type":"text/csv"})
            self.assertEqual(response.status_code, 201, response.text)
            self.uploads.append(response.json()["id"])
        self.body = {"upload_ids":self.uploads, "contexts":context_document(CONTEXTS)["inputs"]}

    def enqueue(self, body=None, key="synthetic-context-plan", expected=202):
        response = self.mutate("POST", self.prefix + "/source-context-plans", body=body or self.body,
            headers={"Idempotency-Key":key})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def test_actual_context_api_and_worker_equal_shared_cli_plan_and_cannot_confirm(self):
        from wealth_ledger.web.uploads import get_upload, verified_upload
        self.prepare()
        paths = [verified_upload(self.store, get_upload(self.store, self.pid, identifier)) for identifier in self.uploads]
        expected = plan_context_sources(paths, contexts=CONTEXTS)
        job = self.enqueue()
        self.assertIsNone(job["core_operation_id"])
        execute_job(self.settings, job["id"])
        row = self.jobs.get(self.pid, job["id"])
        self.assertEqual(row["status"], "ready", row["error_code"])
        self.assertEqual(json.loads(row["result_json"]), expected)
        self.assertFalse(expected["ingestible"])
        confirm = self.mutate("POST", self.prefix + "/jobs", body={"preview_id":job["id"]}, headers={"Idempotency-Key":"never-confirm-v2"})
        self.assertEqual(confirm.status_code, 404)
        self.assertEqual(fingerprint(self.project), self.before)
        self.assertFalse((self.project / "data/db/portfolio.sqlite3").exists())
        self.assertEqual(self.enqueue()["id"], job["id"])

    def test_context_validation_auth_csrf_and_portfolio_scope(self):
        self.prepare()
        missing = self.client.post(self.prefix + "/source-context-plans", json=self.body)
        self.assertEqual(missing.status_code, 403)
        for change in ({"contexts":self.body["contexts"][:1]}, {"module":"untrusted:factory"},
                       {"contexts":[{**self.body["contexts"][0], "evidence_at":"naive-date"}, self.body["contexts"][1]]}):
            with self.subTest(change=change):
                self.enqueue({**self.body, **change}, expected=422)
        other = self.portfolio("Other synthetic context portfolio")
        response = self.mutate("POST", "/api/v1/portfolios/" + other + "/source-context-plans", body=self.body,
            headers={"Idempotency-Key":"wrong-portfolio-context"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(fingerprint(self.project), self.before)

    def test_context_and_environment_drift_block_revalidation_and_execution(self):
        self.prepare()
        job = self.enqueue()
        execute_job(self.settings, job["id"])
        changed = json.loads(json.dumps(self.body))
        changed["previous_plan_id"] = job["id"]
        changed["contexts"][1]["account_alias"] = "different-alias"
        revised = self.enqueue(changed, key="changed-context-plan")
        execute_job(self.settings, revised["id"])
        row = self.jobs.get(self.pid, revised["id"])
        self.assertEqual((row["status"], row["error_code"]), ("blocked", "stale_plan"))
        with patch("wealth_ledger.web.source_plans.environment_fingerprint", return_value="0" * 64):
            mismatch = self.enqueue(key="context-environment-mismatch")
        execute_job(self.settings, mismatch["id"])
        row = self.jobs.get(self.pid, mismatch["id"])
        self.assertEqual((row["status"], row["error_code"]), ("blocked", "stale_environment"))
        self.assertEqual(fingerprint(self.project), self.before)

    def test_interrupted_context_job_has_no_financial_resume(self):
        self.prepare()
        job = self.enqueue()
        self.assertTrue(self.jobs.claim(job["id"]))
        reconcile(self.store)
        row = self.jobs.get(self.pid, job["id"])
        self.assertEqual(row["status"], "interrupted")
        response = self.mutate("POST", self.prefix + "/jobs/" + job["id"] + "/resume")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(fingerprint(self.project), self.before)
