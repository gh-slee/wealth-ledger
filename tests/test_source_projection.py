"""Source-neutral internal projections using disposable, synthetic ledgers only."""
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D, localcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_source_v2 import ACCOUNT, META, POSITION, AT, RAW, CONTEXT, CAD, BTC, LBTC, batch, funding, purchase
from wealth_ledger import source_ingestion as store, source_v2 as v2
from wealth_ledger.source_protocol import AccountKey, CryptoLeg, Money, RecordKey
from wealth_ledger.source_projection import ProjectionError, project_sources
from wealth_ledger.workspace import resolve_workspace

START = AT - timedelta(days=30)
FX = {"usd_cad": "1.25", "usd_twd": "30", "usd_cad_date": "2024-01-30", "usd_twd_date": "2024-01-30",
      "usd_cad_source": "synthetic-fixed", "usd_twd_source": "synthetic-fixed"}


def hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


class SourceProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="synthetic-projection-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "ledger"
        self.root.mkdir()
        self.env = patch("wealth_ledger.source_ingestion.environment_fingerprint", return_value="a" * 64)
        self.env.start()
        self.addCleanup(self.env.stop)

    def commit(self, value=None, *, raw=RAW, bindings=None):
        value = batch() if value is None else value
        selected = tuple(store.new_binding(account.key) for account in value.accounts) if bindings is None else bindings
        plan = store.prepare_ingestion(self.root, (store.SourceInput(value, raw),), bindings=selected)
        return store.commit_ingestion(resolve_workspace(explicit=self.root), plan)

    def model(self, **kwargs):
        return project_sources(self.root, as_of=kwargs.pop("as_of", AT), period_start=kwargs.pop("period_start", START), **kwargs)

    def observation(self, records, *, at, name, status="partial", accounts=(META,)):
        records = tuple(replace(record, as_of=at, observation_id=name) for record in records)
        snapshot = v2.Snapshot(name, "r1", at, tuple(account.key for account in accounts))
        coverage = tuple(v2.Coverage("holdings", account.key, at, at, status, "Explicit synthetic observation",
                                    "observed-positions", "r1", observation_id=name) for account in accounts)
        return batch(records, accounts=accounts, snapshots=(snapshot,), coverage=coverage)

    def test_empty_model_never_initializes_or_guesses_a_zero_portfolio(self):
        result = self.model()
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["observed_values"], {unit: None for unit in ("CAD", "USD", "TWD")})
        self.assertEqual(hashes(self.root), {})
        self.assertIsNone(result["complete_portfolio_values"])
        self.assertFalse(result["report_projection_ready"])

    def test_observed_values_native_cad_cost_and_missing_source_fields_stay_separate(self):
        position = replace(POSITION, asset=replace(POSITION.asset, currency="USD"),
                           market_value=Money(D(125), "USD"), unit_price=None,
                           cost_native=Money(D(90), "USD"), cost_cad=Money(D("111.11"), "CAD"),
                           unrealized=None, source_fields=(("raw_private_note", "DO-NOT-PROJECT-AUDIT"),))
        self.commit(batch((position,)))
        before = hashes(self.root)
        result = self.model(fx=FX)
        row = result["positions"][0]
        self.assertEqual(row["market_values"], {"CAD": "156.25", "USD": "125", "TWD": "3750"})
        self.assertEqual(row["cost_cad"], "111.11")
        self.assertEqual(row["calculated_unrealized_native"], "35")
        self.assertIsNone(row["source_unrealized"])
        self.assertIsNone(row["unit_price"])
        self.assertNotIn("DO-NOT-PROJECT-AUDIT", json.dumps(result))
        self.assertEqual(hashes(self.root), before)
        self.assertEqual(self.model(fx=FX), result)
        self.assertIsNone(result["complete_portfolio_values"])

    def test_explicit_zero_cost_differs_from_unknown_cost_and_missing_fx(self):
        unknown = replace(POSITION, cost_native=None, cost_cad=None, unrealized=None)
        zero = replace(unknown, key=replace(unknown.key, source_id="zero-cost"), cost_native=Money(D(0), "CAD"))
        self.commit(batch((unknown, zero)))
        rows = {row["source_id"]: row for row in self.model()["positions"]}
        self.assertIsNone(rows["position-001"]["calculated_unrealized_native"])
        self.assertEqual(rows["zero-cost"]["calculated_unrealized_native"], "125.00")
        self.assertIsNone(rows["position-001"]["market_values"]["USD"])
        self.assertIsNone(rows["zero-cost"]["cost_cad"])

    def test_results_are_independent_of_the_process_decimal_precision(self):
        position = replace(POSITION, market_value=Money(D("123456789012345678901234567890.123456789"), "CAD"))
        self.commit(batch((position, purchase())))
        expected = self.model(fx=FX)
        with localcontext() as context:
            context.prec = 6
            context.rounding = "ROUND_DOWN"
            context.Emax = 9
            self.assertEqual(self.model(fx=FX), expected)

    def test_invalid_or_future_fx_and_naive_times_are_rejected_without_writes(self):
        invalid = [dict(FX, usd_cad=1.25), dict(FX, usd_cad="NaN"), dict(FX, usd_cad="0"),
                   dict(FX, usd_cad_date="2024-02-02"), {}]
        for fx in invalid:
            with self.subTest(fx=fx), self.assertRaises(ProjectionError):
                self.model(fx=fx)
        for kwargs in ({"as_of": "2024-01-31"}, {"period_start": AT}, {"as_of": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ProjectionError):
                self.model(**kwargs)
        self.assertEqual(hashes(self.root), {})

    def test_latest_per_account_observations_are_not_summed_as_current_assets(self):
        self.commit()
        later = AT + timedelta(days=45)
        self.commit(self.observation((replace(POSITION, market_value=Money(D(150), "CAD")),), at=later, name="march"))
        result = self.model(as_of=later + timedelta(days=2))
        self.assertEqual(len(result["positions"]), 1)
        self.assertEqual(result["positions"][0]["market_native"], "150")
        self.assertTrue(result["accounts"][0]["carried"])
        self.assertEqual(result["accounts"][0]["observed_as_of"], later.isoformat())
        old = self.model()
        self.assertEqual(old["positions"][0]["market_native"], "125.00")
        self.assertFalse(old["history_replay_ready"])

    def test_future_only_account_does_not_become_a_zero_observation(self):
        self.commit(self.observation((POSITION,), at=AT + timedelta(days=2), name="future"))
        result = self.model()
        self.assertEqual(result["positions"], [])
        self.assertIsNone(result["accounts"][0]["observed_as_of"])
        self.assertIsNone(result["accounts"][0]["observed_values"]["CAD"])

    def test_partial_omissions_are_gaps_and_complete_empty_snapshots_clear_them(self):
        self.commit()
        empty = self.observation((), at=AT + timedelta(days=1), name="partial-empty")
        self.commit(empty)
        result = self.model(as_of=AT + timedelta(days=1))
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["observed_values"]["CAD"], "0")
        self.assertEqual(result["accounts"][0]["unobserved_prior_assets"][0]["symbol"], "DEMO")
        self.assertEqual(result["gaps"][0]["code"], "unobserved_prior_assets")
        self.assertIsNone(result["complete_portfolio_values"])
        self.commit(self.observation((), at=AT + timedelta(days=2), name="complete-empty", status="complete"))
        result = self.model(as_of=AT + timedelta(days=2))
        self.assertEqual(result["accounts"][0]["holdings_coverage"], "complete")
        self.assertEqual(result["gaps"], [])
        self.commit(self.observation((), at=AT + timedelta(days=3), name="another-partial"))
        self.assertEqual(self.model(as_of=AT + timedelta(days=3))["gaps"], [])

    def test_empty_snapshot_needs_coverage_at_its_actual_observation_time(self):
        observation = self.observation((), at=AT, name="empty", status="complete")
        old = replace(observation.coverage[0], start=START, end=START + timedelta(days=1))
        self.commit(replace(observation, coverage=(old,)))
        self.assertEqual(self.model()["accounts"][0]["holdings_coverage"], "unknown")

    def test_extreme_analysis_numbers_fail_closed_without_rounding_or_writes(self):
        self.commit(batch((replace(POSITION, market_value=Money(D("1E+5000"), "CAD")),)))
        before = hashes(self.root)
        with self.assertRaises(ProjectionError) as caught:
            self.model()
        self.assertEqual(caught.exception.code, "projection_numeric_range")
        self.assertEqual(hashes(self.root), before)

    def test_equal_time_distinct_snapshots_require_an_explicit_resolution(self):
        self.commit()
        self.commit(self.observation((POSITION,), at=AT, name="conflicting-observation"))
        with self.assertRaises(ProjectionError) as caught:
            self.model()
        self.assertEqual(caught.exception.code, "ambiguous_projection_observation")

    def test_corrected_partial_snapshot_never_resurrects_superseded_members(self):
        other = replace(POSITION, key=replace(POSITION.key, source_id="old-member"),
                        asset=replace(POSITION.asset, symbol="OLD"))
        self.commit(batch((POSITION, other)))
        correction = replace(POSITION, key=replace(POSITION.key, revision="r2", supersedes_revision="r1", change="correction"),
                             revision_reason="Synthetic correction")
        self.commit(batch((correction,)))
        self.commit(batch((POSITION, other)))
        result = self.model()
        self.assertEqual([row["source_id"] for row in result["positions"]], [POSITION.key.source_id])
        self.assertEqual(result["gaps"], [])

    def test_purchase_spend_unclassified_funding_and_linked_cash_do_not_double_contributions(self):
        linked = v2.CashFlow(replace(POSITION.key, source_id="linked-cash"), AT, "transfer", "out", Money(D(100), "CAD"),
                             "completed", "internal", "purchase-link",
                             cash_leg_of=v2.Reference(ACCOUNT, "crypto_transactions", "purchase-001"))
        self.commit(batch((funding(), purchase(), linked)))
        result = self.model()
        flows = result["cash_flows"]
        self.assertEqual(flows["known_external_net_native"], {"CAD": "0", "USD": "0"})
        self.assertEqual(flows["unresolved_count"], 1)
        self.assertEqual({row["classification"] for row in flows["records"]}, {"unclassified_funding", "purchase_cash_leg"})
        cash = [row for row in result["movements"]["changes"] if row["asset"]["kind"] == "cash"]
        self.assertEqual(D(cash[0]["quantity_change"]), D(0))
        self.assertIsNone(flows["period_net_external_values"])
        self.assertFalse(flows["performance_ready"])

    def test_external_deposits_withdrawals_income_fees_and_period_boundaries(self):
        deposit = replace(funding(), boundary="external")
        withdrawal = replace(deposit, key=replace(deposit.key, source_id="withdrawal"), type="withdrawal", direction="out", amount=Money(D(25), "CAD"))
        income = replace(deposit, key=replace(deposit.key, source_id="income"), type="income")
        fee = replace(withdrawal, key=replace(withdrawal.key, source_id="fee"), type="fee")
        excluded = replace(deposit, key=replace(deposit.key, source_id="at-start"), occurred_at=START)
        future = replace(deposit, key=replace(deposit.key, source_id="future"), occurred_at=AT + timedelta(days=1))
        self.commit(batch((deposit, withdrawal, income, fee, excluded, future)))
        result = self.model(fx=FX)["cash_flows"]
        self.assertEqual(result["known_external_net_native"]["CAD"], "75.00")
        self.assertEqual(D(result["known_external_net_values"]["USD"]), D(60))
        self.assertEqual(len(result["records"]), 4)
        self.assertFalse(result["period_coverage_complete"])
        self.assertEqual(result["conversion_basis"], "explicit_cutoff_fx_not_historical_cash_flow_fx")

    def test_flow_corrections_and_voids_replace_effects_without_rewriting_history(self):
        original = replace(funding(), boundary="external")
        self.commit(batch((original,)))
        correction = replace(original, key=replace(original.key, revision="r2", supersedes_revision="r1", change="correction"),
                             amount=Money(D(110), "CAD"), revision_reason="Synthetic correction")
        self.commit(batch((correction,)))
        self.commit(batch((original,)))
        self.assertEqual(self.model()["cash_flows"]["known_external_net_native"]["CAD"], "110")
        void = replace(correction, key=replace(correction.key, revision="r3", supersedes_revision="r2", change="void"),
                       status="cancelled", revision_reason="Synthetic cancellation")
        self.commit(batch((void,)))
        result = self.model()
        self.assertEqual(result["cash_flows"]["known_external_net_native"]["CAD"], "0")
        self.assertEqual(result["movements"]["changes"], [])

    def test_cash_flow_coverage_requires_contiguous_complete_intervals(self):
        value = replace(funding(), boundary="external")
        coverage = (v2.Coverage("cash_flows", ACCOUNT, START, AT - timedelta(days=10), "complete", "First interval", "first", "r1"),
                    v2.Coverage("cash_flows", ACCOUNT, AT - timedelta(days=10), AT, "complete", "Second interval", "second", "r1"))
        self.commit(batch((value,), coverage=coverage))
        self.assertTrue(self.model()["cash_flows"]["period_coverage_complete"])
        self.assertIsNone(self.model()["cash_flows"]["period_net_external_values"])
        self.assertFalse(self.model()["cash_flows"]["performance_ready"])

    def test_gap_in_flow_coverage_cannot_establish_zero_missing_activity(self):
        coverage = (v2.Coverage("cash_flows", ACCOUNT, START, AT - timedelta(days=11), "complete", "First interval", "first", "r1"),
                    v2.Coverage("cash_flows", ACCOUNT, AT - timedelta(days=10), AT, "complete", "Second interval", "second", "r1"))
        self.commit(batch((replace(funding(), boundary="external"),), coverage=coverage))
        self.assertFalse(self.model()["cash_flows"]["period_coverage_complete"])

    def test_pending_events_and_future_purchases_have_no_active_effects(self):
        pending = replace(purchase(), status="pending", type="sale")
        future = replace(purchase(), key=replace(purchase().key, source_id="future"), occurred_at=AT + timedelta(days=1))
        self.commit(batch((pending, future)))
        result = self.model()
        self.assertEqual(result["movements"]["changes"], [])
        self.assertEqual(result["movements"]["purchases"], [])

    def test_transfer_counterparts_after_cutoff_remain_unresolved_for_that_cutoff(self):
        other = AccountKey("synthetic", "account-002")
        first = v2.CashFlow(replace(POSITION.key, source_id="transfer-out"), AT, "transfer", "out", Money(D(50), "CAD"),
                            "completed", "internal", "link", v2.Reference(other, "cash_flows", "transfer-in"))
        second = replace(first, key=RecordKey(other, "transfer-in", "r1"), direction="in", occurred_at=AT + timedelta(days=1),
                         counterpart=v2.Reference(ACCOUNT, "cash_flows", "transfer-out"))
        accounts = (META, replace(META, key=other, masked_identifier="****0002"))
        self.commit(batch((first, second), accounts=accounts))
        self.assertEqual(self.model()["cash_flows"]["unresolved_count"], 1)
        later = self.model(as_of=AT + timedelta(days=1))["cash_flows"]
        self.assertEqual(later["unresolved_count"], 0)
        self.assertEqual({row["classification"] for row in later["records"]}, {"internal_transfer"})
        self.assertEqual(later["known_external_net_native"]["CAD"], "0")

    def test_linked_purchase_after_cutoff_is_not_a_completed_cash_pair_yet(self):
        cash = v2.CashFlow(replace(POSITION.key, source_id="purchase-cash"), AT, "transfer", "out", Money(D(100), "CAD"),
                           "completed", "internal", "link", cash_leg_of=v2.Reference(ACCOUNT, "crypto_transactions", "purchase-001"))
        event = replace(purchase(), occurred_at=AT + timedelta(days=1))
        self.commit(batch((cash, event)))
        result = self.model()["cash_flows"]
        self.assertEqual(result["records"][0]["classification"], "unresolved_purchase_cash_leg")
        self.assertEqual(result["unresolved_count"], 1)

    def test_crypto_networks_known_fees_and_purchase_rates_preserve_movement_semantics(self):
        bitcoin = purchase(fees=(v2.Fee(ACCOUNT, CAD, D(1), False, False),))
        liquid = replace(purchase(fees=()), key=replace(purchase().key, source_id="liquid-purchase"),
                         legs=(CryptoLeg(ACCOUNT, CAD, D(-100)), CryptoLeg(ACCOUNT, LBTC, D("0.00100000"))))
        self.commit(batch((bitcoin, liquid)))
        result = self.model()["movements"]
        self.assertEqual(D(result["btc_equivalent_change"]), D("0.00200000"))
        self.assertEqual({row["asset"]["network"] for row in result["changes"] if row["asset"]["kind"] == "crypto"}, {"bitcoin", "liquid"})
        self.assertIsNone(result["wallet_balance"])
        self.assertFalse(result["wallet_balance_verified"])
        purchases = {row["source_id"]: row for row in result["purchases"]}
        self.assertEqual(D(purchases["purchase-001"]["all_in_acquisition_cost_cad"]), D(101))
        self.assertEqual(D(purchases["liquid-purchase"]["all_in_acquisition_cost_cad"]), D(100))
        self.assertEqual(D(purchases["purchase-001"]["purchase_rate_cad_per_btc"]), D(100000))

    def test_unknown_fees_or_nonvalued_crypto_fees_do_not_imply_all_in_cost(self):
        event = purchase()
        other = replace(purchase(fees=(v2.Fee(ACCOUNT, BTC, D("0.00000001"), False, False),)),
                        key=replace(event.key, source_id="crypto-fee"))
        included = replace(purchase(fees=(v2.Fee(ACCOUNT, BTC, D("0.00000001"), True, True),)),
                           key=replace(event.key, source_id="included-fee"))
        self.commit(batch((event, other, included)))
        result = self.model()["movements"]
        purchases = {row["source_id"]: row for row in result["purchases"]}
        self.assertIsNone(purchases["purchase-001"]["all_in_acquisition_cost_cad"])
        self.assertIsNone(purchases["crypto-fee"]["all_in_acquisition_cost_cad"])
        self.assertEqual(D(purchases["included-fee"]["all_in_acquisition_cost_cad"]), D(100))
        self.assertEqual(D(purchases["crypto-fee"]["source_leg_quantity"]), D("0.00100000"))
        self.assertEqual(D(purchases["crypto-fee"]["net_recorded_quantity_change"]), D("0.00099999"))
        self.assertEqual(D(purchases["included-fee"]["net_recorded_quantity_change"]), D("0.00100000"))
        self.assertEqual(D(result["btc_equivalent_change"]), D("0.00299999"))

    def test_funding_observations_are_separate_and_cash_changes_are_not_balances(self):
        funding_account = replace(META, role="funding")
        self.commit(batch((POSITION, funding()), accounts=(funding_account,)))
        result = self.model()
        self.assertEqual(result["positions"], [])
        self.assertEqual(len(result["funding_observations"]), 1)
        self.assertIsNone(result["observed_values"]["CAD"])
        self.assertEqual(result["movements"]["changes"][0]["quantity_basis"], "recorded_effects_not_total_balance")

    def test_legacy_bindings_preserve_ids_without_adding_legacy_rows_twice(self):
        from wealth_ledger.core import initialize
        initialize(self.root)
        with closing(sqlite3.connect(self.root / "data/db/portfolio.sqlite3")) as conn:
            conn.execute("INSERT INTO accounts VALUES(?,?,?,?)", ("original-id", "TFSA", "Legacy fixture", "****0001"))
            conn.commit()
        binding = store.Binding(ACCOUNT, "original-id", "legacy_holdings")
        self.commit(bindings=(binding,))
        result = self.model()
        self.assertEqual(result["positions"][0]["account_id"], "original-id")
        self.assertEqual(result["legacy_bindings"], [{"account_id": "original-id", "target_kind": "legacy_holdings"}])
        self.assertFalse(result["legacy_merge_ready"])
        self.assertFalse(result["report_projection_ready"])
        from wealth_ledger.core import make_payload
        with self.assertRaises(store.IngestionError) as caught:
            make_payload(self.root)
        self.assertEqual(caught.exception.code, "report_projection_unavailable")

    def test_legacy_wallet_only_state_is_not_silently_ignored(self):
        from wealth_ledger.core import initialize
        initialize(self.root)
        from wealth_ledger.wallet import add_balance
        add_balance(self.root, "0.00100000", AT.isoformat(), source="synthetic-user-observation", now=CONTEXT.evidence_at.isoformat())
        self.assertTrue(self.model()["legacy_state_present"])
        self.assertIsNone(self.model()["complete_portfolio_values"])

    def test_projection_never_calls_a_parser_and_detects_changed_evidence(self):
        self.commit()
        with patch("wealth_ledger.source_builtin.WealthsimpleHoldings.normalize", side_effect=AssertionError("Parser executed")), \
             patch("wealth_ledger.source_builtin.BullBitcoinOrders.normalize", side_effect=AssertionError("Parser executed")):
            self.model()
        encoded = next((self.root / "data/raw/source-v2").glob("*.csv"))
        encoded.chmod(0o600)
        encoded.write_bytes(b"tampered")
        with self.assertRaises(store.IngestionError):
            self.model()

    def test_concurrent_financial_state_change_rejects_projection(self):
        self.commit()
        with patch("wealth_ledger.source_ingestion.state_fingerprint", side_effect=("a" * 64, "b" * 64)):
            with self.assertRaises(ProjectionError) as caught:
                self.model()
        self.assertEqual(caught.exception.code, "projection_state_changed")

    def test_same_core_supports_another_provider_without_dispatch_changes(self):
        self.commit()
        other_key = AccountKey("another_synthetic", "account-001")
        position = replace(POSITION, key=replace(POSITION.key, account=other_key))
        other = replace(batch((position,), accounts=(replace(META, key=other_key),)),
                        adapter=replace(batch().adapter, provider_id="another_synthetic", adapter_id="another_synthetic.v2"))
        self.commit(other)
        result = self.model()
        self.assertEqual(len(result["positions"]), 2)
        self.assertEqual({row["provider"] for row in result["positions"]}, {"synthetic", "another_synthetic"})
        self.assertEqual(D(result["observed_values"]["CAD"]), D(250))
        self.assertFalse(result["report_projection_ready"])

    def test_built_in_holdings_and_orders_project_without_provider_branches(self):
        from test_source_builtin import fixture, CONTEXT as BUILTIN_CONTEXT
        from wealth_ledger.source_builtin import WealthsimpleHoldings, BullBitcoinOrders, WS_FORMAT, BULL_FORMAT
        from wealth_ledger.source_formats import parse_wealthsimple
        raw = fixture("wealthsimple-holdings.csv")
        holdings = WealthsimpleHoldings().normalize(raw, export_version=WS_FORMAT, context=BUILTIN_CONTEXT)
        self.commit(holdings, raw=raw)
        orders = fixture("bull-orders.csv")
        value = BullBitcoinOrders().normalize(orders, export_version=BULL_FORMAT,
                                             context=replace(BUILTIN_CONTEXT, account_alias="synthetic-bull"))
        self.commit(value, raw=orders)
        result = self.model(as_of=BUILTIN_CONTEXT.evidence_at, period_start="2023-12-31T00:00:00Z", fx=FX)
        old = parse_wealthsimple(raw)[2]
        by_id = {(row["source_account"], row["source_id"]): row for row in result["positions"]}
        for record in old:
            row = by_id[(record["account_id"], record["security_id"])]
            for before, after in (("quantity", "quantity"), ("market_native", "market_native"), ("book_cad", "cost_cad")):
                self.assertEqual(D(row[after]), record[before])
        self.assertGreater(D(result["movements"]["btc_equivalent_change"]), 0)
        self.assertTrue(result["movements"]["purchases"])
        self.assertGreater(result["cash_flows"]["unresolved_count"], 0)
        self.assertFalse(result["report_published"])


if __name__ == "__main__":
    unittest.main()
