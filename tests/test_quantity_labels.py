"""Reported baseline labels must not turn into unsupported wallet verification."""
import unittest
from wealth_ledger.wallet_reports import quantity_basis_label


class QuantityLabelTests(unittest.TestCase):
    def view(self):
        return {"meta": {"as_of": "2026-10-10T17:00:00-04:00"}, "btc_equivalent_qty": "0.08",
                "opening": {"reference_as_of": "2026-10-10T21:00:00+00:00",
                            "reported_total_btc_equivalent": "0.08000000"}}

    def test_same_time_and_quantity_identify_reported_baseline(self):
        self.assertEqual(quantity_basis_label(self.view()), "使用者回報基準總量（期初補登依據）；未獨立核驗")

    def test_later_report_is_an_estimate_not_a_new_reported_balance(self):
        view = self.view();view["meta"]["as_of"] = "2026-11-10T17:00:00-05:00"
        self.assertEqual(quantity_basis_label(view), "使用者回報基準＋已知購入（推估）；未獨立核驗")

    def test_different_quantity_is_not_the_original_reported_total(self):
        view = self.view();view["btc_equivalent_qty"] = "0.09"
        self.assertIn("（推估）", quantity_basis_label(view))

    def test_wallet_anchor_and_later_changes_have_distinct_labels(self):
        view = self.view();view["wallet"] = {"anchor": {"as_of": "2026-10-10T21:00:00+00:00"}}
        self.assertEqual(quantity_basis_label(view), "使用者回報錢包總量；未獨立核驗")
        view["meta"]["as_of"] = "2026-10-11T17:00:00-04:00"
        self.assertEqual(quantity_basis_label(view), "回報餘額＋其後已知淨異動（推估）；未獨立核驗")

    def test_events_without_anchor_and_orders_only_remain_estimates(self):
        view = self.view();view["wallet"] = {"events": [{"type": "fee"}]}
        self.assertEqual(quantity_basis_label(view), "固定期初＋Bull 購入＋已知淨異動（推估）；未獨立核驗")
        view.pop("wallet");view.pop("opening")
        self.assertEqual(quantity_basis_label(view), "已完成 Bull 購入量（推估）；尚無餘額回報")
