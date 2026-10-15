"""Isolated financial scenarios for observations, revisions, and late inputs."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import csv
import json
import sqlite3
import tempfile
import unittest
import zipfile

from wealth_ledger import wallet, operations
from wealth_ledger.core import import_holdings, initialize
from wealth_ledger.crypto import import_bull_orders
from wealth_ledger.crypto_opening import import_opening
from wealth_ledger.workflow import prepare_update, ingest_inputs, select_context
from wealth_ledger.reporting import generate_reports
from wealth_ledger.workbook import build_workbook, verify_workbook
from wealth_ledger.validation import validate_formula_caches
from wealth_ledger.wallet_reports import write_exports
from test_core import FX, write_holdings
from test_crypto import FIELDS, ASSUMPTIONS, order
from test_combined import quote

PROJECT = Path(__file__).resolve().parents[1]
NOW = "2026-10-10T20:00:00Z"
T1 = "2026-01-10T18:10:00-05:00"
T2 = "2026-02-10T18:10:00-05:00"


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wallet-test-")
        self.root = Path(self.temp.name)
        self.project = self.root/"project"
        (self.project/"config").mkdir(parents=True)
        (self.project / "config/local.toml").write_text("[reporting]\nbtc_cost_policy = 'bull_average_proxy'\n", encoding="utf-8")
        (self.project/"config/bull-opening.json").write_text(json.dumps(ASSUMPTIONS), encoding="utf-8")
        initialize(self.project)
        self.rows = [order("fund", amount="100"), order("buy", "Buy Bitcoin", "100", "BTC", ".08", completed="2026-01-01T02:00:00Z")]
        self.path = self.orders(self.rows)
        import_bull_orders(self.project, self.path, opening_assumption=ASSUMPTIONS)

    def tearDown(self):
        self.temp.cleanup()

    def orders(self, rows, name="orders.csv"):
        path = self.root/name
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,FIELDS);writer.writeheader();writer.writerows(rows)
        return path

    def balance(self, amount=".0799", time=T1, **kwargs):
        return wallet.add_balance(self.project, amount, time, now=NOW, **kwargs)

    def event(self, *, amount=".0001", time="2026-01-10T18:00:00-05:00", type="fee", reference="fee-1", balance=None):
        return wallet.add_event(self.project, type=type, quantity_btc=amount, occurred_at=time,
                                source="synthetic wallet", reference=reference, balance_id=balance, now=NOW)

    def view(self, time=T2):
        return wallet.make_crypto_view(self.project,time)

    def counts(self):
        with sqlite3.connect(self.project/"data/db/portfolio.sqlite3") as conn:
            return {name:conn.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0] for name in ("crypto_order_revisions","cash_flows","wallet_records","wallet_revisions")}

    def test_unknown_gap_uses_observation_without_inventing_event(self):
        b=self.balance();v=self.view()
        self.assertEqual(v["btc_equivalent_qty"],"0.07990000")
        r=v["wallet"]["reconciliations"][0]
        self.assertEqual((r["expected_btc"],r["residual_btc"],r["status"]),("0.08000000","-0.00010000","unexplained"))
        self.assertEqual(self.counts()["cash_flows"],0)
        self.assertEqual(self.counts()["wallet_records"],1)
        self.assertEqual(wallet.balance_detail(self.project,b["record_id"])["record"]["verification"],"user_reported")

    def test_old_fee_resolves_gap_without_double_subtraction(self):
        b=self.balance();self.event(balance=b["record_id"])
        v=self.view();r=v["wallet"]["reconciliations"][0]
        self.assertEqual(v["btc_equivalent_qty"],"0.07990000")
        self.assertEqual((r["expected_btc"],r["residual_btc"],r["status"]),("0.07990000","0.00000000","arithmetic_match"))
        self.assertEqual(r["recorded_residual_btc"],"-0.00010000")

    def test_event_after_anchor_changes_future_only(self):
        b=self.balance();self.event(time="2026-01-12T12:00:00Z")
        self.assertEqual(self.view(T1)["btc_equivalent_qty"],"0.07990000")
        self.assertEqual(self.view()["btc_equivalent_qty"],"0.07980000")
        with self.assertRaisesRegex(ValueError,"outside"):
            self.event(time="2026-01-12T12:00:00Z",reference="wrong-link",balance=b["record_id"])

    def test_same_time_event_included_in_observation_not_later_estimate(self):
        b=self.balance();self.event(time=T1,balance=b["record_id"])
        self.assertEqual(self.view()["btc_equivalent_qty"],"0.07990000")
        self.assertEqual(self.view()["wallet"]["unresolved_count"],0)

    def test_second_matching_balance_does_not_erase_old_gap(self):
        self.balance();self.balance(time=T2)
        rows=self.view()["wallet"]["reconciliations"]
        self.assertEqual([r["status"] for r in rows],["unexplained","arithmetic_match"])
        self.assertEqual(self.view()["wallet"]["unresolved_count"],1)
        self.assertEqual(self.view()["wallet"]["anchor_ledger_residual_btc"],"-0.00010000")

    def test_partial_and_overexplained_gap_remain_visible(self):
        b=self.balance();self.event(amount=".00004",balance=b["record_id"])
        self.assertEqual(self.view()["wallet"]["reconciliations"][0]["residual_btc"],"-0.00006000")
        self.event(amount=".00008",reference="fee-2",balance=b["record_id"])
        self.assertEqual(self.view()["wallet"]["reconciliations"][0]["residual_btc"],"0.00002000")

    def test_positive_external_in_can_explain_positive_gap(self):
        b=self.balance(".0801");self.event(type="external_in",balance=b["record_id"])
        self.assertEqual(self.view()["wallet"]["unresolved_count"],0)
        self.assertEqual(self.counts()["cash_flows"],0)

    def test_own_transfer_and_conversion_do_not_reduce_holdings(self):
        self.balance(".08")
        self.event(type="own_transfer",amount=".02")
        self.event(type="conversion",amount=".01",reference="swap")
        self.assertEqual(self.view()["btc_equivalent_qty"],"0.08000000")

    def test_all_debit_types_and_no_cash_or_cost_invention(self):
        self.balance(".08")
        for i,type in enumerate(("fee","sale","spend","external_out")):
            self.event(type=type,time="2026-01-11T01:00:00Z",reference=f"debit-{i}")
        v=self.view()
        self.assertEqual(v["btc_equivalent_qty"],"0.07960000")
        self.assertEqual(v["cash_cad"],"0")
        self.assertTrue(v["meta"]["cost_unknown"])

    def test_balance_dedup_utc_equivalence_and_new_time(self):
        b=self.balance();duplicate=self.balance(time="2026-01-10T23:10:00Z")
        self.assertEqual(duplicate["record_id"],b["record_id"])
        self.assertEqual(duplicate["status"],"duplicate")
        later=self.balance(time=T2)
        self.assertNotEqual(later["record_id"],b["record_id"])
        with self.assertRaisesRegex(ValueError,"Same-time"):
            self.balance(".08")

    def test_zero_balance_is_valid_and_satoshi_gap_is_not_rounded_away(self):
        self.balance("0")
        self.assertEqual(self.view()["btc_equivalent_qty"],"0.00000000")
        p=self.project
        wallet.revise(p,wallet.records(p,"balance")[0]["record_id"],expected_revision=1,reason="test",quantity_btc=".07999999")
        self.assertEqual(self.view()["wallet"]["reconciliations"][0]["residual_btc"],"-0.00000001")

    def test_invalid_precision_amounts_and_future_time(self):
        for amount in ("-.1","NaN","Infinity",".000000001"):
            with self.subTest(amount=amount),self.assertRaises(ValueError):
                self.balance(amount)
        with self.assertRaises(ValueError):
            self.balance(time="2026-01-10T10:00:00")
        with self.assertRaisesRegex(ValueError,"future"):
            self.balance(time="2037-01-01T00:00:00Z")
        with self.assertRaises(ValueError):
            self.event(amount="0")

    def test_event_reference_dedup_and_conflict(self):
        a=self.event();b=self.event()
        self.assertEqual(a["record_id"],b["record_id"])
        with self.assertRaisesRegex(ValueError,"reference conflict"):
            self.event(amount=".0002")
        c=self.event(reference="same-second-distinct-fee")
        self.assertNotEqual(c["record_id"],a["record_id"])

    def test_stable_revision_void_and_replacement(self):
        b=self.balance()
        r=wallet.revise(self.project,b["record_id"],expected_revision=1,reason="typo",quantity_btc=".08")
        self.assertEqual((r["record_id"],r["revision"]),(b["record_id"],2))
        with self.assertRaisesRegex(ValueError,"Stale"):
            wallet.revise(self.project,b["record_id"],expected_revision=1,reason="stale",quantity_btc=".09")
        wallet.revise(self.project,b["record_id"],expected_revision=2,reason="wrong time",action="void")
        newer=self.balance(time=T2,replaces=b["record_id"])
        self.assertNotEqual(b["record_id"],newer["record_id"])
        self.assertEqual(len(wallet.revision_history(self.project,b["record_id"])),3)

    def test_identity_cannot_be_revised(self):
        b=self.balance()
        with self.assertRaisesRegex(ValueError,"Identity"):
            wallet.revise(self.project,b["record_id"],expected_revision=1,reason="wrong",as_of=T2)
        e=self.event()
        with self.assertRaisesRegex(ValueError,"Identity"):
            wallet.revise(self.project,e["record_id"],expected_revision=1,reason="wrong",reference="changed")

    def test_event_revision_and_void_recompute_gap(self):
        b=self.balance();e=self.event(balance=b["record_id"])
        wallet.revise(self.project,e["record_id"],expected_revision=1,reason="actual fee",quantity_btc=".00009")
        self.assertEqual(self.view()["wallet"]["reconciliations"][0]["residual_btc"],"-0.00001000")
        wallet.revise(self.project,e["record_id"],expected_revision=2,reason="duplicate",action="void")
        self.assertEqual(self.view()["wallet"]["reconciliations"][0]["residual_btc"],"-0.00010000")

    def test_explicit_link_unlink_does_not_duplicate_event(self):
        b=self.balance();e=self.event()
        wallet.revise(self.project,e["record_id"],expected_revision=1,reason="attribute",action="link",balance_id=b["record_id"])
        self.assertEqual(self.view()["wallet"]["unresolved_count"],0)
        wallet.revise(self.project,e["record_id"],expected_revision=2,reason="remove attribution",action="unlink",balance_id=None)
        self.assertEqual(self.view()["wallet"]["unresolved_count"],0)
        self.assertEqual(self.counts()["wallet_records"],2)

    def test_wrong_and_void_balance_ids_rejected(self):
        with self.assertRaisesRegex(ValueError,"Unknown or void"):
            self.event(balance="B999999")
        b=self.balance()
        wallet.revise(self.project,b["record_id"],expected_revision=1,reason="invalid",action="void")
        with self.assertRaisesRegex(ValueError,"Unknown or void"):
            self.event(balance=b["record_id"])

    def test_inserted_predecessor_marks_attribution_stale(self):
        b=self.balance(time=T2);self.event(time="2026-02-01T00:00:00Z",balance=b["record_id"])
        self.balance(time=T1)
        self.assertEqual(self.view()["wallet"]["reconciliations"][-1]["status"],"link_conflict")

    def test_event_linked_to_later_balance_must_follow_prior_balance(self):
        self.balance();b=self.balance(time=T2)
        with self.assertRaisesRegex(ValueError,"outside"):
            self.event(balance=b["record_id"])

    def test_late_purchase_before_anchor_updates_gap_not_quantity(self):
        self.balance(".081")
        rows=self.rows+[order("fund2",amount="100",created="2026-01-02T00:00:00Z",completed="2026-01-02T01:00:00Z"),
            order("late-buy","Buy Bitcoin","100","LBTC",".001",created="2026-01-02T00:00:00Z",completed="2026-01-02T02:00:00Z")]
        import_bull_orders(self.project,self.orders(rows,"late.csv"),opening_assumption=ASSUMPTIONS)
        self.assertEqual(self.view()["btc_equivalent_qty"],"0.08100000")
        self.assertEqual(self.view()["wallet"]["unresolved_count"],0)

    def test_later_purchase_is_added_once_and_duplicate_csv_is_harmless(self):
        self.balance()
        rows=self.rows+[order("fund2",amount="100",created="2026-01-12T00:00:00Z",completed="2026-01-12T01:00:00Z"),
            order("later-buy","Buy Bitcoin","100","LBTC",".001",created="2026-01-12T00:00:00Z",completed="2026-01-12T02:00:00Z")]
        path=self.orders(rows,"later.csv")
        import_bull_orders(self.project,path,opening_assumption=ASSUMPTIONS)
        import_bull_orders(self.project,path,opening_assumption=ASSUMPTIONS)
        self.assertEqual(self.view()["btc_equivalent_qty"],"0.08090000")

    def test_future_observation_and_event_do_not_change_old_quantity(self):
        self.balance();self.balance(".1",time=T2)
        self.event(time="2026-02-12T00:00:00Z")
        self.assertEqual(self.view(T1)["btc_equivalent_qty"],"0.07990000")
        self.assertEqual(len(self.view(T1)["wallet"]["reconciliations"]),1)

    def test_negative_estimated_holdings_stop_valuation(self):
        self.balance(".00001")
        self.event(time="2026-01-11T00:00:00Z")
        with self.assertRaisesRegex(ValueError,"negative"):
            self.view()

    def test_source_integrity_is_checked(self):
        b=self.balance();path=self.project/b["source_path"]
        path.chmod(0o600);path.write_text("corrupt synthetic evidence", encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"corrupt"):
            self.view()

    def test_wallet_only_baseline_then_bull_history_is_not_added_twice(self):
        p=self.root/"wallet-only"
        wallet.add_balance(p,".09",T1,now=NOW)
        v=wallet.make_crypto_view(p,T2)
        self.assertEqual(v["btc_equivalent_qty"],"0.09000000")
        self.assertIsNone(v["wallet"]["ledger_expected_btc"])
        import_bull_orders(p,self.path,opening_assumption=ASSUMPTIONS)
        v=wallet.make_crypto_view(p,T2)
        self.assertEqual(v["btc_equivalent_qty"],"0.09000000")
        self.assertEqual(v["wallet"]["reconciliations"][0]["status"],"expected_unknown")

    def test_pre_opening_late_order_is_flagged_without_recalculating_opening(self):
        declaration=self.root/"opening.json"
        declaration.write_text(json.dumps({"reported_total_btc_equivalent":".09","reference_as_of":T1,
            "declared_on":"2026-01-11","balance_scope":wallet.SCOPE,"basis":"synthetic","confirmed_by":"test"}), encoding="utf-8")
        import_opening(self.project,declaration)
        self.balance(".09",time=T2)
        extra=[order("fund2",amount="100",created="2026-01-02T00:00:00Z",completed="2026-01-02T01:00:00Z"),
               order("overlap","Buy Bitcoin","100","BTC",".001",created="2026-01-02T00:00:00Z",completed="2026-01-02T02:00:00Z")]
        import_bull_orders(self.project,self.orders(self.rows+extra,"overlap.csv"),opening_assumption=ASSUMPTIONS)
        v=self.view()
        self.assertEqual(v["opening_btc_equivalent_qty"],"0.01")
        self.assertTrue(v["wallet"]["opening_overlap"])
        self.assertEqual(v["btc_equivalent_qty"],"0.09000000")
        self.assertIsNone(v["wallet"]["ledger_expected_btc"])

    def test_event_batch_is_atomic_and_original_csv_is_archived(self):
        b=self.balance();path=self.root/"events.csv"
        fields=("source","reference","type","occurred_at","quantity_btc","balance_id")
        def write(rows):
            with path.open("w",newline="", encoding="utf-8") as stream:
                writer=csv.writer(stream);writer.writerow(fields);writer.writerows(rows)
        write([["wallet","good","fee","2026-01-10T18:00:00-05:00",".0001",b["record_id"]],
               ["wallet","bad","fee","2026-01-11T18:00:00-05:00",".0001",b["record_id"]]])
        before=self.counts()
        with self.assertRaisesRegex(ValueError,"outside"):
            wallet.import_events(self.project,path,now=NOW)
        self.assertEqual(self.counts(),before)
        write([["wallet","good","fee","2026-01-10T18:00:00-05:00",".0001",b["record_id"]]])
        result=wallet.import_events(self.project,path,now=NOW)
        self.assertEqual((self.project/result["source_path"]).read_bytes(),path.read_bytes())
        self.assertEqual(self.view()["wallet"]["unresolved_count"],0)

    def test_atomic_input_stage_does_not_leave_first_valid_import(self):
        before=operations.fingerprint(self.project)
        def bad(stage):
            wallet.add_balance(stage,".08",T1,now=NOW)
            wallet.add_event(stage,type="fee",quantity_btc="-.1",occurred_at=T1,source="test",reference="bad",now=NOW)
        with self.assertRaises(ValueError):
            operations.atomic_data(self.project,bad)
        self.assertEqual(operations.fingerprint(self.project),before)
        self.assertFalse(wallet.records(self.project))

    def test_report_failure_resume_keeps_single_observation_and_fixed_time(self):
        request={"btc_balance":".0799","btc_balance_as_of":T1,"as_of":T1}
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda p,t,f:quote(t)):
            with self.assertRaises(operations.ReportOperationError):
                operations.execute_update(self.project,request,lambda *args:(_ for _ in ()).throw(ValueError("synthetic report failure")))
            failed=operations.list_operations(self.project)[0]
            self.assertEqual(failed["status"],"report_failed")
            seen=[]
            def success(payload,result,run):
                seen.append(payload["meta"]["as_of"])
                return {"output":"synthetic-output"}
            result=operations.execute_update(self.project,{},success,resume=failed["operation_id"])
            again=operations.execute_update(self.project,{},success,resume=failed["operation_id"])
        self.assertEqual(len(wallet.records(self.project,"balance")),1)
        self.assertEqual(len(seen),1)
        self.assertEqual(again["status"],"already_published")
        self.assertEqual(result["operation_id"],failed["operation_id"])

    def test_resume_preserves_saved_locale_and_rejects_changed_catalog(self):
        from wealth_ledger.i18n import PresentationContext
        request={"btc_balance":".0799","btc_balance_as_of":T1,"as_of":T1,"report_locale":"en-CA"}
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda p,t,f:quote(t)):
            with self.assertRaises(operations.ReportOperationError):
                operations.execute_update(self.project,request,lambda *args:(_ for _ in ()).throw(ValueError("synthetic report failure")))
            failed=operations.list_operations(self.project)[0]
            self.assertEqual(failed['request']['report_locale'],'en-CA')
            config=self.project/'config/local.toml'
            config.parent.mkdir(parents=True,exist_ok=True)
            config.write_text('[reporting]\nlocale = "zh-CN"\n',encoding='utf-8')
            original=PresentationContext.metadata
            with patch.object(PresentationContext,'metadata',lambda self:{**original(self),'catalog_sha256':'changed'}):
                with self.assertRaisesRegex(operations.ReportOperationError,'catalog changed'):
                    operations.execute_update(self.project,{},lambda *args:self.fail('publisher must not run'),resume=failed['operation_id'])
            seen=[]
            operations.execute_update(self.project,{},lambda payload,*args:seen.append(payload['reporting']['locale']) or {'output':'synthetic'},resume=failed['operation_id'])
        self.assertEqual(seen,['en-CA'])
        self.assertEqual(len(wallet.records(self.project,'balance')),1)

    def test_stale_pending_operation_rejected_after_new_inputs(self):
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=ValueError("quote unavailable")):
            with self.assertRaises(operations.ReportOperationError):
                operations.execute_update(self.project,{"btc_balance":".0799","btc_balance_as_of":T1,"as_of":T1},lambda *a:{})
        failed=operations.list_operations(self.project)[0]
        self.event()
        with self.assertRaisesRegex(ValueError,"stale"):
            operations.execute_update(self.project,{},lambda *a:{},resume=failed["operation_id"])
        self.assertEqual(operations.get(self.project,failed["operation_id"])["status"],"stale")

    def test_query_operations_is_readonly(self):
        before=(self.project/"data/db/portfolio.sqlite3").read_bytes()
        self.assertEqual(operations.list_operations(self.project),[])
        self.assertEqual((self.project/"data/db/portfolio.sqlite3").read_bytes(),before)

    def test_zero_and_positive_reports_keep_same_scope_and_cost_unknown(self):
        ws=write_holdings(self.root/"ws.csv");import_holdings(self.project,ws,"baseline",FX)
        time="2026-10-10T12:00:00-04:00"
        self.balance(".08",time=time)
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda p,t,f:quote(t)):
            first,_=prepare_update(self.project,as_of=time)
            self.balance("0",time="2026-10-10T13:00:00-04:00")
            zero,_=prepare_update(self.project,as_of="2026-10-10T13:00:00-04:00")
        self.assertEqual(first["meta"]["scope_id"],zero["meta"]["scope_id"])
        self.assertEqual(first["meta"]["account_count"],zero["meta"]["account_count"])
        self.assertIsNone(first["crypto"]["valuation"]["unrealized_cad"])
        self.assertFalse(any(p["scope"]=="portfolio" for p in first["periods"]))

    def test_matching_balance_keeps_numeric_zero_difference_across_reports(self):
        self.balance(".08")
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda p,t,f:quote(t)):
            payload,_=prepare_update(self.project,as_of=T2)
        out=self.root/"matched-report"
        artifacts=generate_reports(payload,out)
        build_workbook(payload,out/"portfolio.ods",chart_images=artifacts["charts"])
        from wealth_ledger.report_checks import validate_report_presentation
        self.assertEqual(validate_report_presentation(payload,out)["status"],"passed")
        self.assertEqual(payload['crypto']['wallet']['anchor_ledger_residual_btc'],'0.00000000')
        self.assertIn('| 錢包回報與同時間帳本推算量差額 | 0 |',(out/'report.md').read_text(encoding="utf-8"))

    def test_all_reports_have_gap_table_audit_exports_and_live_residual_formula(self):
        self.balance();self.event(amount=".00004")
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda p,t,f:quote(t)):
            payload,_=prepare_update(self.project,as_of=T2)
        out=self.root/"reports"
        artifacts=generate_reports(payload,out)
        build_workbook(payload,out/"portfolio.ods",chart_images=artifacts["charts"])
        write_exports(payload,out)
        self.assertEqual(validate_formula_caches(out/"portfolio.ods")["cache_mismatches"],0)
        from wealth_ledger.report_checks import validate_report_presentation
        self.assertEqual(validate_report_presentation(payload,out)["status"],"passed")

        self.assertEqual(verify_workbook(out/"portfolio.ods")["sheets"],11)
        self.assertIn("16_btc_wallet_reconciliation",artifacts["charts"])
        self.assertIn("-0.00006",(out/"report.md").read_text(encoding="utf-8"))
        self.assertIn("首次記錄",(out/"report.md").read_text(encoding="utf-8"))
        self.assertIn("平均買入價 CAD／BTC",(out/"report.md").read_text(encoding="utf-8"))
        with zipfile.ZipFile(out/"portfolio.ods") as archive:
            self.assertIn("平均買入價（CAD／BTC）",archive.read("content.xml").decode())
        self.assertIn("2026-01-10T18:10:00-05:00",(out/"report.md").read_text(encoding="utf-8"))
        self.assertIn("使用者指定查看時間",(out/"report.md").read_text(encoding="utf-8"))
        self.assertTrue((out/"btc-events.csv").exists())
        self.assertGreater((out/"report.pdf").stat().st_size,1000)

    def test_optional_inputs_all_four_combinations(self):
        ws=write_holdings(self.root/"ws.csv")
        now=datetime.fromisoformat(NOW)
        stamp="2026-10-10T12:00:00-04:00"
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda p,t,f:quote(t)):
            for index, paths in enumerate(([],[ws],[self.path],[ws,self.path])):
                with self.subTest(paths=len(paths)):
                    p=self.root/f"combo-{index}"
                    (p/"config").mkdir(parents=True)
                    (p/"config/bull-opening.json").write_text(json.dumps(ASSUMPTIONS), encoding="utf-8")
                    payload,result=prepare_update(p,paths,btc_balance=".0799",btc_balance_as_of=stamp,now=now)
                    self.assertEqual(payload["crypto"]["btc_equivalent_qty"],"0.07990000")
                    self.assertEqual(result["sources"]["wallet"]["status"],"recorded")
                    self.assertGreaterEqual(datetime.fromisoformat(payload["meta"]["as_of"]),datetime.fromisoformat(stamp))

    def test_default_observation_time_captured_once_and_no_input_keeps_it(self):
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda p,t,f:quote(t)):
            first,_=prepare_update(self.project,btc_balance=".0799",now=datetime.fromisoformat(NOW))
            later,_=prepare_update(self.project,now=datetime.fromisoformat("2026-10-10T22:00:00Z"))
        self.assertEqual(first["meta"]["as_of"],later["meta"]["as_of"])
        self.assertEqual(wallet.records(self.project,"balance")[0]["time_basis"],"execution_time")
        self.assertEqual(len(wallet.records(self.project,"balance")),1)

    def test_backfilled_old_balance_does_not_replace_latest_anchor(self):
        self.balance(".09",time=T2)
        self.balance(".0799",time=T1)
        self.assertEqual(self.view()["btc_equivalent_qty"],"0.09000000")
        self.assertEqual(self.view()["wallet"]["anchor"]["as_of"],wallet.timestamp(T2,NOW))

    def test_historical_report_never_uses_future_broker_snapshot(self):
        ws=write_holdings(self.root/"ws.csv");import_holdings(self.project,ws,"baseline",FX)
        self.balance()
        with self.assertRaisesRegex(ValueError,"No Wealthsimple snapshot"):
            prepare_update(self.project,as_of=T2)

    def test_zero_wallet_only_report_is_supported(self):
        p=self.root/"zero-wallet"
        wallet.add_balance(p,"0",T1,now=NOW)
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda p,t,f:quote(t)):
            payload,_=prepare_update(p,as_of=T1)
        out=self.root/"zero-report"
        artifacts=generate_reports(payload,out)
        build_workbook(payload,out/"portfolio.ods",chart_images=artifacts["charts"])
        self.assertEqual(Decimal(payload["totals"]["total_cad"]),0)
        self.assertEqual(payload["meta"]["account_count"],1)
        self.assertEqual(validate_formula_caches(out/"portfolio.ods")["cache_mismatches"],0)
        from wealth_ledger.report_checks import validate_report_presentation
        self.assertEqual(validate_report_presentation(payload,out)["status"],"passed")


    def test_two_source_invalid_batch_does_not_commit_valid_holdings(self):
        p=self.root/"rejected-batch"
        initialize(p)
        ws=write_holdings(self.root/"ws-batch.csv")
        invalid=self.orders([{**order("bad"),"ORDER_TYPE":"Unsupported"}],"invalid.csv")
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX):
            with self.assertRaises(ValueError):
                operations.atomic_data(p,lambda stage:ingest_inputs(stage,[ws,invalid],now=datetime.fromisoformat(NOW)))
        with sqlite3.connect(p/"data/db/portfolio.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],0)

    def test_quote_failure_preserves_input_ids_for_retry(self):
        request={"btc_balance":".0799","btc_balance_as_of":T1,"as_of":T1}
        with patch("wealth_ledger.workflow.resolve_rates",return_value=FX),patch("wealth_ledger.combined.resolve_btc_price",side_effect=ValueError("quote failure")):
            with self.assertRaises(operations.ReportOperationError):
                operations.execute_update(self.project,request,lambda *a:{})
        operation=operations.list_operations(self.project)[0]
        self.assertEqual(operation["status"],"report_failed")
        self.assertEqual(operation["result"]["sources"]["wallet"]["record_id"],wallet.records(self.project,"balance")[0]["record_id"])

    def test_completed_pending_order_before_opening_is_detected_as_overlap(self):
        pending=order("pending","Buy Bitcoin","100","BTC",".001",created="2026-01-02T00:00:00Z",completed="",status="Pending")
        extra_fund=order("fund2",amount="100",created="2026-01-02T00:00:00Z",completed="2026-01-02T01:00:00Z")
        import_bull_orders(self.project,self.orders(self.rows+[extra_fund,pending],"pending.csv"),opening_assumption=ASSUMPTIONS)
        declaration=self.root/"opening-pending.json"
        declaration.write_text(json.dumps({"reported_total_btc_equivalent":".09","reference_as_of":T1,
            "declared_on":"2026-01-11","balance_scope":wallet.SCOPE,"basis":"synthetic","confirmed_by":"test"}), encoding="utf-8")
        import_opening(self.project,declaration)
        completed={**pending,"ORDER_STATUS":"Completed","PAYIN_STATUS":"Completed","PAYOUT_STATUS":"Completed","COMPLETED_AT (UTC)":"2026-01-02T02:00:00Z","SENT_AT (UTC)":"2026-01-02T02:00:00Z"}
        import_bull_orders(self.project,self.orders(self.rows+[extra_fund,completed],"completed.csv"),opening_assumption=ASSUMPTIONS)
        with self.assertRaisesRegex(ValueError,"quantity cannot be valued"):
            self.view()

    def test_database_payload_tampering_is_not_hidden_by_intact_source_file(self):
        b=self.balance()
        with sqlite3.connect(self.project/"data/db/portfolio.sqlite3") as conn:
            value=json.loads(conn.execute("SELECT payload_json FROM wallet_revisions WHERE record_id=?",(b['record_id'],)).fetchone()[0])
            value['quantity_btc']='0.1'
            conn.execute("UPDATE wallet_revisions SET payload_json=? WHERE record_id=?",(json.dumps(value),b['record_id']))
        with self.assertRaisesRegex(ValueError,'corrupt'):
            self.view()

    def test_reference_override_archived_and_retry_does_not_require_original(self):
        path=self.root/'quote.json';path.write_text(json.dumps(quote(T1)), encoding="utf-8")
        request={'btc_balance':'.0799','btc_balance_as_of':T1,'as_of':T1,'price_file':str(path)}
        with patch('wealth_ledger.workflow.resolve_rates',return_value=FX):
            with self.assertRaises(operations.ReportOperationError):
                operations.execute_update(self.project,request,lambda *a:(_ for _ in ()).throw(ValueError('synthetic publisher failed')))
            operation=operations.list_operations(self.project)[0]
            path.unlink()
            accepted=Path(operation['request']['price_file'])
            self.assertTrue(accepted.is_file())
            self.assertTrue(accepted.is_relative_to(self.project/'data/raw/reference'))
            operations.execute_update(self.project,{},lambda *a:{'output':'synthetic'},resume=operation['operation_id'])
        self.assertEqual(len(wallet.records(self.project,'balance')),1)

    def test_no_input_rebuild_uses_successful_pointer_not_failed_future_report(self):
        with patch('wealth_ledger.workflow.resolve_rates',return_value=FX),patch('wealth_ledger.combined.resolve_btc_price',side_effect=lambda p,t,f:quote(t)):
            initial,_=prepare_update(self.project,as_of=T1)
            bundle=self.project/'reports/initial';bundle.mkdir(parents=True)
            (bundle/'data.json').write_text(json.dumps(initial), encoding="utf-8")
            (self.project/'reports/latest.json').write_text(json.dumps({'path':'reports/initial','snapshot_id':None}), encoding="utf-8")
            with self.assertRaises(operations.ReportOperationError):
                operations.execute_update(self.project,{'btc_balance':'.0799','btc_balance_as_of':T2,'as_of':T2},
                    lambda *a:(_ for _ in ()).throw(ValueError('synthetic report failure')))
            regenerated,_=prepare_update(self.project,now=datetime.fromisoformat(NOW))
        self.assertEqual(regenerated['meta']['as_of'],initial['meta']['as_of'])
        self.assertEqual(Decimal(regenerated['crypto']['btc_equivalent_qty']),Decimal('.08'))


if __name__=="__main__":
    unittest.main()
