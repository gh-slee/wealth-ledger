"""Synthetic source-neutral valuations, frozen history and all report formats."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal as D, localcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_source_legacy_projection as fixtures
from test_source_projection import hashes
from test_source_v2 import batch, META, POSITION, RAW, AT as POSITION_AT
from wealth_ledger import source_v2 as v2, wallet
from wealth_ledger.application import ApplicationService
from wealth_ledger.workspace import resolve_workspace
from wealth_ledger.source_report import make_source_payload
from wealth_ledger.source_valuation import read_observations, read_source_valuation
from wealth_ledger.source_projection import ProjectionError
from wealth_ledger.crypto_opening import import_opening
from wealth_ledger.reporting import generate_reports
from wealth_ledger.workbook import build_workbook, verify_workbook
from wealth_ledger.validation import validate_formula_caches
from wealth_ledger.publishing import verify_ods
from wealth_ledger.report_checks import validate_report_presentation

AT=fixtures.AT
START=fixtures.START
FX=fixtures.FX


class SourceReportTests(unittest.TestCase):
    setUp=fixtures.LegacyProjectionTests.setUp
    native=fixtures.LegacyProjectionTests.native
    commit=fixtures.LegacyProjectionTests.commit
    ws=fixtures.LegacyProjectionTests.ws
    bull=fixtures.LegacyProjectionTests.bull
    new_purchase=fixtures.LegacyProjectionTests.new_purchase
    opening=fixtures.LegacyProjectionTests.opening

    def inputs(self, **changes):
        return {"as_of":AT,"period_start":START,"fx":FX,"generated_at":AT,**changes}

    def service(self):
        return ApplicationService(resolve_workspace(explicit=self.root))

    def payload(self, **changes):
        return self.service().source_payload(**self.inputs(**changes))

    def render(self, payload, name, locale="en-CA"):
        output=self.base/name
        with patch("urllib.request.urlopen",side_effect=AssertionError("No network")),patch("wealth_ledger.prices.urlopen",side_effect=AssertionError("No network")):
            artifacts=generate_reports(payload,output,locale=locale)
            book=build_workbook(payload,output/"portfolio.ods",chart_images=artifacts["charts"],locale=locale)
            self.assertEqual(validate_formula_caches(output/"portfolio.ods")["cache_mismatches"],0)
            verify_ods(output/"portfolio.ods",payload,artifacts["charts"],locale=locale)
            verify_workbook(output/"portfolio.ods",payload["totals"]["total_cad"],locale=locale)
            checks=validate_report_presentation(payload,output,locale=locale)
            self.assertEqual(checks["status"],"passed")
        self.assertGreater((output/"report.pdf").stat().st_size,1000)
        return output,artifacts,book

    def test_empty_payload_is_readonly_and_never_invents_zero_assets(self):
        before=hashes(self.root);value=self.payload()
        self.assertIsNone(value["totals"]["total_cad"])
        self.assertIsNone(value["totals"]["book_native_cad"])
        self.assertIsNone(value["meta"]["full_portfolio_values"])
        self.assertEqual(value["positions"],[])
        self.assertEqual(hashes(self.root),before)
        self.assertEqual(read_observations(self.root),[])

    def test_native_and_canonical_overlap_has_one_value_and_original_identities(self):
        self.native();self.commit(self.ws(),self.bull());before=hashes(self.root)
        value=self.payload(btc_price=fixtures.quote())
        self.assertEqual(D(value["totals"]["total_cad"]),D("2140"))
        self.assertEqual(len(value["positions"]),4)
        self.assertEqual(len(value["cash_rows"]),4)
        self.assertEqual({row["account_id"] for row in value["source_coverage"] if row["role"]=="investment"},
                         {row["account_id"] for row in value["source_projection"]["positions"]})
        self.assertTrue(all(row["source_id"]==row["security_id"] for row in value["positions"] if row["security_type"]!="CRYPTO"))
        self.assertEqual(hashes(self.root),before)

    def test_carried_securities_keep_their_dates_prices_and_source_book_cad(self):
        self.commit(self.ws());value=self.payload()
        for row in value["positions"]:
            source=next(p for p in value["source_projection"]["positions"] if (p["account_id"],p["source_id"])==(row["account_id"],row["source_id"]))
            self.assertEqual(row["observed_as_of"],source["observed_as_of"])
            self.assertLess(datetime.fromisoformat(row["observed_as_of"]),datetime.fromisoformat(AT.replace("Z","+00:00")))
            self.assertEqual(D(row["book_cad"]),D(source["cost_cad"]))
            self.assertEqual(D(row["price"]),D(source["unit_price"]["amount"]))

    def test_missing_btc_price_exposes_quantity_and_unknown_value_without_zero_position(self):
        self.native();self.commit(self.bull());value=self.payload()
        self.assertEqual(D(value["source_crypto"]["quantity_btc"]),D("0.007"))
        self.assertIsNone(value["source_crypto"]["market_values"]["CAD"])
        self.assertFalse(any(row["security_type"]=="CRYPTO" for row in value["positions"]))
        wallet_account=next(row for row in value["accounts"] if row["account_type"]=="BTC")
        self.assertEqual(D(wallet_account["total_cad"]),D(300))
        self.assertEqual(D(value["totals"]["total_cad"]),D("1090"))

    def test_unanchored_canonical_orders_are_not_wallet_assets_or_cash_balances(self):
        self.commit(self.bull());value=self.payload(btc_price=fixtures.quote())
        self.assertIsNone(value["source_crypto"]["quantity_btc"])
        self.assertIsNone(value["totals"]["total_cad"])
        self.assertEqual(value["source_crypto"]["legacy_cash_cad_by_account"],{})
        self.assertEqual(value["positions"],[])
        self.assertEqual(value["cash_rows"],[])

    def test_canonical_observation_prices_only_the_reported_wallet_scope(self):
        self.commit(self.bull());wallet.add_balance(self.root,"0.008",AT,now=AT)
        value=self.payload(btc_price=fixtures.quote())
        self.assertEqual(D(value["totals"]["total_cad"]),D("1200"))
        self.assertEqual(len(value["positions"]),1)
        self.assertIsNone(value["positions"][0]["book_native"])
        self.assertEqual(value["periods"],[])

    def test_proxy_is_opt_in_and_does_not_fill_actual_costs_or_gains(self):
        self.native();self.commit(self.bull());self.opening()
        value=self.payload(btc_price=fixtures.quote())
        self.assertIsNone(value["source_crypto"]["estimated_full_cost_cad"])
        proxy=self.payload(btc_price=fixtures.quote(),btc_cost_policy="bull_average_proxy")
        self.assertEqual(D(proxy["source_crypto"]["estimated_full_cost_cad"]),D(800))
        self.assertEqual(D(proxy["source_crypto"]["estimated_gain_cad"]),D(400))
        self.assertEqual(D(proxy["source_crypto"]["estimated_return"]),D("0.5"))
        self.assertIsNone(proxy["source_crypto"]["actual_full_cost_cad"])
        row=next(row for row in proxy["positions"] if row["security_type"]=="CRYPTO")
        self.assertIsNone(row["book_native"]);self.assertIsNone(row["unrealized_native"])

    def test_unknown_security_price_and_cost_remain_null_independently(self):
        position=replace(POSITION,unit_price=None,cost_native=None,cost_cad=None,unrealized=None)
        self.commit((batch((position,)),RAW));value=self.payload();row=value["positions"][0]
        self.assertIsNone(row["price"]);self.assertIsNone(row["book_native"]);self.assertIsNone(row["unrealized_native"])
        self.assertEqual(D(row["market_cad"]),D(125))
        self.assertIsNone(value["securities"][0]["avg_cost"])
        self.assertIsNone(value["securities"][0]["price"])
        self.assertEqual(value["securities"][0]["source_observations"][0]["observed_as_of"],row["observed_as_of"])

    def test_explicit_zero_cost_remains_zero_and_undefined_ratio_is_null(self):
        position=replace(POSITION,cost_native=v2.Money(D(0),"CAD"),unrealized=v2.Money(D(125),"CAD"))
        self.commit((batch((position,)),RAW));row=self.payload()["positions"][0]
        self.assertEqual(D(row["book_native"]),D(0));self.assertEqual(D(row["avg_cost"]),D(0));self.assertIsNone(row["unrealized_pct"])

    def empty_observation(self):
        snapshot=v2.Snapshot("synthetic-empty","r1",POSITION_AT,(META.key,))
        coverage=v2.Coverage("holdings",META.key,POSITION_AT,POSITION_AT,"complete","Explicit empty observation","empty","r1",observation_id=snapshot.source_id)
        self.commit((batch((),snapshots=(snapshot,),coverage=(coverage,)),RAW))

    def test_explicit_empty_observation_is_zero_without_claiming_complete_wealth(self):
        self.empty_observation();value=self.payload()
        self.assertEqual(D(value["totals"]["total_cad"]),D(0))
        self.assertEqual(D(value["accounts"][0]["total_cad"]),D(0))
        self.assertIsNone(value["meta"]["full_portfolio_values"])

    def test_cutoff_before_first_holdings_keeps_account_as_unknown(self):
        self.commit((batch(),RAW));value=self.payload(as_of="2024-01-01T00:00:00Z",period_start="2023-12-01T00:00:00Z",fx={**FX,"usd_cad_date":"2023-12-31","usd_twd_date":"2023-12-31"})
        self.assertIsNone(value["totals"]["total_cad"])
        self.assertIsNone(value["accounts"][0]["total_cad"])
        self.assertEqual(value["positions"],[])

    def test_recorded_external_flow_subtotal_does_not_enable_complete_returns(self):
        from wealth_ledger.core import import_cash_flows
        self.native(orders=False);account=self.payload()["accounts"][0]["account_id"]
        path=self.base/"synthetic-flow.csv";path.write_text("date,account_id,flow_type,currency,amount\n2024-02-10,"+account+",deposit,CAD,100\n")
        import_cash_flows(self.root,path);value=self.payload()
        self.assertEqual(D(value["source_projection"]["legacy_cash_flows"]["known_recorded_external_cad"]),D(100))
        self.assertEqual(value["periods"],[])
        self.assertIsNone(value["source_projection"]["legacy_cash_flows"]["full_period_net_external_cad"])

    def test_frozen_duplicate_is_same_edition_without_inventing_months(self):
        self.commit(self.ws());service=self.service();first=service.source_valuation(self.inputs())
        second=service.source_valuation(self.inputs(generated_at="2024-03-02T00:00:00Z"))
        self.assertEqual(second["status"],"duplicate");self.assertEqual(first["observation_id"],second["observation_id"])
        self.assertEqual(len(read_observations(self.root)),1)
        self.assertEqual(read_source_valuation(self.root,first["observation_id"])["meta"]["generated_at"],"2024-03-01T00:00:00+00:00")
        self.assertFalse((self.root/"reports/latest.json").exists())

    def test_later_valuation_preserves_original_fx_and_gaps_in_calendar(self):
        self.commit(self.ws());service=self.service();first=service.source_valuation(self.inputs())
        original=read_source_valuation(self.root,first["observation_id"])
        changed={**FX,"usd_cad":"3","usd_twd":"40"}
        second=service.source_valuation(self.inputs(as_of="2024-05-15T00:00:00Z",generated_at="2024-05-15T00:00:00Z",fx=changed))
        frozen=read_source_valuation(self.root,second["observation_id"])
        self.assertEqual(len(frozen["history"]),2)
        self.assertEqual([r["as_of"][:10] for r in frozen["history"]],["2024-03-01","2024-05-15"])
        self.assertEqual(frozen["history"][0]["totals"],original["totals"])
        self.assertEqual(read_source_valuation(self.root,first["observation_id"]),original)

    def test_same_time_revision_keeps_old_edition_bytes(self):
        self.commit(self.ws());service=self.service();first=service.source_valuation(self.inputs());old=read_source_valuation(self.root,first["observation_id"])
        second=service.source_valuation(self.inputs(fx={**FX,"usd_cad":"2"}))
        self.assertEqual(second["revision"],2);self.assertEqual(len(read_observations(self.root)),2)
        self.assertEqual(read_source_valuation(self.root,first["observation_id"]),old)
        self.assertEqual(len(read_source_valuation(self.root,second["observation_id"])["history"]),1)

    def test_adding_wallet_scope_starts_separate_history_without_rewriting_prior(self):
        self.commit(self.ws());service=self.service();first=service.source_valuation(self.inputs());old=read_source_valuation(self.root,first["observation_id"])
        self.commit(self.bull());second=service.source_valuation(self.inputs())
        self.assertNotEqual(read_source_valuation(self.root,second["observation_id"])["meta"]["scope_id"],old["meta"]["scope_id"])
        self.assertEqual(read_source_valuation(self.root,first["observation_id"]),old)

    def test_reading_frozen_edition_ignores_current_prices_settings_and_source_parsers(self):
        self.commit(self.ws());result=self.service().source_valuation(self.inputs());original=read_source_valuation(self.root,result["observation_id"])
        (self.root/"config/local.toml").write_text("[reporting]\nlocale='zh-TW'\nbtc_cost_policy='bull_average_proxy'\n")
        with patch("wealth_ledger.source_report.make_source_payload",side_effect=AssertionError("No repricing")),patch("wealth_ledger.source_builtin.WealthsimpleHoldings.normalize",side_effect=AssertionError("No parser")):
            self.assertEqual(read_source_valuation(self.root,result["observation_id"]),original)

    def test_corrupt_frozen_archive_fails_without_revaluation_or_writes(self):
        self.commit(self.ws());self.service().source_valuation(self.inputs())
        path=next((self.root/"data/raw/source-valuations").glob("*.json"));path.chmod(0o600);path.write_bytes(b"invalid")
        before=hashes(self.root)
        with self.assertRaises(ProjectionError):read_source_valuation(self.root,1)
        self.assertEqual(hashes(self.root),before)

    def test_invalid_report_inputs_are_rejected_without_mutation(self):
        self.commit(self.ws());before=hashes(self.root)
        for values in ({"fx":None},{"fx":{**FX,"usd_cad":1.5}},{"generated_at":START},{"kind":"invalid"},{"as_of":"2024-03-01T00:00:00"}):
            with self.subTest(values=values),self.assertRaises(ValueError):self.payload(**values)
        self.assertEqual(hashes(self.root),before)

    def test_failed_staged_valuation_has_no_derived_rows_or_archive_in_live_workspace(self):
        import wealth_ledger.source_valuation as module
        self.commit(self.ws());original=module.freeze_valuation
        def fail(stage,**inputs):original(stage,**inputs);raise RuntimeError("Synthetic interruption")
        with patch.object(module,"freeze_valuation",side_effect=fail),self.assertRaises(RuntimeError):self.service().source_valuation(self.inputs())
        self.assertEqual(read_observations(self.root),[])
        self.assertFalse((self.root/"data/raw/source-valuations").exists())

    def test_atomic_receipt_recovers_without_recomputing_valuation(self):
        self.commit(self.ws());service=self.service();identifier="OP-0123456789abcdef"
        first=service.source_valuation(self.inputs(),operation_id=identifier)
        with patch("wealth_ledger.source_valuation.freeze_valuation",side_effect=AssertionError("No repeated action")):
            self.assertEqual(service.source_valuation(self.inputs(),operation_id=identifier),first)
        self.assertEqual(len(read_observations(self.root)),1)

    def test_preview_fingerprint_invalidates_after_canonical_input_change(self):
        from wealth_ledger.operations import input_fingerprint
        self.commit(self.ws());before=input_fingerprint(self.root);self.commit(self.bull())
        with self.assertRaisesRegex(ValueError,"stale"):
            self.service().source_valuation(self.inputs(),expected_fingerprint=before)
        self.assertEqual(read_observations(self.root),[])

    def test_concurrent_configuration_change_rejects_read_model(self):
        import wealth_ledger.source_valuation as module
        self.commit(self.ws());original=module.read_observations
        def changed(project):
            (self.root/"config").mkdir(exist_ok=True);(self.root/"config/local.toml").write_text("[reporting]\nlocale='zh-TW'\n")
            return original(project)
        with patch.object(module,"read_observations",side_effect=changed),self.assertRaisesRegex(ValueError,"inputs_changed"):self.payload()

    def test_decimal_context_is_independent_for_financial_inputs_and_monthly_rates(self):
        self.native();self.commit(self.ws(),self.bull());expected=self.payload(btc_price=fixtures.quote())
        with localcontext() as context:
            context.prec=6;context.rounding="ROUND_DOWN";context.Emax=9
            self.assertEqual(self.payload(btc_price=fixtures.quote()),expected)

    def test_negative_cash_is_disclosed_without_clamping_or_counting_as_assets(self):
        self.native();value,raw=self.new_purchase();event=value.records[0]
        value=replace(value,records=(replace(event,legs=(replace(event.legs[0],quantity=D(-900)),event.legs[1]),acquisition_cost=v2.Money(D(900),"CAD"),acquisition_cost_cad=v2.Money(D(900),"CAD")),))
        self.commit((value,raw));payload=self.payload(btc_price=fixtures.quote())
        self.assertTrue(payload["source_crypto"]["cash_valuation_blocked"])
        self.assertEqual(set(payload["source_crypto"]["legacy_cash_cad_by_account"].values()),{"-600"})
        self.assertFalse(any(row["source_provider"]=="bullbitcoin" for row in payload["cash_rows"]))

    def test_native_report_gate_is_not_removed_by_valuation_record(self):
        from wealth_ledger.source_ingestion import require_report_projection
        self.commit(self.ws());self.service().source_valuation(self.inputs())
        with self.assertRaisesRegex(ValueError,"report_projection_unavailable"):require_report_projection(self.root)

    def test_mixed_source_three_locale_reports_preserve_actual_unknowns_and_wallet_links(self):
        self.native();self.commit(self.ws(),self.bull());self.opening();record=wallet.add_balance(self.root,"0.0079",AT,now=AT)
        wallet.add_event(self.root,type="fee",quantity_btc="0.0001",occurred_at="2024-02-20T00:00:00Z",source="Synthetic wallet",reference="report-fee",balance_id=record["record_id"],now=AT)
        result=self.service().source_valuation(self.inputs(btc_price=fixtures.quote(),btc_cost_policy="bull_average_proxy"))
        payload=read_source_valuation(self.root,result["observation_id"]);before=hashes(self.root)
        for locale in ("en-CA","zh-TW","zh-CN"):
            output,artifacts,book=self.render(payload,"mixed-"+locale,locale)
            self.assertEqual(len(artifacts["charts"]),11)
            self.assertEqual(book["total_cad"],payload["totals"]["total_cad"])
        self.assertEqual(hashes(self.root),before)

    def test_unknown_security_costs_render_without_numeric_zero_or_profit_chart_crash(self):
        position=replace(POSITION,unit_price=None,cost_native=None,cost_cad=None,unrealized=None)
        self.commit((batch((position,)),RAW));self.render(self.payload(),"unknown-cost")

    def test_unknown_wallet_quantity_and_value_render_in_all_three_languages(self):
        self.commit(self.bull());payload=self.payload(btc_price=fixtures.quote())
        for locale in ("en-CA","zh-TW","zh-CN"):
            _,artifacts,book=self.render(payload,"unknown-wallet-"+locale,locale)
            self.assertEqual(len(artifacts["charts"]),10)
            self.assertIsNone(book["total_cad"])

    def test_zero_position_complete_empty_snapshot_renders_valid_ods_and_charts(self):
        self.empty_observation();self.render(self.payload(),"explicit-empty")

    def test_source_report_rendering_rejects_modified_source_amounts(self):
        self.commit((batch(),RAW));payload=self.payload();payload["positions"][0]["market_native"]="999"
        output=self.base/"modified"
        artifacts=generate_reports(payload,output,locale="en-CA");build_workbook(payload,output/"portfolio.ods",chart_images=artifacts["charts"],locale="en-CA")
        with self.assertRaisesRegex(ValueError,"source market_native changed"):
            validate_report_presentation(payload,output,locale="en-CA")

    def test_saved_history_renders_actual_irregular_points_and_original_values(self):
        self.commit(self.ws());service=self.service();service.source_valuation(self.inputs())
        result=service.source_valuation(self.inputs(as_of="2024-05-15T00:00:00Z",generated_at="2024-05-15T00:00:00Z",fx={**FX,"usd_cad":"3"}))
        value=read_source_valuation(self.root,result["observation_id"])
        _,artifacts,_=self.render(value,"irregular-history")
        self.assertIn("09_historical_values",artifacts["charts"])
        self.assertEqual(len(value["history"]),2)

    def test_etf_exposure_and_classification_render_from_explicit_frozen_data(self):
        from wealth_ledger.lookthrough import calculate
        from wealth_ledger.fund_sources import holding
        self.commit(self.ws());value=self.payload()
        funds={row["mic"]+":"+row["symbol"]:{"fund_id":row["mic"]+":"+row["symbol"],"status":"ok","as_of":"2024-01-31",
            "retrieved_at":"2024-02-01T00:00:00Z","issuer":"SYNTHETIC","latest_checked":False,"evidence":[],
            "official_url":"https://example.test/synthetic-holdings","rows":[holding("Synthetic Company",100,ticker="SYN",country="CA",gics_sector="Industrials")]}
            for row in value["securities"] if row["security_type"]=="EXCHANGE_TRADED_FUND"}
        value["lookthrough"]=calculate(value,funds,{"companies":[]},calculated_at=AT);value["lookthrough"].update(run_id=1,mode="synthetic_demo")
        self.assertTrue(value["lookthrough"]["top20"])
        for locale in ("en-CA","zh-TW","zh-CN"):
            output,artifacts,_=self.render(value,"exposure-"+locale,locale)
            self.assertIn("12_company_exposure",artifacts["charts"])
            self.assertIn("13_sector_exposure",artifacts["charts"])
            self.assertTrue((output/"company-exposure.csv").exists())

    def test_source_workbook_generates_its_own_complete_charts_when_not_supplied(self):
        self.commit(self.bull());value=self.payload()
        result=build_workbook(value,self.base/"direct"/"portfolio.ods",locale="en-CA")
        self.assertEqual(result["embedded_charts"],10)
        self.assertIsNone(result["total_cad"])

    def test_known_native_opening_and_unknown_wallet_basis_are_presented_distinctly(self):
        from wealth_ledger.source_presentation import _btc_sections,label
        self.native();value=self.payload()
        section=_btc_sections(value)[0][1];table=section.blocks[0][1]
        self.assertEqual(table.source_values[2,1].value,D(0))
        self.assertEqual(table.rows[2][0],label("opening"))
        self.assertNotEqual(table.rows[1][1],label("unknown"))
