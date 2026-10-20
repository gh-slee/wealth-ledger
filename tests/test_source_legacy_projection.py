"""Synthetic legacy/canonical coexistence, wallet and frozen-evidence acceptance."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D, localcontext
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_source_builtin import fixture, CONTEXT
from test_source_projection import hashes
from wealth_ledger import source_ingestion as store, source_v2 as v2, wallet
from wealth_ledger.core import import_holdings, make_payload, import_cash_flows
from wealth_ledger.crypto import import_bull_orders, make_crypto_view
from wealth_ledger.crypto_opening import import_opening
from wealth_ledger.source_builtin import WealthsimpleHoldings, BullBitcoinOrders, WS_FORMAT, BULL_FORMAT
from wealth_ledger.source_legacy_projection import project_compatible_sources
from wealth_ledger.source_projection import ProjectionError
from wealth_ledger.workspace import resolve_workspace

AT = "2024-03-01T00:00:00Z"
START = "2023-12-31T00:00:00Z"
ALIAS = "bullbitcoin-main"
FX = {"usd_cad": "1.5", "usd_twd": "30", "usd_cad_date": "2024-01-30", "usd_twd_date": "2024-01-30",
      "usd_cad_source": "synthetic-fixed", "usd_twd_source": "synthetic-fixed"}
ASSUMPTIONS = {"btc": "0", "lbtc": "0", "cad": "0", "basis": "Synthetic explicit opening", "confirmed_by": "synthetic-example"}


def quote(as_of=AT):
    stamp = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    return {"provider": "synthetic-fixed", "pair": "BTC-USD", "close": "100000", "as_of": as_of,
            "candle_start": (stamp-timedelta(minutes=1)).isoformat(), "candle_end": stamp.isoformat(),
            "source_url": "https://example.test/synthetic-price"}


class LegacyProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-compatible-");self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve();self.root = self.base/"ledger";self.root.mkdir()
        self.raw = (fixture("wealthsimple-holdings.csv"), fixture("bull-orders.csv"))
        self.paths = (self.base/"holdings.csv", self.base/"orders.csv")
        for path,raw in zip(self.paths,self.raw):path.write_bytes(raw)
        self.environment = patch("wealth_ledger.source_ingestion.environment_fingerprint",return_value="a"*64)
        self.environment.start();self.addCleanup(self.environment.stop)

    def native(self, *, holdings=True, orders=True):
        if holdings:import_holdings(self.root,self.paths[0],"baseline",FX)
        if orders:import_bull_orders(self.root,self.paths[1],opening_assumption=ASSUMPTIONS)

    def ws(self, raw=None):
        raw = self.raw[0] if raw is None else raw
        return WealthsimpleHoldings().normalize(raw,export_version=WS_FORMAT,context=CONTEXT),raw

    def bull(self, raw=None):
        raw = self.raw[1] if raw is None else raw
        return BullBitcoinOrders().normalize(raw,export_version=BULL_FORMAT,context=replace(CONTEXT,account_alias=ALIAS)),raw

    def commit(self, *values, binding_override=None):
        conn=store._open(self.root)
        try:
            accounts=store._rows(conn,"accounts");crypto=store._rows(conn,"crypto_accounts")
            scope_heads={}
            for row in sorted(store._rows(conn,"src_scopes"),key=lambda row:row["id"]):scope_heads[(row["provider"],row["scope_key"])]=row
        finally:
            if conn:conn.close()
        inputs=[];bindings=[]
        for value,raw in values:
            scopes={key:row for provider,key,revision,parent,payload in store._scope_entries(value)
                    if (row:=scope_heads.get((provider,key))) and row["revision"]!=revision}
            membership=replace(value.membership,supersedes_revision=scopes["membership:"+value.membership.scope_id]["revision"]) if "membership:"+value.membership.scope_id in scopes else value.membership
            coverage=[]
            for scope in value.coverage:
                key=store._json(["coverage",scope.account.account_id,scope.kind,scope.scope_id,scope.observation_id])
                coverage.append(replace(scope,supersedes_revision=scopes[key]["revision"]) if key in scopes else scope)
            value=replace(value,membership=membership,coverage=tuple(coverage))
            inputs.append(store.SourceInput(value,raw))
            for account in value.accounts:
                old=next((row for row in accounts if row["account_id"]==account.key.account_id),None)
                old_crypto=next((row for row in crypto if (row["provider"],row["source_account"])==(account.key.provider,account.key.account_id)),None)
                binding=(store.Binding(account.key,old["account_id"],"legacy_holdings") if old else
                         store.Binding(account.key,old_crypto["account_id"],"legacy_crypto") if old_crypto else store.new_binding(account.key))
                bindings.append(binding_override(account,binding) if binding_override else binding)
        plan=store.prepare_ingestion(self.root,tuple(inputs),bindings=tuple(bindings))
        return store.commit_ingestion(resolve_workspace(explicit=self.root),plan)

    def view(self, **kwargs):
        return project_compatible_sources(self.root,as_of=kwargs.pop("as_of",AT),period_start=kwargs.pop("period_start",START),fx=kwargs.pop("fx",FX),**kwargs)

    def new_purchase(self, *, when="2024-02-15T12:01:00Z", source_id="NEW-PURCHASE"):
        rows=list(csv.reader(io.StringIO(self.raw[1].decode())))
        header=rows[0];row=rows[2]
        values={"ORDER_ID":source_id,"PAYIN_AMOUNT":"100","PAYOUT_AMOUNT":"0.001", "CREATED_AT (UTC)":when,
                "COMPLETED_AT (UTC)":when,"SENT_AT (UTC)":when}
        for key,value in values.items():row[header.index(key)]=value
        output=io.StringIO(newline="");writer=csv.writer(output);writer.writerows((header,row))
        return self.bull(output.getvalue().encode())

    def opening(self):
        path=self.base/"opening.json"
        path.write_text(json.dumps({"reported_total_btc_equivalent":"0.008", "reference_as_of":"2024-02-01T00:00:00Z",
            "declared_on":"2024-02-02", "balance_scope":"all_wallets_btc_plus_lbtc", "basis":"Synthetic pre-source quantity", "confirmed_by":"synthetic-example"}))
        return import_opening(self.root,path)

    def test_native_only_view_matches_original_quantities_costs_and_original_ids_readonly(self):
        self.native();original=make_payload(self.root);crypto=make_crypto_view(self.root,AT);before=hashes(self.root)
        result=self.view(btc_price=quote())
        self.assertEqual(D(result["observed_values"]["CAD"]),D(original["totals"]["total_cad"]))
        self.assertEqual(D(result["btc"]["quantity_btc"]),D(crypto["btc_equivalent_qty"]))
        self.assertEqual(set(result["btc"]["legacy_cash_cad_by_account"].values()),{"300"})
        self.assertEqual({row["account_id"] for row in result["positions"]},{row["account_id"] for row in original["positions"]+original["cash_rows"]})
        self.assertTrue(result["legacy_merge_ready"]);self.assertFalse(result["report_projection_ready"])
        self.assertEqual(hashes(self.root),before)

    def test_both_sources_reimported_canonically_have_one_effect_and_funding_balance(self):
        self.native();self.commit(self.ws(),self.bull());before=hashes(self.root)
        result=self.view()
        self.assertEqual(len(result["legacy_overlap"]["holdings"]),3)
        self.assertEqual(len(result["legacy_overlap"]["orders"]),3)
        self.assertEqual(len(result["btc"]["purchases"]),2)
        self.assertEqual(D(result["btc"]["quantity_btc"]),D("0.007"))
        self.assertEqual(set(result["btc"]["legacy_cash_cad_by_account"].values()),{"300"})
        self.assertEqual(len(result["btc"]["funding_records"]),1)
        self.assertEqual(hashes(self.root),before)
        self.assertEqual(result,self.view())

    def test_subset_order_export_preserves_unmatched_old_orders_and_cash(self):
        self.native();self.commit(self.new_purchase())
        result=self.view()
        self.assertEqual(len(result["btc"]["purchases"]),3)
        self.assertEqual(D(result["btc"]["quantity_btc"]),D("0.008"))
        self.assertEqual(set(result["btc"]["legacy_cash_cad_by_account"].values()),{"200"})
        self.assertEqual(len(result["positions"]),6)

    def test_partial_later_holdings_keep_other_accounts_and_flag_omitted_assets(self):
        self.native();raw=self.raw[0];rows=list(csv.reader(io.StringIO(raw.decode())))
        output=io.StringIO(newline="");writer=csv.writer(output)
        writer.writerows((rows[0],rows[1],[],["As of 2024-02-15 17:00 GMT-05:00"]))
        self.commit(self.ws(output.getvalue().encode()))
        result=self.view()
        self.assertEqual(len({row["account_id"] for row in result["positions"]}),3)
        self.assertTrue(result["gaps"])
        self.assertIsNone(result["complete_portfolio_values"])

    def test_same_time_changed_first_canonical_observation_fails_without_ancestor_proof(self):
        self.native();value,raw=self.ws()
        row=value.records[0]
        changed=replace(row,quantity=row.quantity+D(1))
        self.commit((replace(value,records=(changed,*value.records[1:])),raw))
        with self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"legacy_observation_conflict")

    def test_completed_order_cannot_hide_changed_legs_behind_unchanged_lifecycle(self):
        self.native();value,raw=self.bull();index=next(i for i,row in enumerate(value.records) if row.kind=="crypto_transactions")
        records=list(value.records);event=records[index]
        records[index]=replace(event,legs=(replace(event.legs[0],quantity=event.legs[0].quantity-D(1)),event.legs[1]))
        self.commit((replace(value,records=tuple(records)),raw))
        with self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"legacy_completed_order_conflict")

    def test_bypass_of_legacy_binding_is_rejected_not_double_counted(self):
        self.native();self.commit(self.bull(),binding_override=lambda account,binding:store.new_binding(account.key))
        with self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"legacy_binding_required")

    def test_opening_anchor_fee_and_new_purchase_preserve_every_original_link(self):
        self.native();opening=self.opening()
        balance=wallet.add_balance(self.root,"0.0079","2024-02-10T00:00:00Z",now=AT)
        fee=wallet.add_event(self.root,type="fee",quantity_btc="0.0001",occurred_at="2024-02-09T00:00:00Z",source="synthetic-wallet",reference="fee-1",balance_id=balance["record_id"],now=AT)
        self.commit(self.bull());self.commit(self.new_purchase())
        result=self.view()
        self.assertEqual(D(result["btc"]["quantity_btc"]),D("0.0089"))
        self.assertEqual(result["btc"]["opening"]["opening_btc_equivalent_qty"],opening["opening_btc_equivalent_qty"])
        row=result["wallet"]["reconciliations"][0]
        self.assertEqual(row["residual_btc"],"0.00000000")
        self.assertEqual(row["recorded_residual_btc"],"-0.00010000")
        self.assertEqual(row["linked_event_ids"],[fee["record_id"]])
        self.assertEqual(result["wallet"]["anchor"]["record_id"],balance["record_id"])

    def test_backfill_before_opening_reference_flags_overlap_without_changing_anchor(self):
        self.native();self.opening();wallet.add_balance(self.root,"0.008","2024-02-10T00:00:00Z",now=AT)
        self.commit(self.new_purchase(when="2024-01-04T00:00:00Z"))
        result=self.view()
        self.assertEqual(D(result["btc"]["quantity_btc"]),D("0.008"))
        self.assertTrue(result["wallet"]["opening_overlap"])
        self.assertEqual(result["wallet"]["reconciliations"][0]["status"],"ledger_conflict")

    def test_wallet_only_anchor_and_later_source_history_never_add_pre_anchor_buys_again(self):
        wallet.add_balance(self.root,"0.005","2024-02-10T00:00:00Z",now=AT)
        self.commit(self.bull());result=self.view()
        self.assertEqual(D(result["btc"]["quantity_btc"]),D("0.005"))
        self.assertEqual(result["wallet"]["reconciliations"][0]["status"],"expected_unknown")
        self.assertIsNone(result["btc"]["opening"])

    def test_new_canonical_source_never_inherits_a_zero_opening(self):
        self.commit(self.bull());result=self.view()
        self.assertIsNone(result["btc"]["quantity_btc"])
        self.assertTrue(result["btc"]["valuation_blocked"])
        self.assertIsNone(result["btc"]["actual_full_cost_cad"])

    def test_proxy_is_opt_in_uses_deduplicated_purchase_average_and_never_fills_actual_cost(self):
        self.native();wallet.add_balance(self.root,"0.01","2024-02-10T00:00:00Z",now=AT);self.commit(self.bull())
        actual=self.view(btc_price=quote());proxy=self.view(btc_price=quote(),btc_cost_policy="bull_average_proxy")
        self.assertIsNone(actual["btc"]["estimated_full_cost_cad"])
        self.assertEqual(D(proxy["btc"]["proxy_average_cad_per_btc"]),D(100000))
        self.assertEqual(D(proxy["btc"]["estimated_full_cost_cad"]),D(1000))
        self.assertEqual(D(proxy["btc"]["estimated_gain_cad"]),D(500))
        self.assertIsNone(proxy["btc"]["actual_full_cost_cad"])
        self.assertEqual(proxy["wallet"],actual["wallet"])

    def test_no_revaluation_or_invented_months_in_stored_history(self):
        self.native()
        from wealth_ledger.combined import make_combined_payload
        with patch("wealth_ledger.combined.resolve_btc_price",return_value=quote()):
            original=make_combined_payload(self.root,as_of=AT,fx=FX)
        self.commit(self.ws(),self.bull());before=hashes(self.root)
        result=self.view(fx=dict(FX,usd_cad="2"))
        self.assertEqual(result["frozen_combined_observations"][0]["record"]["view"]["totals"],original["totals"])
        self.assertEqual(result["btc"]["scope_account_id"],original["crypto"]["meta"]["account_id"])
        self.assertEqual(len(result["legacy_snapshot_history"]),1)
        self.assertEqual(json.loads(result["legacy_snapshot_history"][0]["fx_json"])["usd_cad"],"1.5")
        self.assertEqual(hashes(self.root),before)

    def test_legacy_cash_flow_keeps_its_original_historical_usd_cad_value(self):
        self.native(orders=False)
        account=make_payload(self.root)["accounts"][0]["account_id"]
        path=self.base/"flows.csv"
        path.write_text("date,account_id,flow_id,flow_type,currency,amount,usd_cad,fx_date,fx_source\n2024-02-10,"+account+",synthetic-flow,deposit,USD,100,1.1,2024-02-09,synthetic-fixed\n")
        import_cash_flows(self.root,path)
        result=self.view(fx=dict(FX,usd_cad="2"))
        self.assertEqual(result["legacy_cash_flows"]["records"][0]["amount_cad"],"110")
        self.assertEqual(result["legacy_cash_flows"]["time_basis"],"source_calendar_date_only")
        self.assertFalse(result["legacy_cash_flows"]["performance_ready"])

    def test_corrupt_archives_fail_before_projecting_or_writing(self):
        self.native();source=next((self.root/"data/raw/holdings").rglob("*.csv"));source.chmod(0o600);source.write_bytes(b"changed")
        before=hashes(self.root)
        with self.assertRaises(ProjectionError):self.view()
        self.assertEqual(hashes(self.root),before)

    def test_future_or_float_reference_price_is_rejected(self):
        self.native()
        for price in (dict(quote(),close=100000.0),dict(quote(),close="NaN"),{},quote("2024-03-02T00:00:00Z")):
            with self.subTest(price=price),self.assertRaises(ValueError):self.view(btc_price=price)

    def test_read_only_projection_does_not_execute_any_source_parser(self):
        self.native();self.commit(self.ws(),self.bull())
        with patch("wealth_ledger.source_formats.parse_bull",side_effect=AssertionError("Parser executed")), patch("wealth_ledger.source_formats.parse_wealthsimple",side_effect=AssertionError("Parser executed")):
            self.view()

    def test_before_any_native_source_is_unknown_instead_of_a_zero_observation(self):
        self.native()
        result=self.view(as_of="2023-12-30T00:00:00Z",period_start="2023-12-01T00:00:00Z",fx=None)
        self.assertEqual(result["positions"],[])
        self.assertIsNone(result["btc"]["quantity_btc"])

    def test_existing_wallet_reconciliation_matches_the_native_wrapper_exactly(self):
        self.native();balance=wallet.add_balance(self.root,"0.0069","2024-02-10T00:00:00Z",now=AT)
        wallet.add_event(self.root,type="fee",quantity_btc="0.0001",occurred_at="2024-02-09T00:00:00Z",
                         source="synthetic-wallet",reference="fee",balance_id=balance["record_id"],now=AT)
        original=wallet.make_crypto_view(self.root,AT)
        self.commit(self.bull());result=self.view()
        self.assertEqual(result["wallet"],original["wallet"])
        self.assertEqual(D(result["btc"]["quantity_btc"]),D(original["btc_equivalent_qty"]))

    def test_generic_third_source_changes_share_global_anchor_without_entering_bull_proxy(self):
        self.native();wallet.add_balance(self.root,"0.007","2024-02-10T00:00:00Z",now=AT)
        from test_source_v2 import batch, purchase, META, RAW
        at=datetime.fromisoformat("2024-02-15T12:00:00+00:00")
        event=purchase()
        event=replace(event,occurred_at=at,legs=(replace(event.legs[0],quantity=D(-500)),event.legs[1]),
                      acquisition_cost=v2.Money(D(500),"CAD"),acquisition_cost_cad=v2.Money(D(500),"CAD"))
        value=batch((event,),accounts=(replace(META,role="crypto"),))
        value=replace(value,evidence=replace(value.evidence,effective_at=at,context=replace(value.evidence.context,evidence_at=CONTEXT.evidence_at)))
        self.commit((value,RAW));result=self.view(btc_cost_policy="bull_average_proxy")
        self.assertEqual(D(result["btc"]["quantity_btc"]),D("0.008"))
        self.assertEqual(len(result["btc"]["purchases"]),3)
        self.assertEqual(D(result["btc"]["proxy_average_cad_per_btc"]),D(100000))
        self.assertIsNone(result["btc"]["actual_full_cost_cad"])

    def test_cash_deficit_is_visible_and_never_clamped_or_invented_as_funding(self):
        self.native();value,raw=self.new_purchase()
        event=value.records[0]
        value=replace(value,records=(replace(event,legs=(replace(event.legs[0],quantity=D(-900)),event.legs[1]),
                                             acquisition_cost=v2.Money(D(900),"CAD"),acquisition_cost_cad=v2.Money(D(900),"CAD")),))
        self.commit((value,raw));result=self.view()
        self.assertEqual(set(result["btc"]["legacy_cash_cad_by_account"].values()),{"-600"})
        self.assertTrue(result["btc"]["cash_valuation_blocked"])

    def test_date_only_flow_respects_the_explicit_report_offset_not_utc_next_day(self):
        self.native(orders=False);account=make_payload(self.root)["accounts"][0]["account_id"]
        path=self.base/"flows.csv"
        path.write_text("date,account_id,flow_type,currency,amount\n2024-02-10,"+account+",deposit,CAD,100\n")
        import_cash_flows(self.root,path)
        result=self.view(as_of="2024-02-09T20:00:00-05:00")
        self.assertEqual(result["legacy_cash_flows"]["records"],[])
        self.assertEqual(result["legacy_cash_flows"]["period_end_date_inclusive"],"2024-02-09")

    def test_concurrent_settings_change_invalidates_the_model(self):
        self.native();original=wallet.records
        def changed(project):
            (self.root/"config").mkdir(exist_ok=True)
            (self.root/"config/local.toml").write_text("[reporting]\nbtc_cost_policy='bull_average_proxy'\n")
            return original(project)
        with patch("wealth_ledger.wallet.records",side_effect=changed),self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"projection_settings_changed")

    def test_concurrent_frozen_history_change_invalidates_the_model(self):
        self.native();original=wallet.records
        def changed(project):
            with sqlite3.connect(self.root/"data/db/portfolio.sqlite3") as conn:
                conn.execute("CREATE TABLE combined_observations(id INTEGER PRIMARY KEY,as_of_utc TEXT,revision INTEGER,payload_json TEXT)")
                conn.execute("INSERT INTO combined_observations VALUES(1,?,1,'{}')",(AT,))
            return original(project)
        with patch("wealth_ledger.wallet.records",side_effect=changed),self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"projection_history_changed")

    def test_decimal_context_does_not_change_reconciliation_or_display_values(self):
        self.native();self.commit(self.bull());expected=self.view(btc_price=quote(),btc_cost_policy="bull_average_proxy")
        with localcontext() as context:
            context.prec=6;context.rounding="ROUND_DOWN";context.Emax=9
            self.assertEqual(self.view(btc_price=quote(),btc_cost_policy="bull_average_proxy"),expected)

    def test_equal_amount_time_but_different_order_id_is_a_distinct_purchase(self):
        self.native();rows=list(csv.reader(io.StringIO(self.raw[1].decode())))
        rows[2][0]="DIFFERENT-SYNTHETIC-ID"
        output=io.StringIO(newline="");csv.writer(output).writerows((rows[0],rows[2]))
        self.commit(self.bull(output.getvalue().encode()));result=self.view()
        self.assertEqual(len(result["btc"]["purchases"]),3)
        self.assertEqual(D(result["btc"]["quantity_btc"]),D("0.011"))

    def test_proven_same_time_correction_keeps_the_original_snapshot_link(self):
        from test_source_builtin import csv_change
        self.native(orders=False);before=make_payload(self.root);original,raw=self.ws();self.commit((original,raw))
        changed_raw=csv_change(raw,((1,"Quantity","11"),(1,"Market Value","220"),(1,"Market Unrealized Returns","40")))
        value,_=self.ws(changed_raw)
        old=original.snapshots[0].revision
        value=replace(value,snapshots=tuple(replace(row,supersedes_revision=old) for row in value.snapshots),
            records=tuple(replace(row,key=replace(row.key,supersedes_revision=old,change="correction"),
                                  revision_reason="Explicit synthetic correction") for row in value.records))
        self.commit((value,changed_raw));result=self.view()
        self.assertEqual(D(result["observed_values"]["CAD"]),D(before["totals"]["total_cad"])+20)
        self.assertEqual({row["legacy_snapshot_id"] for row in result["legacy_overlap"]["holdings"]},{before["meta"]["snapshot_id"]})

    def test_exact_cash_flow_overlap_preserves_historical_fx_without_counting_twice(self):
        from wealth_ledger.source_protocol import RecordKey, Money
        self.native(orders=False);value,raw=self.ws();account=value.accounts[0].key
        path=self.base/"flows.csv"
        path.write_text("date,account_id,flow_id,flow_type,currency,amount,usd_cad,fx_date,fx_source\n2024-02-10,"+account.account_id+",synthetic-flow,deposit,USD,100,1.1,2024-02-09,synthetic-fixed\n")
        import_cash_flows(self.root,path)
        at=datetime.fromisoformat("2024-02-10T12:00:00+00:00")
        flow=v2.CashFlow(RecordKey(account,"synthetic-flow","r1"),at,"deposit","in",Money(D(100),"USD"),"completed","external")
        value=replace(value,adapter=replace(value.adapter,kinds=(*value.adapter.kinds,"cash_flows")),records=(*value.records,flow),
            coverage=(*value.coverage,v2.Coverage("cash_flows",account,at,at,"partial","Synthetic flow rows","flow-rows","r1")))
        self.commit((value,raw));result=self.view()
        self.assertEqual(result["legacy_cash_flows"]["records"],[])
        self.assertEqual(result["legacy_cash_flows"]["canonical_overlap_ids"],["synthetic-flow"])
        self.assertEqual(result["cash_flows"]["records"][0]["historical_amount_cad"],"110")
        self.assertEqual(D(result["legacy_cash_flows"]["known_recorded_external_cad"]),D(110))
        self.assertIsNone(result["legacy_cash_flows"]["full_period_net_external_cad"])

    def test_covered_contribution_dates_require_a_declaration_and_preserve_historical_fx(self):
        from wealth_ledger.core import mark_flow_period
        self.native(orders=False);account=make_payload(self.root)["accounts"][0]["account_id"]
        path=self.base/"flows.csv"
        path.write_text("date,account_id,flow_type,currency,amount,usd_cad,fx_date,fx_source\n2024-02-10,"+account+",deposit,USD,100,1.1,2024-02-09,synthetic-fixed\n")
        import_cash_flows(self.root,path)
        before=self.view()["legacy_cash_flows"]["covered_account_periods"]
        self.assertTrue(all(not row["available"] for row in before))
        mark_flow_period(self.root,"2023-12-31","2024-03-01","complete")
        result=self.view(fx=dict(FX,usd_cad="2"))["legacy_cash_flows"]["covered_account_periods"]
        row=next(row for row in result if row["account_id"]==account)
        self.assertTrue(row["available"]);self.assertEqual(D(row["external_net_cad"]),D(110))
        self.assertFalse(row["performance_ready"])

    def test_funding_only_subset_without_a_proven_cash_link_requires_review(self):
        self.native();rows=list(csv.reader(io.StringIO(self.raw[1].decode())))
        rows[1][0]="NEW-FUNDING-ID"
        output=io.StringIO(newline="");csv.writer(output).writerows((rows[0],rows[1]))
        self.commit(self.bull(output.getvalue().encode()))
        with self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"legacy_cash_binding_required")
        value,raw=self.bull()
        cash=value.accounts[1]
        extra=replace(cash,key=replace(cash.key,account_id=cash.key.account_id+"-alternate"))
        records=list(value.records)
        index=next(i for i,row in enumerate(records) if row.kind=="crypto_transactions")
        event=records[index]
        records[index]=replace(event,legs=(replace(event.legs[0],account=extra.key),event.legs[1]))
        value=replace(value,accounts=(*value.accounts,extra),records=tuple(records),
            membership=replace(value.membership,revision="synthetic-multiple-cash",accounts=(*value.membership.accounts,extra.key)))
        self.commit((value,raw))
        with self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"legacy_cash_binding_ambiguous")

    def test_unsupported_legacy_currency_is_never_silently_treated_as_cad(self):
        self.native(orders=False)
        with sqlite3.connect(self.root/"data/db/portfolio.sqlite3") as conn:
            snapshot,account,security,payload=conn.execute("SELECT snapshot_id,account_id,security_id,payload_json FROM positions LIMIT 1").fetchone()
            row=json.loads(payload);row["currency"]="EUR"
            conn.execute("UPDATE positions SET payload_json=? WHERE snapshot_id=? AND account_id=? AND security_id=?",
                         (json.dumps(row),snapshot,account,security))
        before=hashes(self.root)
        with self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"unsupported_legacy_currency")
        self.assertEqual(hashes(self.root),before)

    def test_same_time_partial_revision_keeps_unknown_accounts_and_rejects_stale_full_replay(self):
        self.native(orders=False);rows=list(csv.reader(io.StringIO(self.raw[0].decode())))
        output=io.StringIO(newline="");csv.writer(output).writerows((rows[0],rows[1],rows[2],[],rows[-1]))
        path=self.base/"same-time-partial.csv";path.write_bytes(output.getvalue().encode())
        import_holdings(self.root,path,"monthly",FX)
        result=self.view()
        self.assertEqual(len([row for row in result["accounts"] if row["role"]=="investment"]),3)
        missing=[row for row in result["accounts"] if row["observed_as_of"] is None]
        self.assertEqual(len(missing),2)
        self.assertTrue(all(row["observed_values"]["CAD"] is None for row in missing))
        self.assertEqual(len(result["legacy_snapshot_history"]),2)
        self.commit(self.ws())
        with self.assertRaises(ProjectionError) as caught:self.view()
        self.assertEqual(caught.exception.code,"legacy_snapshot_replay_conflict")

    def test_original_native_reporting_gate_remains_after_compatibility_projection(self):
        self.native();self.commit(self.bull());self.view()
        with self.assertRaises(store.IngestionError) as caught:make_payload(self.root)
        self.assertEqual(caught.exception.code,"report_projection_unavailable")


if __name__=="__main__":unittest.main()
