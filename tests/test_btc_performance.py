"""BTC balance changes must not alter the Bull purchase reference average."""
from copy import deepcopy
from decimal import Decimal
import unittest

from wealth_ledger.btc_performance import btc_cost_estimate


class BtcEstimateTests(unittest.TestCase):
    def view(self, quantity="0.08", price="120000"):
        return {"purchased_btc_equivalent_qty": "0.06", "total_buy_cost_cad": "6000",
                "btc_equivalent_qty": quantity, "opening_btc_equivalent_qty": "0.02",
                "valuation": {"market_cad": str(Decimal(quantity)*Decimal(price)),
                              "unit_price_cad": price, "unrealized_cad": None},
                "wallet": {"unresolved_count": 1, "reconciliations": [{"status": "unexplained"}]}}

    def test_higher_lower_balances_keep_average_and_return_but_scale_estimates(self):
        for quantity in ("0.08", "0.09", "0.07"):
            with self.subTest(quantity=quantity):
                view = self.view(quantity); before = deepcopy(view)
                result = btc_cost_estimate(view)
                self.assertEqual(result["average_price_cad_per_btc"], Decimal("100000"))
                self.assertEqual(result["estimated_cost_cad"], Decimal(quantity)*100000)
                self.assertEqual(result["estimated_gain_cad"], Decimal(quantity)*20000)
                self.assertEqual(result["estimated_return"], Decimal("0.2"))
                self.assertEqual(view, before)
                self.assertIsNone(view["valuation"]["unrealized_cad"])

    def test_lower_market_price_keeps_loss_sign_when_quantity_increases(self):
        self.assertEqual(btc_cost_estimate(self.view("0.08", "90000"))["estimated_gain_cad"], Decimal("-800"))
        self.assertEqual(btc_cost_estimate(self.view("0.09", "90000"))["estimated_gain_cad"], Decimal("-900"))

    def test_new_bull_purchase_changes_reference_average(self):
        view = self.view();view.update(purchased_btc_equivalent_qty="0.08", total_buy_cost_cad="10000")
        self.assertEqual(btc_cost_estimate(view)["average_price_cad_per_btc"], Decimal("125000"))

    def test_no_bull_history_does_not_turn_unknown_cost_into_zero(self):
        view = self.view();view.update(purchased_btc_equivalent_qty="0", total_buy_cost_cad="0")
        result = btc_cost_estimate(view)
        for key in ("average_price_cad_per_btc", "estimated_cost_cad", "estimated_gain_cad", "estimated_return"):
            self.assertIsNone(result[key])
        self.assertEqual(result["status"], "no_completed_purchases")

    def test_zero_holdings_with_known_average_have_zero_values_but_no_rate(self):
        result = btc_cost_estimate(self.view("0"))
        self.assertEqual(result["estimated_cost_cad"], 0)
        self.assertEqual(result["estimated_gain_cad"], 0)
        self.assertIsNone(result["estimated_return"])

    def test_quantity_events_do_not_fabricate_actual_costs_or_change_proxy(self):
        view = self.view("0.0799")
        view["wallet"]["events"] = [{"type": "fee", "quantity_btc": "0.0001"}]
        result = btc_cost_estimate(view)
        self.assertEqual(result["average_price_cad_per_btc"], 100000)
        self.assertEqual(result["estimated_cost_cad"], 7990)
        self.assertEqual(result["estimated_gain_cad"], 1598)
        self.assertIsNone(view["valuation"]["unrealized_cad"])

    def test_missing_price_still_has_estimated_cost_but_no_gain(self):
        view = self.view();view.pop("valuation")
        result = btc_cost_estimate(view)
        self.assertEqual(result["estimated_cost_cad"], 8000)
        self.assertIsNone(result["estimated_gain_cad"])
        self.assertEqual(result["status"], "no_valuation")
