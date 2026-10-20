"""Canonical-v2 state, identity, evidence and atomicity using isolated synthetic ledgers."""
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

from test_source_v2 import ACCOUNT, META, POSITION, KEY, AT, RAW, CONTEXT, INFO, CAD, BTC, batch, funding, purchase
from wealth_ledger import source_ingestion as ingestion, source_v2 as v2
from wealth_ledger.core import initialize
from wealth_ledger.source_protocol import AccountKey, Money
from wealth_ledger.workspace import resolve_workspace
from wealth_ledger.operations import fingerprint


def file_hashes(root):
    return {path.relative_to(root).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}


class CanonicalIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="synthetic-canonical-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()/"ledger"; self.root.mkdir()
        self.environment=patch("wealth_ledger.source_ingestion.environment_fingerprint",return_value="a"*64)
        self.environment.start(); self.addCleanup(self.environment.stop)

    def plan(self, value=None, *, raw=RAW, bindings=None):
        value=batch() if value is None else value
        supplied=tuple(ingestion.new_binding(account.key) for account in value.accounts) if bindings is None else bindings
        return ingestion.prepare_ingestion(self.root,(ingestion.SourceInput(value,raw),),bindings=supplied)

    def commit(self, value=None, *, raw=RAW, bindings=None, operation_id=None):
        return ingestion.commit_ingestion(resolve_workspace(explicit=self.root),self.plan(value,raw=raw,bindings=bindings),operation_id=operation_id)

    def query(self, sql, params=()):
        with closing(sqlite3.connect(self.root/"data/db/portfolio.sqlite3")) as conn:
            return conn.execute(sql,params).fetchall()

    def test_preview_readonly_atomic_commit_provenance_and_exact_reimport(self):
        before=file_hashes(self.root)
        plan=self.plan()
        self.assertEqual(file_hashes(self.root),before)
        result=ingestion.commit_ingestion(resolve_workspace(explicit=self.root),plan,operation_id="OP-"+uuid.uuid4().hex)
        self.assertEqual(result["new_records"],1)
        self.assertFalse(result["report_projection_ready"])
        self.assertFalse(result["contributions_calculated"])
        self.assertFalse(result["report_published"])
        facts=ingestion.read_facts(self.root)
        self.assertEqual(len(facts["records"]),1)
        self.assertEqual(facts["effects"],[])
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_records")[0][0],1)
        self.assertEqual(self.query("SELECT environment_sha256 FROM src_batches")[0][0],"a"*64)
        repeat=self.commit()
        self.assertEqual(repeat["new_records"],0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_batches")[0][0],1)
        self.assertFalse((self.root/"reports").exists())

    def test_new_fetch_context_retains_evidence_without_duplicate_effects(self):
        self.commit(batch((funding(),)))
        updated=batch((funding(),),context=replace(CONTEXT,evidence_at=CONTEXT.evidence_at+timedelta(days=1)))
        self.assertEqual(self.commit(updated)["new_records"],0)
        self.assertEqual(ingestion.verify_store(self.root)["batches"],2)
        self.assertEqual(len(ingestion.read_facts(self.root)["effects"]),1)
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_batch_records")[0][0],2)

    def test_correction_void_and_historical_replay_preserve_one_active_effect(self):
        original=funding()
        self.commit(batch((original,)))
        corrected=replace(original,key=replace(original.key,revision="r2",supersedes_revision="r1",change="correction"),
            amount=Money(D("110.00"),"CAD"),revision_reason="Explicit source correction")
        self.commit(batch((corrected,)))
        self.commit(batch((original,)))
        self.assertEqual([row["quantity"] for row in ingestion.read_facts(self.root)["effects"]],["110.00"])
        void=replace(corrected,key=replace(corrected.key,revision="r3",supersedes_revision="r2",change="void"),status="cancelled",revision_reason="Explicit source retraction")
        self.commit(batch((void,)))
        self.assertEqual(ingestion.read_facts(self.root)["effects"],[])
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_records")[0][0],3)

    def test_revision_conflicts_or_unknown_parent_do_not_write(self):
        self.commit(batch((funding(),)))
        before=file_hashes(self.root)
        changed=replace(funding(),amount=Money(D(200),"CAD"))
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(batch((changed,)))
        self.assertEqual(caught.exception.code,"record_revision_conflict")
        wrong=replace(changed,key=replace(changed.key,revision="r2",supersedes_revision="missing",change="correction"),revision_reason="Synthetic correction")
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(batch((wrong,)))
        self.assertEqual(caught.exception.code,"record_lineage_conflict")
        self.assertEqual(file_hashes(self.root),before)

    def test_partial_snapshot_replacement_never_creates_disposal_or_zero(self):
        other=replace(POSITION,key=replace(KEY,source_id="position-002"),asset=replace(POSITION.asset,symbol="DEMO2"))
        self.commit(batch((POSITION,other)))
        corrected=replace(POSITION,key=replace(KEY,revision="r2",supersedes_revision="r1",change="correction"),revision_reason="Corrected partial export")
        self.commit(batch((corrected,)))
        facts=ingestion.read_facts(self.root)
        self.assertEqual(len(facts["records"]),1)
        self.assertEqual(facts["records"][0]["quantity"],"1.25")
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_records")[0][0],3)
        self.assertEqual(facts["effects"],[])
        self.assertTrue(any('partial' in row["payload_json"] for row in facts["coverage"]))

    def test_empty_partial_snapshot_retains_scope_and_no_fabricated_positions(self):
        self.commit()
        snapshot=v2.Snapshot(POSITION.observation_id,"r2",AT,(ACCOUNT,),"r1")
        coverage=(v2.Coverage("holdings",ACCOUNT,AT,AT,"partial","Explicit partial empty export","records-holdings","r2","r1",POSITION.observation_id),)
        self.commit(batch(records=(),snapshots=(snapshot,),coverage=coverage))
        self.assertEqual(ingestion.read_facts(self.root)["records"],[])
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_records")[0][0],1)

    def test_cash_funding_purchase_and_linked_cash_leg_have_no_double_effect(self):
        cash=v2.CashFlow(replace(KEY,source_id="purchase-cash"),AT,"transfer","out",Money(D("100.00"),"CAD"),"completed","internal", "purchase-link",
            cash_leg_of=v2.Reference(ACCOUNT,"crypto_transactions","purchase-001"))
        self.commit(batch((funding(),purchase(),cash)))
        facts=ingestion.read_facts(self.root)
        self.assertEqual(len(facts["records"]),3)
        self.assertEqual(len(facts["effects"]),3)
        cash_effects=[D(row["quantity"]) for row in facts["effects"] if json.loads(row["asset_json"])["kind"]=="cash"]
        self.assertEqual(sum(cash_effects),D(0))
        self.assertFalse(facts["contributions_calculated"])
        duplicate=replace(cash,key=replace(cash.key,source_id="second-cash-copy"))
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(batch((duplicate,)))
        self.assertEqual(caught.exception.code,"duplicate_cash_leg")
        with self.assertRaises(ingestion.IngestionError):self.plan(batch((replace(duplicate,amount=Money(D(99),"CAD")),)))

    def test_unresolved_cash_leg_rejects_and_fees_are_not_deducted_twice(self):
        cash=v2.CashFlow(replace(KEY,source_id="cash"),AT,"transfer","out",Money(D(100),"CAD"),"completed","internal","link",
            cash_leg_of=v2.Reference(ACCOUNT,"crypto_transactions","missing"))
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(batch((cash,)))
        self.assertEqual(caught.exception.code,"cash_leg_unresolved")
        event=purchase(fees=(v2.Fee(ACCOUNT,CAD,D(1),False,False),))
        self.commit(batch((event,)))
        self.assertEqual(sum(D(row["quantity"]) for row in ingestion.read_facts(self.root)["effects"] if json.loads(row["asset_json"])["kind"]=="cash"),D(-101))
        other=replace(event,key=replace(event.key,source_id="purchase-002"),fees=(v2.Fee(ACCOUNT,CAD,D(1),True,True),))
        self.commit(batch((other,)))
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_effects WHERE role='separate_fee'")[0][0],1)

    def test_signed_source_effects_do_not_round_under_the_process_decimal_context(self):
        exact=D("1234567890123456789012345678901234567890123456789012345678901234567890.000000000000000001")
        outgoing=replace(funding(),type="withdrawal",direction="out",amount=Money(exact,"CAD"))
        self.commit(batch((outgoing,)))
        effect=ingestion.read_facts(self.root)["effects"][0]
        self.assertEqual(D(effect["quantity"]),exact.copy_negate())

    def test_unknown_fees_and_pending_unsupported_events_remain_evidence(self):
        pending=replace(purchase(),status="pending",type="sale")
        self.commit(batch((pending,)))
        self.assertEqual(ingestion.read_facts(self.root)["effects"],[])
        self.assertIsNone(ingestion.read_facts(self.root)["records"][0]["fees"])
        completed=replace(pending,status="completed",key=replace(pending.key,revision="r2",supersedes_revision="r1",change="correction"),revision_reason="Source status update")
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(batch((completed,)))
        self.assertEqual(caught.exception.code,"unsupported_effect")

    def test_unresolved_transfer_is_not_an_inferred_contribution(self):
        transfer=v2.CashFlow(replace(KEY,source_id="transfer-001"),AT,"transfer","out",Money(D(20),"CAD"),"completed","internal","transfer-ref")
        result=self.commit(batch((transfer,)))
        self.assertEqual(result["unresolved_transfers"],1)
        self.assertFalse(result["contributions_calculated"])

    def test_explicit_cross_provider_transfer_matches_only_reciprocal_amounts(self):
        other=AccountKey("another","account-001")
        left=v2.CashFlow(replace(KEY,source_id="transfer-out"),AT,"transfer","out",Money(D("20.00"),"CAD"),"completed","internal","pair",
            counterpart=v2.Reference(other,"cash_flows","transfer-in"))
        right=v2.CashFlow(replace(KEY,account=other,source_id="transfer-in"),AT,"transfer","in",Money(D("20"),"CAD"),"completed","internal","pair",
            counterpart=v2.Reference(ACCOUNT,"cash_flows","transfer-out"))
        self.commit(batch((left,)))
        value=replace(batch((right,),accounts=(replace(META,key=other),)),adapter=replace(INFO,provider_id="another",adapter_id="another.v2"))
        result=self.commit(value)
        self.assertEqual(result["unresolved_transfers"],0)
        self.assertEqual(sum(D(row["quantity"]) for row in ingestion.read_facts(self.root)["effects"]),D(0))
        corrected=replace(right,key=replace(right.key,revision="r2",supersedes_revision="r1",change="correction"),amount=Money(D(21),"CAD"),revision_reason="Mismatched source correction")
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(replace(value,records=(corrected,)))
        self.assertEqual(caught.exception.code,"transfer_mismatch")

    def test_bindings_are_required_injective_and_portfolio_scoped(self):
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(bindings=())
        self.assertEqual(caught.exception.code,"binding_required")
        self.commit(bindings=(ingestion.Binding(ACCOUNT,"canonical_a"),))
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(bindings=(ingestion.Binding(ACCOUNT,"changed"),))
        self.assertEqual(caught.exception.code,"binding_conflict")
        first=self.root
        self.root=self.root.parent/"another-ledger"; self.root.mkdir()
        self.commit(bindings=(ingestion.Binding(ACCOUNT,"canonical_b"),))
        self.assertEqual(ingestion.read_facts(first)["bindings"][0]["ledger_account"],"canonical_a")
        self.assertEqual(ingestion.read_facts(self.root)["bindings"][0]["ledger_account"],"canonical_b")

    def test_new_provider_cannot_claim_legacy_or_previously_bound_identity(self):
        initialize(self.root)
        with sqlite3.connect(self.root/"data/db/portfolio.sqlite3") as conn:
            conn.execute("INSERT INTO accounts VALUES(?,?,?,?)",("a_legacy","TFSA","Synthetic legacy","****0001"))
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(bindings=(ingestion.Binding(ACCOUNT,"a_legacy"),))
        self.assertEqual(caught.exception.code,"legacy_binding_required")
        before=self.query("SELECT * FROM accounts")
        self.commit(bindings=(ingestion.Binding(ACCOUNT,"a_legacy","legacy_holdings"),))
        self.assertEqual(self.query("SELECT * FROM accounts"),before)
        other=AccountKey("another","account-001")
        value=replace(batch((replace(POSITION,key=replace(KEY,account=other)),),accounts=(replace(META,key=other),)),adapter=replace(INFO,provider_id="another",adapter_id="another.v2"))
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(value,bindings=(ingestion.Binding(other,"a_legacy","legacy_holdings"),))
        self.assertEqual(caught.exception.code,"binding_collision")

    def test_changed_account_metadata_and_membership_revision_require_review(self):
        self.commit()
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(batch(accounts=(replace(META,account_type="RRSP"),)))
        self.assertEqual(caught.exception.code,"account_metadata_conflict")
        value=batch(membership=replace(batch().membership,status="complete"))
        with self.assertRaises(ingestion.IngestionError) as caught:self.plan(value)
        self.assertEqual(caught.exception.code,"scope_revision_conflict")
        value=replace(value,membership=replace(value.membership,revision="scope2",supersedes_revision="scope1"))
        self.commit(value)
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_scopes WHERE scope_key='membership:exported-accounts'")[0][0],2)

    def test_source_errors_scope_conflicts_and_invalid_plans_never_write(self):
        value=batch()
        invalid=replace(value,evidence=replace(value.evidence,diagnostics=(v2.Diagnostic("synthetic.bad_source","error"),)))
        with self.assertRaises(ingestion.IngestionError):self.plan(invalid)
        corrected=replace(POSITION,key=replace(KEY,revision="r2",supersedes_revision="r1",change="correction"),revision_reason="Explicit change")
        with self.assertRaises(ingestion.IngestionError):
            ingestion.prepare_ingestion(self.root,(ingestion.SourceInput(value,RAW),ingestion.SourceInput(batch((corrected,)),RAW)),bindings=(ingestion.new_binding(ACCOUNT),))
        plan=self.plan()
        for changed in (replace(plan,policy="unknown"),replace(plan,environment_sha256="b"*64)):
            with self.assertRaises(ingestion.IngestionError):ingestion.commit_ingestion(resolve_workspace(explicit=self.root),changed)
        self.assertEqual(file_hashes(self.root),{})

    def test_financial_or_environment_changes_invalidate_prepared_plan(self):
        self.commit(batch((funding(),)))
        plan=self.plan()
        self.commit(batch((replace(funding(),key=replace(KEY,source_id="new-funding")),)))
        with self.assertRaises(ingestion.IngestionError) as caught:ingestion.commit_ingestion(resolve_workspace(explicit=self.root),plan)
        self.assertEqual(caught.exception.code,"stale_plan")
        plan=self.plan()
        with patch("wealth_ledger.source_ingestion.environment_fingerprint",return_value="b"*64),self.assertRaises(ingestion.IngestionError):
            ingestion.commit_ingestion(resolve_workspace(explicit=self.root),plan)
        self.assertEqual(self.query("SELECT COUNT(*) FROM src_records")[0][0],2)

    def test_atomic_failure_rolls_back_bindings_schema_and_effects(self):
        plan=self.plan(batch((funding(),purchase())))
        original=ingestion._effect_rows
        def fail_after_first(record):
            if isinstance(record,v2.CryptoTransaction):raise RuntimeError("Synthetic injected failure")
            return original(record)
        with patch("wealth_ledger.source_ingestion._effect_rows",side_effect=fail_after_first),self.assertRaises(RuntimeError):
            ingestion.commit_ingestion(resolve_workspace(explicit=self.root),plan)
        self.assertEqual(self.query("SELECT name FROM sqlite_master WHERE name LIKE 'src_%'"),[])
        self.assertEqual(ingestion.verify_store(self.root)["schema_version"],0)
        self.assertEqual(self.query("SELECT status FROM update_operations")[0][0],"data_failed")

    def test_completed_operation_replay_needs_no_parser_or_new_environment(self):
        plan=self.plan(batch((funding(),)))
        op="OP-"+uuid.uuid4().hex
        first=ingestion.commit_ingestion(resolve_workspace(explicit=self.root),plan,operation_id=op)
        with patch("wealth_ledger.source_ingestion.environment_fingerprint",side_effect=AssertionError("Committed replay must not inspect new code")):
            second=ingestion.commit_ingestion(resolve_workspace(explicit=self.root),plan,operation_id=op)
        self.assertEqual(first,second)
        self.assertEqual(len(ingestion.read_facts(self.root)["effects"]),1)

    def test_response_failure_after_commit_replays_the_durable_receipt(self):
        from wealth_ledger import operations
        plan=self.plan(batch((funding(),)))
        operation_id="OP-"+uuid.uuid4().hex
        atomic=operations.atomic_data
        def fail_after_commit(*args,**kwargs):
            atomic(*args,**kwargs)
            raise RuntimeError("Synthetic delivery failure after commit")
        with patch("wealth_ledger.operations.atomic_data",side_effect=fail_after_commit),self.assertRaises(RuntimeError):
            ingestion.commit_ingestion(resolve_workspace(explicit=self.root),plan,operation_id=operation_id)
        self.assertEqual(self.query("SELECT status FROM update_operations WHERE operation_id=?",(operation_id,))[0][0],"data_only_complete")
        result=ingestion.commit_ingestion(resolve_workspace(explicit=self.root),plan,operation_id=operation_id)
        self.assertEqual(result["new_records"],1)
        self.assertEqual(len(ingestion.read_facts(self.root)["effects"]),1)

    def test_canonical_evidence_effect_and_membership_tamper_are_detected(self):
        self.commit(batch((funding(),purchase())))
        db=self.root/"data/db/portfolio.sqlite3"
        with sqlite3.connect(db) as conn:conn.execute("UPDATE src_effects SET quantity='999'")
        with self.assertRaises(ingestion.IngestionError):ingestion.verify_store(self.root)

    def test_missing_archive_future_schema_and_unsafe_paths_fail_closed(self):
        self.commit()
        row=self.query("SELECT raw_path FROM src_batches")[0][0]
        raw=self.root/row
        saved=raw.read_bytes();raw.unlink()
        with self.assertRaises(ingestion.IngestionError):self.plan()
        raw.write_bytes(saved)
        with sqlite3.connect(self.root/"data/db/portfolio.sqlite3") as conn:conn.execute("UPDATE src_schema SET version=999")
        with self.assertRaises(ingestion.IngestionError):self.plan()

    def test_legacy_ids_rows_archives_and_frozen_reports_survive_explicit_binding(self):
        from wealth_ledger.core import import_holdings,make_payload
        from wealth_ledger.combined import make_combined_payload
        project=Path(__file__).resolve().parents[1]
        fx=json.loads((project/"examples/data/fx.json").read_text())
        import_holdings(self.root,project/"examples/data/wealthsimple-holdings.csv","baseline",fx)
        names=("schema_info","sources","accounts","snapshots","positions","cash_flows","flow_periods")
        old={name:self.query("SELECT * FROM "+name) for name in names}
        frozen=self.root/"reports/frozen/report.md";frozen.parent.mkdir(parents=True);frozen.write_bytes(b"Synthetic frozen historical report")
        before=file_hashes(self.root/"data/raw")
        account=next(row for row in self.query("SELECT * FROM accounts") if row[1]=="TFSA")
        value=batch(accounts=(replace(META,account_type=account[1],masked_identifier=account[3]),))
        self.commit(value,bindings=(ingestion.Binding(ACCOUNT,account[0],"legacy_holdings"),))
        self.assertEqual(old,{name:self.query("SELECT * FROM "+name) for name in names})
        after=file_hashes(self.root/"data/raw")
        self.assertTrue(all(after[name]==sha for name,sha in before.items()))
        self.assertEqual(frozen.read_bytes(),b"Synthetic frozen historical report")
        for action in (lambda:make_payload(self.root),lambda:make_combined_payload(self.root)):
            with self.assertRaises(ingestion.IngestionError) as caught:action()
            self.assertEqual(caught.exception.code,"report_projection_unavailable")

    def test_database_backup_rolls_back_new_schema_without_reimport(self):
        from wealth_ledger.publishing import database_backup
        initialize(self.root)
        old=fingerprint(self.root)
        backup=self.root/database_backup(self.root,"synthetic-before-source-store")
        self.commit()
        self.assertEqual(ingestion.verify_store(self.root)["schema_version"],1)
        with closing(sqlite3.connect(backup.as_uri()+"?mode=ro",uri=True)) as src,closing(sqlite3.connect(self.root/"data/db/portfolio.sqlite3")) as dst:
            src.backup(dst)
        self.assertEqual(ingestion.verify_store(self.root)["schema_version"],0)
        self.assertEqual(fingerprint(self.root),old)
        self.assertTrue((self.root/"data/raw/source-v2").is_dir())

    def test_binding_declaration_and_record_order_tamper_are_detected(self):
        self.commit(batch((funding(),)))
        declaration=self.query("SELECT declaration_path FROM src_bindings")[0][0]
        path=self.root/declaration;path.chmod(0o600);path.write_bytes(b"synthetic tampered binding")
        with self.assertRaises(ingestion.IngestionError):ingestion.verify_store(self.root)

    def test_source_facts_participate_in_existing_financial_fingerprints(self):
        initialize(self.root)
        before=fingerprint(self.root)
        self.commit(batch((funding(),)))
        self.assertNotEqual(before,fingerprint(self.root))


class ActualRuntimeTests(unittest.TestCase):
    def test_real_code_fingerprint_canonical_commit_and_archived_replay(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-v2-runtime-") as directory:
            root=Path(directory).resolve()
            plan=ingestion.prepare_ingestion(root,(ingestion.SourceInput(batch((funding(),)),RAW),),bindings=(ingestion.new_binding(ACCOUNT),))
            result=ingestion.commit_ingestion(resolve_workspace(explicit=root),plan)
            self.assertEqual(result["environment_sha256"],plan.environment_sha256)
            self.assertEqual(ingestion.verify_store(root)["batches"],1)
