"""Synthetic source confirmation, owner isolation, committed recovery and restore."""
from dataclasses import replace
import importlib.util
import json
import time
from pathlib import Path
from unittest.mock import patch
import unittest

import test_web as foundation
from test_source_builtin import ALIAS, fixture
from test_source_context_pipeline import CONTEXTS
from wealth_ledger.source_builtin import WealthsimpleHoldings,BullBitcoinOrders,WS_FORMAT,BULL_FORMAT
from wealth_ledger.source_context_pipeline import ParsedSources,context_document

AVAILABLE=foundation.AVAILABLE and importlib.util.find_spec("huey") is not None
if AVAILABLE:
    from wealth_ledger import operations,source_ingestion as core
    from wealth_ledger.source_submission import recover_submission
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.worker import execute_job,reconcile
    from wealth_ledger.web.backups import backup_instance,restore_instance
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.storage import Store


@unittest.skipUnless(AVAILABLE,"Optional Web dependencies are not installed")
class WebSubmissionTests(unittest.TestCase):
    setUp=foundation.WebTests.setUp
    bootstrap=foundation.WebTests.bootstrap
    login=foundation.WebTests.login
    mutate=foundation.WebTests.mutate
    portfolio=foundation.WebTests.portfolio

    def prepare(self,*,actual=False):
        self.now[0]=time.time()
        self.login();self.pid=self.portfolio();self.prefix="/api/v1/portfolios/"+self.pid
        _,self.project=self.store.portfolio(self.pid);self.jobs=Jobs(self.store)
        self.raw=(fixture("wealthsimple-holdings.csv"),fixture("bull-orders.csv"))
        self.batches=(WealthsimpleHoldings().normalize(self.raw[0],export_version=WS_FORMAT,context=CONTEXTS[0]),
            BullBitcoinOrders().normalize(self.raw[1],export_version=BULL_FORMAT,context=CONTEXTS[1]))
        self.uploads=[]
        for index,raw in enumerate(self.raw):
            response=self.client.post(self.prefix+"/uploads",params={"kind":"source_csv","filename":str(index)+".csv"},content=raw,
                headers={"Origin":foundation.ORIGIN,"X-CSRF-Token":self.csrf,"Content-Type":"text/csv"})
            self.assertEqual(response.status_code,201,response.text);self.uploads.append(response.json()["id"])
        self.body={"upload_ids":self.uploads,"contexts":context_document(CONTEXTS)["inputs"],"bindings":[
            {"provider":a.key.provider,"source_account_id":a.key.account_id,"target_kind":"new"} for batch in self.batches for a in batch.accounts]}
        if not actual:
            patches=[patch("wealth_ledger.source_submission.parse_sources",return_value=ParsedSources({"environment_sha256":"a"*64},self.batches,self.raw)),
                patch("wealth_ledger.source_ingestion.environment_fingerprint",return_value="a"*64),
                patch("wealth_ledger.web.source_submissions.environment_fingerprint",return_value="a"*64)]
            for item in patches:item.start();self.addCleanup(item.stop)

    def preview(self,*,body=None,key="synthetic-source-preview",expected=202,execute=True):
        response=self.mutate("POST",self.prefix+"/source-ingestion-previews",body=body or self.body,headers={"Idempotency-Key":key})
        self.assertEqual(response.status_code,expected,response.text)
        if response.status_code!=202:return response.json()
        value=response.json()
        if execute:execute_job(self.settings,value["id"])
        return self.jobs.view(self.jobs.get(self.pid,value["id"]))

    def confirm(self,preview,*,key="synthetic-source-confirm",expected=202,changes=None,execute=True):
        body={"preview_id":preview["id"],"approval_sha256":preview["result"].get("approval_sha256","0"*64),"acknowledge_no_reports":True,**(changes or {})}
        response=self.mutate("POST",self.prefix+"/source-ingestions",body=body,headers={"Idempotency-Key":key})
        self.assertEqual(response.status_code,expected,response.text)
        if response.status_code!=202:return response.json()
        value=response.json()
        if execute:execute_job(self.settings,value["id"])
        return self.jobs.view(self.jobs.get(self.pid,value["id"]))

    def test_actual_worker_child_preview_and_confirmation_preserve_data_only_boundary(self):
        self.prepare(actual=True);preview=self.preview()
        self.assertEqual(preview["status"],"ready",preview["error_code"])
        self.assertIsNone(preview["core_operation_id"])
        self.assertEqual(preview["result"]["status"],"awaiting_confirmation")
        self.assertFalse((self.project/"data/db/portfolio.sqlite3").exists())
        committed=self.confirm(preview)
        self.assertEqual(committed["status"],"recorded",committed["error_code"])
        self.assertFalse(committed["result"]["report_published"])
        self.assertFalse(committed["result"]["report_projection_ready"])
        self.assertEqual(committed["core_operation_id"],"OP-"+preview["id"])
        core.verify_store(self.project)
        self.assertEqual(len(operations.list_operations(self.project)),1)
        repeated=self.confirm(preview)
        self.assertEqual(repeated["id"],committed["id"])
        self.assertEqual(len(operations.list_operations(self.project)),1)

    def test_mapping_required_is_nonconfirmable_and_does_not_create_financial_state(self):
        self.prepare();preview=self.preview(body={**self.body,"bindings":[]})
        self.assertEqual(preview["result"]["status"],"mapping_required")
        self.assertTrue(preview["result"]["account_review"])
        self.confirm(preview,expected=409)
        self.assertFalse((self.project/"data/db/portfolio.sqlite3").exists())

    def test_auth_csrf_closed_body_cross_portfolio_exact_approval_and_acknowledgement(self):
        self.prepare();preview=self.preview()
        missing=self.client.post(self.prefix+"/source-ingestions",json={"preview_id":preview["id"],"approval_sha256":"0"*64,"acknowledge_no_reports":True})
        self.assertEqual(missing.status_code,403)
        self.confirm(preview,changes={"approval_sha256":"0"*64},expected=409)
        for value in (False,1,"true"):
            self.confirm(preview,changes={"acknowledge_no_reports":value},expected=422)
        self.preview(body={**self.body,"module":"untrusted:factory"},key="invalid-source-body",expected=422)
        other=self.portfolio("Other synthetic portfolio")
        response=self.mutate("POST","/api/v1/portfolios/"+other+"/source-ingestions",body={"preview_id":preview["id"],"approval_sha256":preview["result"]["approval_sha256"],"acknowledge_no_reports":True},headers={"Idempotency-Key":"cross-portfolio-source"})
        self.assertEqual(response.status_code,404)
        self.assertEqual(operations.list_operations(self.project),[])

    def test_changed_configuration_expired_preview_and_normal_confirmation_are_rejected(self):
        self.prepare();preview=self.preview()
        normal=self.mutate("POST",self.prefix+"/jobs",body={"preview_id":preview["id"]},headers={"Idempotency-Key":"wrong-financial-route"})
        self.assertEqual(normal.status_code,404)
        config=self.root/"admin/source-parsers.json";config.write_text('{"schema_version":1,"enabled":[],"bindings":[]}\n')
        self.confirm(preview,expected=409)
        config.unlink();self.now[0]+=25*3600;self.login()
        self.confirm(preview,key="expired-source-preview",expected=409)
        self.assertEqual(operations.list_operations(self.project),[])

    def test_completed_commit_survives_job_delivery_failure_and_explicit_receipt_recovery(self):
        self.prepare();preview=self.preview();job=self.confirm(preview,execute=False)
        real=Jobs.state;lost=[False]
        def delivery(jobs,identifier,status,**kwargs):
            if identifier==job["id"] and status=="recorded" and not lost[0]:
                lost[0]=True;raise OSError("Synthetic result delivery failure")
            return real(jobs,identifier,status,**kwargs)
        with patch.object(Jobs,"state",delivery):execute_job(self.settings,job["id"])
        self.assertEqual(self.jobs.get(self.pid,job["id"])["status"],"recorded")
        self.jobs.state(job["id"],"needs_review")
        from wealth_ledger.web.source_submissions import plan_directory
        import shutil
        shutil.rmtree(plan_directory(self.store,self.pid,preview["id"]))
        with patch("wealth_ledger.source_ingestion.environment_fingerprint",side_effect=AssertionError("Environment used during recovery")):
            response=self.mutate("POST",self.prefix+"/source-ingestions/"+job["id"]+"/recover")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["status"],"recorded")
        self.assertEqual(len(operations.list_operations(self.project)),1)
        discard=self.mutate("POST",self.prefix+"/source-ingestions/"+job["id"]+"/discard")
        self.assertEqual(discard.status_code,409)

    def test_unproven_started_operation_never_reexecutes_or_discards(self):
        self.prepare();preview=self.preview();job=self.confirm(preview,execute=False)
        operations.start(self.project,{"type":"synthetic-unknown-start"},data_only=True,operation_id=job["core_operation_id"])
        execute_job(self.settings,job["id"])
        self.assertEqual(self.jobs.get(self.pid,job["id"])["status"],"needs_review")
        for action in ("recover","discard"):
            response=self.mutate("POST",self.prefix+"/source-ingestions/"+job["id"]+"/"+action)
            self.assertEqual(response.status_code,409)
        self.assertEqual(core.read_facts(self.project)["records"],[])

    def test_restore_expires_pending_confirmation_and_allows_only_unstarted_discard(self):
        self.prepare();preview=self.preview();job=self.confirm(preview,execute=False)
        archive=self.root.parent/"synthetic-source-pending.zip";backup_instance(self.settings,archive)
        target=WebSettings(self.root.parent/"source-pending-restored");restore_instance(target,archive)
        restored=Store(target);jobs=Jobs(restored)
        self.assertEqual(jobs.get(self.pid,preview["id"])["status"],"interrupted")
        self.assertEqual(jobs.get(self.pid,job["id"])["status"],"needs_review")
        _,project=restored.portfolio(self.pid)
        self.assertIsNone(recover_submission(project,job["core_operation_id"],preview["result"]["plan_sha256"]))
        # The original still-unstarted job can be explicitly discarded without finance.
        self.jobs.state(job["id"],"needs_review")
        response=self.mutate("POST",self.prefix+"/source-ingestions/"+job["id"]+"/discard")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["status"],"cancelled")
        self.assertEqual(operations.list_operations(self.project),[])

    def test_restore_preserves_completed_source_receipt_without_parser_environment(self):
        self.prepare();preview=self.preview();job=self.confirm(preview)
        archive=self.root.parent/"synthetic-source-complete.zip";backup_instance(self.settings,archive)
        target=WebSettings(self.root.parent/"source-complete-restored");restore_instance(target,archive)
        restored=Store(target);row=Jobs(restored).get(self.pid,job["id"])
        self.assertEqual(row["status"],"recorded")
        from wealth_ledger.web.source_submissions import completed_result
        with patch("wealth_ledger.source_submission.parse_sources",side_effect=AssertionError("Restore parsed source")):
            self.assertEqual(completed_result(restored,row),job["result"])
        _,project=restored.portfolio(self.pid);core.verify_store(project)

    def test_mutual_exclusion_with_other_financial_jobs_and_preview_reuse(self):
        self.prepare();preview=self.preview()
        with self.store.transaction() as conn:
            other=self.jobs._insert(conn,self.pid,"record",{"synthetic":True},"other-financial-job-key","a"*64)
        self.confirm(preview,expected=409)
        self.jobs.cancel(self.pid,other["id"])
        job=self.confirm(preview,execute=False)
        again=self.confirm(preview,key="another-key-same-preview",execute=False)
        self.assertEqual(job["id"],again["id"])
        with self.store.transaction() as conn:
            declaration=self.jobs._insert(conn,self.pid,"record_preview",{"synthetic":True},"normal-declaration-preview","b"*64)
        self.jobs.state(declaration["id"],"ready",fingerprint=operations.input_fingerprint(self.project))
        with self.assertRaises(Exception) as caught:self.jobs.confirm(self.pid,declaration["id"],"normal-confirm-while-source-pending",preview_kind="record_preview")
        self.assertEqual(caught.exception.code,"portfolio_busy")

    def test_failed_uncommitted_operation_can_be_discarded_without_removing_its_audit_row(self):
        self.prepare();preview=self.preview();job=self.confirm(preview,execute=False)
        with patch("wealth_ledger.source_ingestion._apply",side_effect=ValueError("Synthetic rejected stage")):
            execute_job(self.settings,job["id"])
        self.assertEqual(self.jobs.get(self.pid,job["id"])["status"],"failed")
        response=self.mutate("POST",self.prefix+"/source-ingestions/"+job["id"]+"/discard")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["status"],"cancelled")
        self.assertEqual(operations.list_operations(self.project)[0]["status"],"data_failed")
        self.assertEqual(core.read_facts(self.project)["records"],[])

    def test_cli_frozen_preview_honors_web_instance_maintenance_before_parser_or_write(self):
        self.prepare()
        from wealth_ledger.web.maintenance import maintenance
        from wealth_ledger.locking import LockBusy
        from wealth_ledger.source_submission import prepare_submission
        with maintenance(self.root,timeout=0):
            with patch("wealth_ledger.source_submission.parse_sources",side_effect=AssertionError("Parser ran during maintenance")):
                with self.assertRaises(LockBusy):
                    prepare_submission(self.project,(),contexts=CONTEXTS,bindings=(),directory=self.root/"admin/blocked-source-preview")
        self.assertFalse((self.root/"admin/blocked-source-preview").exists())
        self.assertEqual(operations.list_operations(self.project),[])
