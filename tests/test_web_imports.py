"""Synthetic Web uploads, confirmation, durable jobs and crash/restart acceptance."""
from contextlib import closing
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from test_core import FX, write_holdings
from test_crypto import FIELDS, ASSUMPTIONS, order
import test_web as foundation
from test_web import AVAILABLE, ORIGIN

AVAILABLE = AVAILABLE and importlib.util.find_spec("huey") is not None
if AVAILABLE:
    from wealth_ledger.operations import fingerprint, input_fingerprint
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.storage import Store, WebError
    from wealth_ledger.web.worker import execute_job, execute_isolated, reconcile, run_worker
    from wealth_ledger.web.queue import make_queue, NotificationSerializer
    from wealth_ledger.web.uploads import CSV_BYTES, REFERENCE_BYTES, MAX_ROWS

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(AVAILABLE, "Optional Web/worker dependencies are not installed")
class ImportTests(unittest.TestCase):
    setUp = foundation.WebTests.setUp
    bootstrap = foundation.WebTests.bootstrap
    login = foundation.WebTests.login
    mutate = foundation.WebTests.mutate
    portfolio = foundation.WebTests.portfolio

    def prepare(self):
        self.now[0] = datetime.fromisoformat("2026-10-12T12:00:00-04:00").timestamp()
        self.login(); self.pid = self.portfolio()
        self.prefix = "/api/v1/portfolios/" + self.pid
        _, self.project = self.store.portfolio(self.pid)
        self.jobs = Jobs(self.store)
        self.source = write_holdings(self.root.parent / "synthetic.csv")
        return self.upload(self.source.read_bytes())["id"]

    def upload(self, raw, kind="csv", filename="source.csv", *, expected=201, headers=None):
        response = self.client.post(self.prefix + "/uploads", params={"kind": kind, "filename": filename},
            content=raw, headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf,
                                  "Content-Type": "application/octet-stream", **(headers or {})})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def start_preview(self, uploads=None, *, key=None, **values):
        response = self.mutate("POST", self.prefix + "/previews",
            body={"upload_ids": uploads or [], **values}, headers={"Idempotency-Key": key or uuid.uuid4().hex})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def ready(self, *, references=True):
        upload = self.prepare()
        inputs = [upload]
        if references:
            inputs.append(self.upload(json.dumps(FX).encode(), "fx", "fx.json")["id"])
        preview = self.start_preview(inputs)
        before = fingerprint(self.project)
        execute_job(self.settings, preview["id"])
        row = self.jobs.get(self.pid, preview["id"])
        self.assertEqual(row["status"], "ready", row)
        self.assertEqual(fingerprint(self.project), before)
        return row

    def confirm(self, preview, key=None, expected=202):
        response = self.mutate("POST", self.prefix + "/jobs", body={"preview_id": preview["id"]},
                               headers={"Idempotency-Key": key or uuid.uuid4().hex})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def test_upload_detects_by_content_preserves_bytes_and_metadata_and_deduplicates(self):
        first = self.prepare()
        second = self.upload(self.source.read_bytes(), filename="other-name.csv")
        self.assertEqual(first, second["id"])
        self.assertEqual(second["original_name"], "source.csv")
        self.assertEqual(second["provider"], "wealthsimple")
        response = self.client.get(self.prefix + "/uploads/" + first)
        self.assertEqual(response.content, self.source.read_bytes())
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertFalse((self.project / "data/db/portfolio.sqlite3").exists())

    def test_upload_auth_origin_path_format_encoding_and_size_boundaries(self):
        self.prepare()
        for raw in (b"PK\x03\x04binary", b"a,b\n1,2\n", b"\xff\xfe", b"a\x00,b"):
            self.upload(raw, expected=422)
        self.upload(b"{}", "fx", "../outside.json", expected=422)
        self.upload(b"[1]", "price", "quote.json", expected=422)
        self.upload(b" " * (REFERENCE_BYTES + 1), "fx", expected=413)
        self.upload(b"x" * (CSV_BYTES + 1), expected=413)
        self.upload(self.source.read_bytes(), headers={"Origin": "http://attacker.test"}, expected=403)
        self.upload(self.source.read_bytes(), headers={"X-CSRF-Token": ""}, expected=403)
        self.client.cookies.clear()
        anonymous = self.bootstrap()
        self.upload(self.source.read_bytes(), headers={"X-CSRF-Token": anonymous}, expected=401)
        self.assertFalse(list((self.root / "uploads").rglob("*.part")))

    def test_chunked_upload_limit_and_excessive_rows_fail_without_partial_files(self):
        self.prepare()
        response = self.client.post(self.prefix + "/uploads", content=(b"x"*65536 for _ in range(161)),
            headers={"Origin": ORIGIN,"X-CSRF-Token": self.csrf,"Content-Type":"application/octet-stream"})
        self.assertEqual(response.status_code, 413, response.text)
        header = self.source.read_bytes().splitlines()[0]
        self.upload(header + b"\n" + b"x\n" * (MAX_ROWS + 1), expected=422)
        self.assertFalse(list((self.root / "uploads").rglob("*.part")))

    def test_uploads_and_jobs_are_portfolio_scoped_and_polls_do_not_touch_idle(self):
        first = self.prepare()
        preview = self.start_preview([first])
        other = self.portfolio("Other synthetic portfolio")
        old = self.prefix; self.prefix = "/api/v1/portfolios/" + other
        self.assertEqual(self.client.get(self.prefix + "/uploads/" + first).status_code, 404)
        self.assertEqual(self.client.get(self.prefix + "/jobs/" + preview["id"]).status_code, 404)
        response = self.mutate("POST", self.prefix + "/previews", body={"upload_ids":[first]},
                               headers={"Idempotency-Key":uuid.uuid4().hex})
        self.assertEqual(response.status_code, 404)
        self.prefix = old
        self.now[0] += 1799
        self.assertEqual(self.client.get(old + "/jobs").status_code, 200)
        self.now[0] += 2
        self.assertEqual(self.client.get(old + "/jobs").status_code, 401)

    def test_preview_is_offline_and_financially_readonly_even_without_references(self):
        with patch("wealth_ledger.fx._download", side_effect=AssertionError("Network forbidden")) as download:
            preview = self.ready(references=False)
            result = json.loads(preview["result_json"])
            self.assertEqual(result["status"], "pending_reference")
            self.assertFalse(result["network_used"])
            self.assertFalse(result["live_data_changed"])
            self.assertEqual(result["sources"]["wealthsimple"]["row_count"], 9)
            self.assertFalse((self.project / "data/db/portfolio.sqlite3").exists())
            self.assertNotIn(str(self.root), json.dumps(result))
            download.assert_not_called()

    def test_idempotency_and_confirmation_bind_current_financial_inputs(self):
        preview = self.ready()
        key = uuid.uuid4().hex
        first = self.confirm(preview, key)
        self.assertEqual(first["id"], self.confirm(preview, key)["id"])
        different = self.mutate("POST", self.prefix + "/jobs", body={"preview_id":uuid.uuid4().hex},
                                headers={"Idempotency-Key":key})
        self.assertEqual(different.status_code, 409)
        self.confirm(preview, expected=409)
        (self.project / "config/local.toml").write_text('[reporting]\nlocale="zh-TW"\n')
        # Exact retries retain the same result even after input changes.
        self.assertEqual(self.confirm(preview, key)["id"], first["id"])
        execute_job(self.settings, first["id"])
        self.assertEqual(self.jobs.get(self.pid, first["id"])["error_code"], "stale_preview")
        self.assertFalse((self.project / "data/db/portfolio.sqlite3").exists())

    def test_confirmation_rejects_stale_settings_and_expired_previews(self):
        preview = self.ready()
        text = (self.project / "config/local.toml").read_text()
        (self.project / "config/local.toml").write_text(text.replace("en-CA", "zh-TW"))
        self.confirm(preview, expected=409)
        (self.project / "config/local.toml").write_text(text)
        self.now[0] += 25*3600
        self.login()
        self.confirm(preview, expected=409)

    def test_upload_tampering_symlinks_batch_duplicates_and_float_amount_rejected(self):
        identifier = self.prepare()
        self.start_preview([identifier], key="same-preview-key")
        conflict = self.mutate("POST", self.prefix + "/previews", body={"upload_ids":[identifier],"kind":"interim"},
                               headers={"Idempotency-Key":"same-preview-key"})
        self.assertEqual(conflict.status_code, 409)
        for body in ({"upload_ids":[identifier,identifier]}, {"btc_balance":0.1,"btc_balance_as_of":"2026-10-10T12:00:00Z"},
                     {"btc_balance":"0.1"}, {"btc_balance":"0.1","btc_balance_as_of":"2026-10-10"},
                     {"paths":["/etc/passwd"]}):
            response=self.mutate("POST",self.prefix+"/previews",body=body,headers={"Idempotency-Key":uuid.uuid4().hex})
            self.assertEqual(response.status_code,422,response.text)
        path = next((self.root / "uploads" / self.pid).glob("*.csv"))
        path.chmod(0o600); path.write_bytes(b"changed")
        response=self.mutate("POST",self.prefix+"/previews",body={"upload_ids":[identifier]},headers={"Idempotency-Key":uuid.uuid4().hex})
        self.assertEqual(response.status_code,409)
        path.unlink(); path.symlink_to(self.source)
        self.assertEqual(self.client.get(self.prefix+"/uploads/"+identifier).status_code,404)

    def test_optional_btc_balance_alone_preserves_explicit_time_and_unknown_opening(self):
        self.prepare()
        preview=self.start_preview(btc_balance="0.12500000",btc_balance_as_of="2026-10-12T10:00:00-04:00",
                                   as_of="2026-10-12T10:00:00-04:00")
        execute_job(self.settings,preview["id"])
        row=self.jobs.get(self.pid,preview["id"])
        self.assertEqual(row["status"],"ready",row)
        result=json.loads(row["result_json"])
        self.assertEqual(result["sources"]["wallet"]["quantity_btc"],"0.12500000")
        self.assertFalse((self.project/"data/db/portfolio.sqlite3").exists())

    def test_cancel_only_queued_and_repeated_notifications_do_not_run_twice(self):
        preview=self.ready()
        formal=self.confirm(preview)
        response=self.mutate("POST",self.prefix+"/jobs/"+formal["id"]+"/cancel")
        self.assertEqual(response.status_code,200)
        execute_job(self.settings,formal["id"])
        self.assertEqual(self.jobs.get(self.pid,formal["id"])["status"],"cancelled")
        self.assertFalse((self.project/"data/db/portfolio.sqlite3").exists())
        response=self.mutate("POST",self.prefix+"/jobs/"+formal["id"]+"/resume")
        self.assertEqual(response.status_code,409)

    def test_queue_uses_json_ids_and_restart_recovers_lost_notifications(self):
        identifier=self.prepare()
        preview=self.start_preview([identifier])
        queue,dispatch=make_queue(self.store)
        task=dispatch.s(preview["id"])
        raw=queue.serialize_task(task)
        value=json.loads(raw)
        self.assertEqual(set(value),{"v","notification","job"})
        self.assertEqual(queue.deserialize_task(raw).args,(preview["id"],))
        for bad in (b"\\x80pickle",b'{"v":1,"job":"callable"}', b"x"*513):
            with self.assertRaises((ValueError,TypeError)):
                NotificationSerializer().deserialize(bad)
        run_worker(self.settings,once=True)
        self.assertEqual(self.jobs.get(self.pid,preview["id"])["status"],"ready")
        # A repeated stale notification cannot change a completed preview.
        dispatch(preview["id"])
        run_worker(self.settings,once=True)
        self.assertEqual(self.jobs.get(self.pid,preview["id"])["status"],"ready")

    def test_isolated_real_report_publishes_three_formats_and_registers_artifacts_once(self):
        preview=self.ready()
        formal=self.confirm(preview)
        self.assertEqual(execute_isolated(self.settings,formal["id"]),0)
        row=self.jobs.get(self.pid,formal["id"])
        self.assertEqual(row["status"],"published",row)
        artifacts=self.client.get(self.prefix+"/artifacts").json()["artifacts"]
        types={a["media_type"] for a in artifacts}
        self.assertTrue({"application/pdf","application/vnd.oasis.opendocument.spreadsheet","text/markdown; charset=utf-8"}.issubset(types))
        before=fingerprint(self.project)
        execute_job(self.settings,formal["id"])
        self.assertEqual(fingerprint(self.project),before)
        self.assertEqual(self.client.get(self.prefix+"/artifacts").json()["artifacts"],artifacts)
        for artifact in artifacts:
            response=self.client.get(self.prefix+"/artifacts/"+artifact["id"])
            self.assertEqual(response.status_code,200)
            self.assertEqual(hashlib.sha256(response.content).hexdigest(),artifact["sha256"])

    def crash(self, formal, patch_code):
        # A real child exits without Python cleanup, exercising persisted evidence.
        script='''import os
from unittest.mock import patch
from wealth_ledger.web.config import WebSettings
from wealth_ledger.web.worker import execute_job
from pathlib import Path
'''+patch_code+f'\nexecute_job(WebSettings(Path({str(self.root)!r})), {formal["id"]!r})\n'
        result=subprocess.run([sys.executable,"-c",script],env={**os.environ,"PYTHONPATH":str(ROOT/"src"),"PYTHONDONTWRITEBYTECODE":"1"},capture_output=True)
        self.assertEqual(result.returncode,77,result.stderr.decode())

    def test_crash_after_financial_commit_resumes_same_operation_without_reimport(self):
        preview=self.ready(); formal=self.confirm(preview)
        self.crash(formal,'patch("wealth_ledger.application.publish", side_effect=lambda *a: os._exit(77)).start()')
        before=fingerprint(self.project)
        with closing(sqlite3.connect(self.project/"data/db/portfolio.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT status FROM update_operations").fetchone()[0],"data_committed")
        reconcile(self.store)
        self.assertEqual(self.jobs.get(self.pid,formal["id"])["status"],"queued")
        self.assertEqual(execute_isolated(self.settings,formal["id"]),0)
        self.assertEqual(self.jobs.get(self.pid,formal["id"])["status"],"published")
        self.assertEqual(fingerprint(self.project),before)
        with closing(sqlite3.connect(self.project/"data/db/portfolio.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM update_operations").fetchone()[0],1)

    def test_crash_after_bundle_move_recovers_without_new_edition(self):
        preview=self.ready(); formal=self.confirm(preview)
        self.crash(formal,'patch("wealth_ledger.publishing._set_latest", side_effect=lambda *a: os._exit(77)).start()')
        bundles=list((self.project/"reports").glob("*/r*/manifest.json"))
        self.assertEqual(len(bundles),1)
        before=fingerprint(self.project)
        reconcile(self.store)
        self.assertEqual(execute_isolated(self.settings,formal["id"]),0)
        self.assertEqual(self.jobs.get(self.pid,formal["id"])["status"],"published")
        self.assertEqual(list((self.project/"reports").glob("*/r*/manifest.json")),bundles)
        self.assertEqual(fingerprint(self.project),before)
        self.assertTrue((self.project/"reports/latest.json").is_file())

    def test_crash_before_commit_becomes_needs_review_without_automatic_rerun(self):
        preview=self.ready(); formal=self.confirm(preview)
        self.crash(formal,'patch("wealth_ledger.operations.atomic_data", side_effect=lambda *a, **k: os._exit(77)).start()')
        reconcile(self.store)
        self.assertEqual(self.jobs.get(self.pid,formal["id"])["status"],"needs_review")
        self.assertEqual(fingerprint(self.project),hashlib.sha256(b"[]").hexdigest())
        response=self.mutate("POST",self.prefix+"/jobs/"+formal["id"]+"/resume")
        self.assertEqual(response.status_code,409)

    def test_crash_inside_commit_transaction_rolls_back_marker_and_financial_rows(self):
        preview=self.ready(); formal=self.confirm(preview)
        self.crash(formal,'''from wealth_ledger import operations
original = operations.atomic_data
def interrupted(project, action, *, finalize=None):
    def barrier(conn, accepted, digest):
        finalize(conn, accepted, digest)
        os._exit(77)
    return original(project, action, finalize=barrier)
patch("wealth_ledger.operations.atomic_data", side_effect=interrupted).start()''')
        reconcile(self.store)
        self.assertEqual(self.jobs.get(self.pid,formal["id"])["status"],"needs_review")
        with closing(sqlite3.connect(self.project/"data/db/portfolio.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT status FROM update_operations").fetchone()[0],"started")

    def test_crash_after_core_publication_reconciles_registry_without_another_report(self):
        preview=self.ready(); formal=self.confirm(preview)
        self.crash(formal,'patch("wealth_ledger.web.worker.publish_registry", side_effect=lambda *a: os._exit(77)).start()')
        before=list((self.project/"reports").glob("*/r*/manifest.json"))
        self.assertEqual(len(before),1)
        reconcile(self.store)
        row=self.jobs.get(self.pid,formal["id"])
        self.assertEqual(row["status"],"published",row)
        self.assertEqual(list((self.project/"reports").glob("*/r*/manifest.json")),before)
        self.assertTrue(json.loads(row["result_json"])["artifact_ids"])

    def test_report_failure_explicit_resume_uses_saved_inputs_and_frozen_time(self):
        preview=self.ready(); formal=self.confirm(preview)
        with patch("wealth_ledger.application.publish",side_effect=ValueError("Synthetic report failure")):
            execute_job(self.settings,formal["id"])
        row=self.jobs.get(self.pid,formal["id"])
        self.assertEqual(row["status"],"report_failed")
        before=fingerprint(self.project)
        response=self.mutate("POST",self.prefix+"/jobs/"+formal["id"]+"/resume")
        self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(execute_isolated(self.settings,formal["id"]),0)
        row=self.jobs.get(self.pid,formal["id"])
        self.assertEqual(row["status"],"published",row)
        self.assertEqual(row["execution_at"],formal["execution_at"])
        self.assertEqual(fingerprint(self.project),before)

    def test_both_sources_and_bull_alone_need_explicit_opening_and_keep_source_dates(self):
        import csv,io
        ws=self.prepare()
        stream=io.StringIO(newline="")
        writer=csv.DictWriter(stream,FIELDS);writer.writeheader()
        writer.writerows([order("synthetic-funding",amount="100"),
                         order("synthetic-buy","Buy Bitcoin","100","BTC",".001")])
        bull=self.upload(stream.getvalue().encode(),filename="unhelpful.csv")["id"]
        blocked=self.start_preview([bull])
        execute_job(self.settings,blocked["id"])
        self.assertEqual(self.jobs.get(self.pid,blocked["id"])["status"],"blocked")
        opening=self.upload(json.dumps(ASSUMPTIONS).encode(),"opening","opening.json")["id"]
        for inputs in ([bull,opening],[ws,bull,opening]):
            preview=self.start_preview(inputs)
            execute_job(self.settings,preview["id"])
            row=self.jobs.get(self.pid,preview["id"])
            self.assertEqual(row["status"],"ready",row)
            result=json.loads(row["result_json"])
            self.assertEqual(result["sources"]["bullbitcoin"]["new_orders"],2)
            self.assertEqual(Decimal(result["btc"]["quantity_btc"]),Decimal("0.00100000"))
            self.assertEqual(result["source_usage"]["wealthsimple"],"provided" if ws in inputs else "not_available")
        self.assertFalse((self.project/"data/db/portfolio.sqlite3").exists())

    def test_engine_change_and_corrupt_bundle_fail_closed(self):
        preview=self.ready(); formal=self.confirm(preview)
        with patch("wealth_ledger.web.jobs.engine_fingerprint",return_value="changed"):
            execute_job(self.settings,formal["id"])
        self.assertEqual(self.jobs.get(self.pid,formal["id"])["error_code"],"stale_engine")
        self.assertFalse((self.project/"data/db/portfolio.sqlite3").exists())
        formal=self.confirm(preview)
        self.crash(formal,'patch("wealth_ledger.publishing._set_latest", side_effect=lambda *a: os._exit(77)).start()')
        report=next((self.project/"reports").glob("*/r*/report.md"))
        report.write_text("Corrupt synthetic report")
        reconcile(self.store)
        self.assertEqual(execute_isolated(self.settings,formal["id"]),0)
        self.assertEqual(self.jobs.get(self.pid,formal["id"])["status"],"report_failed")
        self.assertFalse((self.project/"reports/latest.json").exists())

    def test_worker_singleton_and_persistent_schema_upgrade_backup(self):
        from wealth_ledger.locking import file_lock,LockBusy
        self.prepare()
        with file_lock(self.root/"admin/worker.guard"):
            with self.assertRaises(LockBusy):
                run_worker(self.settings,once=True)
        self.assertTrue(list((self.root/"admin/backups").glob("app-v1-*.sqlite3")))
        with closing(self.store.connect()) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0],2)

    def test_live_advisory_guard_cannot_be_broken_and_crash_releases_kernel_ownership(self):
        from wealth_ledger.operations import project_lock
        from wealth_ledger.locking import LockBusy
        self.prepare()
        with project_lock(self.project):
            with self.assertRaises(LockBusy):
                with project_lock(self.project):
                    self.fail("Concurrent lock acquired")
        script='from wealth_ledger.operations import project_lock; import os; from pathlib import Path\nwith project_lock(Path('+repr(str(self.project))+')): os._exit(77)'
        result=subprocess.run([sys.executable,"-c",script],env={**os.environ,"PYTHONPATH":str(ROOT/"src")})
        self.assertEqual(result.returncode,77)
        with project_lock(self.project):
            self.assertTrue((self.project/"work/update.lock").exists())
