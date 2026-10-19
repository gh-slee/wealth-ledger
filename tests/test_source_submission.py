"""Synthetic frozen mapping/confirmation/receipt recovery and migration boundaries."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_source_builtin import CONTEXT, ALIAS, ROOT, fixture, csv_change
from test_source_context_pipeline import CONTEXTS
from wealth_ledger import operations, source_ingestion as core
from wealth_ledger.source_builtin import WealthsimpleHoldings, BullBitcoinOrders, WS_FORMAT, BULL_FORMAT
from wealth_ledger.source_context_pipeline import ParsedSources, context_document
from wealth_ledger.source_submission import (SubmissionError, parse_bindings, prepare_submission,
    load_submission, confirm_submission, recover_submission)


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="synthetic-submission-");self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.project=self.root/"ledger";self.project.mkdir()
        self.directory=self.root/"frozen"
        self.paths=[self.root/"holdings.csv",self.root/"orders.csv"]
        self.raw=(fixture("wealthsimple-holdings.csv"),fixture("bull-orders.csv"))
        for path,raw in zip(self.paths,self.raw):path.write_bytes(raw)
        self.batches=(WealthsimpleHoldings().normalize(self.raw[0],export_version=WS_FORMAT,context=CONTEXTS[0]),
                      BullBitcoinOrders().normalize(self.raw[1],export_version=BULL_FORMAT,context=CONTEXTS[1]))
        self.parsed=ParsedSources({"environment_sha256":"a"*64},self.batches,self.raw)
        self.parse_patch=patch("wealth_ledger.source_submission.parse_sources",return_value=self.parsed)
        self.parse_patch.start();self.addCleanup(self.parse_patch.stop)
        self.env=patch("wealth_ledger.source_ingestion.environment_fingerprint",return_value="a"*64)
        self.env.start();self.addCleanup(self.env.stop)
        self.bindings=tuple(core.new_binding(a.key) for b in self.batches for a in b.accounts)

    def prepare(self,**kwargs):
        return prepare_submission(self.project,self.paths,contexts=CONTEXTS,bindings=kwargs.pop("bindings",self.bindings),
            directory=kwargs.pop("directory",self.directory),**kwargs)

    def confirm(self,result=None,**kwargs):
        result=result or self.prepare()
        return confirm_submission(self.project,self.directory,result["approval_sha256"],acknowledge_no_reports=kwargs.pop("acknowledge_no_reports",True),**kwargs)

    def hashes(self):
        return {p.relative_to(self.project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in self.project.rglob('*') if p.is_file() and p.relative_to(self.project).as_posix()!="work/update.guard"}

    def test_missing_mapping_returns_review_without_frozen_bundle_or_financial_writes(self):
        result=self.prepare(bindings=())
        self.assertEqual(result["status"],"mapping_required")
        choices=[r["suggested_choice"] for r in result["account_review"]]
        self.assertEqual({r["target_kind"] for r in choices},{"new"})
        self.assertFalse(self.directory.exists());self.assertEqual(self.hashes(),{})
        result=self.prepare(bindings=parse_bindings({"schema_version":1,"bindings":choices}))
        self.assertEqual(result["status"],"awaiting_confirmation")

    def test_preview_freezes_evidence_and_explicit_mappings_without_financial_writes(self):
        result=self.prepare()
        self.assertEqual(self.hashes(),{})
        manifest,plan=load_submission(self.project,self.directory,result["approval_sha256"])
        self.assertEqual(plan.inputs[0].raw,self.raw[0])
        self.assertEqual(manifest["operation_id"],result["operation_id"])
        self.assertEqual({r["ledger_account_id"] for r in result["account_review"]},{b.ledger_account_id for b in self.bindings})
        self.assertFalse(result["report_projection_ready"])
        if sys.platform!="win32":
            self.assertEqual(self.directory.stat().st_mode&0o777,0o700)
            self.assertTrue(all(p.stat().st_mode&0o777==0o400 for p in self.directory.iterdir()))

    def test_confirmation_requires_exact_digest_and_report_gate_acknowledgement(self):
        result=self.prepare()
        for approval,ack in [("0"*64,True),(result["approval_sha256"],False)]:
            with self.subTest(ack=ack),self.assertRaises(SubmissionError):
                confirm_submission(self.project,self.directory,approval,acknowledge_no_reports=ack)
        self.assertEqual(self.hashes(),{})

    def test_confirm_uses_frozen_bytes_not_original_path_or_parser(self):
        result=self.prepare()
        for path in self.paths:path.unlink()
        with patch("wealth_ledger.source_builtin.WealthsimpleHoldings.normalize",side_effect=AssertionError("Parser executed")), \
             patch("wealth_ledger.source_builtin.BullBitcoinOrders.normalize",side_effect=AssertionError("Parser executed")), \
             patch("wealth_ledger.source_submission.parse_sources",side_effect=AssertionError("Child executed")):
            value=self.confirm(result)
        self.assertEqual(value["operation_id"],result["operation_id"])
        self.assertFalse(value["report_published"])
        facts=core.read_facts(self.project)
        self.assertFalse(facts["contributions_calculated"])
        self.assertEqual(self.confirm(result),value)
        self.assertEqual(len(operations.list_operations(self.project)),1)

    def test_tampered_raw_canonical_config_manifest_and_extra_file_fail_closed(self):
        for name in ("0.csv","0.json","configuration.json","manifest.json","extra.json"):
            with self.subTest(name=name):
                directory=self.root/("frozen-"+name)
                result=self.prepare(directory=directory)
                path=directory/name
                if path.exists():path.chmod(0o600);path.write_bytes(path.read_bytes()+b" ")
                else:path.write_bytes(b"{}")
                with self.assertRaises(SubmissionError):load_submission(self.project,directory,result["approval_sha256"])
                self.assertEqual(self.hashes(),{})

    def test_equal_state_in_another_workspace_cannot_reuse_confirmation(self):
        result=self.prepare();other=self.root/"other";other.mkdir()
        with self.assertRaises(SubmissionError) as caught:
            confirm_submission(other,self.directory,result["approval_sha256"],acknowledge_no_reports=True)
        self.assertEqual(caught.exception.code,"workspace_mismatch")
        self.assertFalse(list(other.iterdir()))

    def test_stale_config_settings_environment_and_financial_state_reject(self):
        result=self.prepare()
        config=self.root/"parsers.json";config.write_text('{"schema_version":1,"enabled":[],"bindings":[]}\n')
        with self.assertRaises(SubmissionError):self.confirm(result,config_path=config)
        with patch("wealth_ledger.source_ingestion.environment_fingerprint",return_value="b"*64):
            with self.assertRaises(core.IngestionError):self.confirm(result)
        # Environment rejection can leave only a failed operation, not any facts.
        self.assertEqual(core.read_facts(self.project)["records"],[])

    def test_changed_portfolio_settings_reject_before_starting_operation(self):
        result=self.prepare();(self.project/"config").mkdir();(self.project/"config/local.toml").write_text('[report]\nlocale="en-CA"\n')
        with self.assertRaises(ValueError):self.confirm(result)
        self.assertEqual(operations.list_operations(self.project),[])

    def test_completed_receipt_recovers_after_plan_loss_and_without_environment_or_parser(self):
        result=self.prepare();value=self.confirm(result);shutil.rmtree(self.directory)
        with patch("wealth_ledger.source_ingestion.environment_fingerprint",side_effect=AssertionError("Environment executed")), \
             patch("wealth_ledger.source_submission.parse_sources",side_effect=AssertionError("Parser executed")):
            recovered=recover_submission(self.project,result["operation_id"],result["plan_sha256"])
        self.assertEqual(recovered,value)
        with self.assertRaises(SubmissionError):recover_submission(self.project,result["operation_id"],"0"*64)

    def test_postcommit_delivery_failure_has_one_effect_and_matching_receipt(self):
        result=self.prepare();original=operations.atomic_data
        def lost(*args,**kwargs):
            original(*args,**kwargs)
            raise OSError("Synthetic response delivery failure")
        with patch("wealth_ledger.operations.atomic_data",side_effect=lost),self.assertRaises(OSError):self.confirm(result)
        recovered=recover_submission(self.project,result["operation_id"],result["plan_sha256"])
        self.assertIsNotNone(recovered)
        before=self.hashes()
        self.assertEqual(self.confirm(result),recovered)
        self.assertEqual(self.hashes(),before)
        self.assertEqual(len(operations.list_operations(self.project)),1)

    def test_unfinished_operation_is_not_retried_or_discarded(self):
        result=self.prepare()
        operations.start(self.project,{"type":"synthetic-unknown"},data_only=True,operation_id=result["operation_id"])
        with self.assertRaises(SubmissionError) as caught:recover_submission(self.project,result["operation_id"],result["plan_sha256"])
        self.assertEqual(caught.exception.code,"operation_requires_review")
        with self.assertRaises(ValueError):self.confirm(result)
        self.assertEqual(core.read_facts(self.project)["records"],[])

    def test_binding_schema_unknown_choices_duplicate_keys_and_global_aliases_rejected(self):
        for value in ({"schema_version":True,"bindings":[]},{"schema_version":1,"bindings":[{"module":"untrusted:factory"}]},
                      {"schema_version":1,"bindings":[],"host_alias":"global-account"}):
            with self.assertRaises(SubmissionError):parse_bindings(value)
        key=self.batches[0].accounts[0].key
        choice={"provider":key.provider,"source_account_id":key.account_id,"target_kind":"new"}
        with self.assertRaises(SubmissionError):parse_bindings({"schema_version":1,"bindings":[choice,choice]})

    def test_legacy_account_match_requires_explicit_preserved_identity(self):
        from wealth_ledger.core import import_holdings
        import_holdings(self.project,self.paths[0],"baseline",json.loads(fixture("fx.json")))
        before=self.hashes()
        with self.assertRaises(SubmissionError) as caught:self.prepare()
        self.assertEqual(caught.exception.code,"legacy_mapping_required")
        review=self.prepare(bindings=())
        choices=[r["suggested_choice"] for r in review["account_review"]]
        self.assertIn("legacy_holdings",{r["target_kind"] for r in choices})
        approved=self.prepare(bindings=parse_bindings({"schema_version":1,"bindings":choices}))
        self.assertEqual(self.hashes(),before)
        self.confirm(approved)
        with sqlite3.connect(self.project/"data/db/portfolio.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],1)

    def test_native_imports_and_reports_remain_gated_after_canonical_commit(self):
        from wealth_ledger.core import import_holdings,make_payload
        from wealth_ledger.crypto import import_bull_orders
        result=self.prepare();self.confirm(result);before=self.hashes()
        for action in (lambda:import_holdings(self.project,self.paths[0],"monthly",json.loads(fixture("fx.json"))),
                       lambda:import_bull_orders(self.project,self.paths[1]),lambda:make_payload(self.project)):
            with self.assertRaises(core.IngestionError):action()
        self.assertEqual(self.hashes(),before)

    def test_bundle_symlink_and_protected_financial_directory_rejected(self):
        with self.assertRaises(SubmissionError):self.prepare(directory=self.project/"data/raw/frozen")
        target=self.root/"actual";target.mkdir();link=self.root/"linked";link.symlink_to(target,target_is_directory=True)
        with self.assertRaises(SubmissionError):self.prepare(directory=link)


    def test_native_completed_orders_reject_economic_changes_against_legacy_rows(self):
        from wealth_ledger.crypto import import_bull_orders
        assumptions={"btc":"0","lbtc":"0","cad":"0","basis":"Synthetic explicit assumption","confirmed_by":"synthetic-test"}
        import_bull_orders(self.project,self.paths[1],source_account=ALIAS,opening_assumption=assumptions)
        reviewed=self.prepare(bindings=())
        bindings=parse_bindings({"schema_version":1,"bindings":[r["suggested_choice"] for r in reviewed["account_review"]]})
        changed=csv_change(self.raw[1],[(2,"PAYIN_AMOUNT","401")])
        batch=BullBitcoinOrders().normalize(changed,export_version=BULL_FORMAT,context=CONTEXTS[1])
        parsed=ParsedSources({"environment_sha256":"a"*64},(self.batches[0],batch),(self.raw[0],changed))
        before=self.hashes()
        with patch("wealth_ledger.source_submission.parse_sources",return_value=parsed):
            with self.assertRaises(core.IngestionError) as caught:self.prepare(bindings=bindings)
        self.assertEqual(caught.exception.code,"native_completed_order_conflict")
        self.assertEqual(self.hashes(),before)

    def test_native_completed_orders_reject_changes_against_canonical_heads(self):
        first=self.prepare();self.confirm(first)
        changed=csv_change(self.raw[1],[(2,"PAYIN_AMOUNT","401")])
        original=next(r for r in self.batches[1].records if r.kind=="crypto_transactions" and r.lifecycle.payin.quantity==400)
        from wealth_ledger import source_v2 as v2
        context=replace(CONTEXTS[1],revisions=(v2.RevisionContext(original.key.account,original.kind,original.key.source_id,"",original.key.revision),))
        corrected=BullBitcoinOrders().normalize(changed,export_version=BULL_FORMAT,context=context)
        old_scope=next(c for c in self.batches[1].coverage if c.kind=="crypto_transactions")
        context=replace(context,scope_revisions=(v2.ScopeRevisionContext("coverage",old_scope.scope_id,old_scope.revision,old_scope.account,old_scope.kind),))
        corrected=BullBitcoinOrders().normalize(changed,export_version=BULL_FORMAT,context=context)
        parsed=ParsedSources({"environment_sha256":"a"*64},(self.batches[0],corrected),(self.raw[0],changed))
        before=self.hashes()
        with patch("wealth_ledger.source_submission.parse_sources",return_value=parsed):
            with self.assertRaises(core.IngestionError) as caught:self.prepare(directory=self.root/"changed-order")
        self.assertEqual(caught.exception.code,"native_completed_order_conflict")
        self.assertEqual(self.hashes(),before)

    def test_pending_completion_and_historical_export_replay_never_revert_current_effects(self):
        from wealth_ledger import source_v2 as v2
        pending_raw=csv_change(self.raw[1],[(2,"ORDER_STATUS","Pending"),(2,"PAYIN_STATUS","Pending"),(2,"PAYOUT_STATUS","Pending"),(2,"COMPLETED_AT (UTC)",""),(2,"SENT_AT (UTC)","")])
        pending=BullBitcoinOrders().normalize(pending_raw,export_version=BULL_FORMAT,context=CONTEXTS[1])
        parsed=ParsedSources({"environment_sha256":"a"*64},(self.batches[0],pending),(self.raw[0],pending_raw))
        with patch("wealth_ledger.source_submission.parse_sources",return_value=parsed):first=self.prepare()
        self.confirm(first)
        old=next(r for r in pending.records if r.status=="pending")
        scope=next(c for c in pending.coverage if c.kind=="crypto_transactions")
        context=replace(CONTEXTS[1],revisions=(v2.RevisionContext(old.key.account,old.kind,old.key.source_id,"",old.key.revision),),
            scope_revisions=(v2.ScopeRevisionContext("coverage",scope.scope_id,scope.revision,scope.account,scope.kind),))
        completed=BullBitcoinOrders().normalize(self.raw[1],export_version=BULL_FORMAT,context=context)
        completed_parsed=ParsedSources({"environment_sha256":"a"*64},(self.batches[0],completed),self.raw)
        second_directory=self.root/"completion"
        with patch("wealth_ledger.source_submission.parse_sources",return_value=completed_parsed):second=self.prepare(directory=second_directory)
        confirm_submission(self.project,second_directory,second["approval_sha256"],acknowledge_no_reports=True)
        effects=core.read_facts(self.project)["effects"]
        last_directory=self.root/"historical"
        with patch("wealth_ledger.source_submission.parse_sources",return_value=parsed):last=self.prepare(directory=last_directory)
        result=confirm_submission(self.project,last_directory,last["approval_sha256"],acknowledge_no_reports=True)
        self.assertEqual(result["new_records"],0)
        self.assertEqual(core.read_facts(self.project)["effects"],effects)

    def test_configuration_change_inside_staging_rolls_back_main_financial_effects(self):
        from wealth_ledger.source_pipeline import DEFAULT_CONFIG
        config=self.root/"host.json";config.write_bytes(DEFAULT_CONFIG)
        result=self.prepare(config_path=config);original=core._apply
        def changed(*args,**kwargs):
            value=original(*args,**kwargs);config.write_bytes(DEFAULT_CONFIG+b"\n");return value
        with patch("wealth_ledger.source_ingestion._apply",side_effect=changed):
            with self.assertRaises(core.IngestionError):self.confirm(result,config_path=config)
        self.assertEqual(core.read_facts(self.project)["records"],[])
        self.assertEqual(operations.list_operations(self.project)[0]["status"],"data_failed")

    def test_financial_state_change_rejects_previously_reviewed_submission(self):
        from wealth_ledger.core import import_holdings
        result=self.prepare()
        import_holdings(self.project,self.paths[0],"baseline",json.loads(fixture("fx.json")))
        before=self.hashes()
        with self.assertRaises(ValueError):self.confirm(result)
        self.assertEqual(self.hashes(),before)

    def test_unfinished_other_operation_blocks_preparation_before_parser_execution(self):
        operations.start(self.project,{"type":"synthetic-unfinished"},data_only=True)
        with patch("wealth_ledger.source_submission.parse_sources",side_effect=AssertionError("Parser used before pending guard")):
            with self.assertRaises(SubmissionError) as caught:self.prepare()
        self.assertEqual(caught.exception.code,"unfinished_operation")


class SubmissionCliTests(unittest.TestCase):
    def test_actual_child_cli_preview_confirm_and_receipt_only_recovery(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-submission-cli-") as directory:
            root=Path(directory).resolve();project=root/"ledger";project.mkdir()
            source=root/"orders.csv";source.write_bytes(fixture("bull-orders.csv"))
            contexts=root/"context.json";contexts.write_text(json.dumps(context_document((CONTEXTS[1],))))
            config=root/"config.json";config.write_text('{"schema_version":1,"enabled":[],"bindings":[]}')
            choices=root/"bindings.json"
            choices.write_text(json.dumps({"schema_version":1,"bindings":[{"provider":"bullbitcoin","source_account_id":name,"target_kind":"new"} for name in (ALIAS,ALIAS+":cad")]}))
            prefix=[sys.executable,"-B","-m","wealth_ledger.source_submission_cli"]
            def run(*args):
                result=subprocess.run(prefix+list(args),cwd=ROOT,capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return json.loads(result.stdout)
            preview=run("preview",str(source),"--workspace",str(project),"--config",str(config),"--context",str(contexts),"--bindings",str(choices),"--plan-directory",str(root/"frozen"))
            self.assertFalse((project/"data/db/portfolio.sqlite3").exists())
            committed=run("confirm","--workspace",str(project),"--config",str(config),"--plan-directory",str(root/"frozen"),"--approval-sha256",preview["approval_sha256"],"--acknowledge-no-reports")
            shutil.rmtree(root/"frozen");source.unlink()
            recovered=run("recover","--workspace",str(project),"--operation-id",preview["operation_id"],"--plan-sha256",preview["plan_sha256"])
            self.assertEqual(committed,recovered)
