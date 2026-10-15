"""Synthetic-only regression tests for the Bull Bitcoin acquisition ledger."""
import csv
import hashlib
import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from wealth_ledger.crypto import REQUIRED, import_bull_orders, make_crypto_view


STAGE = Path(__file__).resolve().parents[1]
ASSUMPTIONS = {
    "btc": "0", "lbtc": "0", "cad": "0", "confirmed_by": "synthetic-user",
    "basis": "BTC/LBTC user-confirmed zero; CAD zero is a balanced-export assumption",
    "cad_basis": "inferred_zero_opening_balance",
}
FIELDS = list(REQUIRED) + [
    "ORDER_NUMBER", "ORDER_SUBTYPE", "MESSAGE", "TRANSACTION_ID", "ADDRESS",
    "EXCHANGE_RATE_AMOUNT", "EXCHANGE_RATE_CURRENCY", "INDEX_RATE_AMOUNT", "INDEX_RATE_CURRENCY",
]


def order(identifier, kind="Funding", amount="100", asset="CAD", quantity=None,
          created="2026-01-01T00:00:00Z", completed="2026-01-01T01:00:00Z", status="Completed"):
    return {
        "ORDER_ID": identifier, "ORDER_TYPE": kind, "PAYIN_AMOUNT": amount, "PAYIN_CURRENCY": "CAD",
        "PAYOUT_AMOUNT": quantity or amount, "PAYOUT_CURRENCY": asset,
        "PAYIN_METHOD": "CAD Balance" if kind == "Buy Bitcoin" else "Interac e-Transfer (CAD)",
        "PAYOUT_METHOD": "Bitcoin On-Chain" if asset == "BTC" else "Liquid Network" if asset == "LBTC" else "CAD Balance",
        "ORDER_STATUS": status, "PAYIN_STATUS": status, "PAYOUT_STATUS": status,
        "CREATED_AT (UTC)": created, "COMPLETED_AT (UTC)": completed,
        "SENT_AT (UTC)": completed, "ORDER_NUMBER": "private-order-number",
        "ORDER_SUBTYPE": "Market Order", "MESSAGE": "private-source-message",
        "TRANSACTION_ID": "private-source-transaction", "ADDRESS": "private-source-address",
        "EXCHANGE_RATE_AMOUNT": ".01" if kind == "Funding" else "100001",
        "EXCHANGE_RATE_CURRENCY": "CAD", "INDEX_RATE_AMOUNT": "99999" if kind == "Buy Bitcoin" else "",
        "INDEX_RATE_CURRENCY": "CAD" if kind == "Buy Bitcoin" else "",
    }


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="crypto-test-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"

    def tearDown(self):
        self.temp.cleanup()

    def csv(self, rows, name="orders.csv"):
        path = self.root / name
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def ingest(self, rows, name="orders.csv", **kwargs):
        return import_bull_orders(self.project, self.csv(rows, name), opening_assumption=ASSUMPTIONS, **kwargs)

    def counts(self):
        with sqlite3.connect(self.project / "data/db/portfolio.sqlite3") as conn:
            return tuple(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in (
                "crypto_sources", "crypto_order_revisions"))

    def view(self, cutoff="2026-12-31T23:59:59Z", **kwargs):
        return make_crypto_view(self.project, cutoff, **kwargs)

    def test_explicit_opening_metadata_required_before_any_writes(self):
        path = self.csv([order("initial")])
        with self.assertRaisesRegex(ValueError, "explicit zero opening"):
            import_bull_orders(self.project, path)
        self.assertFalse(self.project.exists())
        bad = {**ASSUMPTIONS, "btc": "0.1"}
        with self.assertRaisesRegex(ValueError, "explicit zero"):
            import_bull_orders(self.project, path, opening_assumption=bad)
        self.assertFalse(self.project.exists())

    def test_native_totals_cash_networks_raw_preservation_and_privacy(self):
        rows = [order("private-full-order-1", amount="300"),
                order("private-full-order-2", "Buy Bitcoin", "100", "BTC", ".001", completed="2026-01-01T02:00:00Z"),
                order("private-full-order-3", "Buy Bitcoin", "150", "LBTC", ".0015", completed="2026-01-01T03:00:00Z")]
        path = self.csv(rows)
        result = import_bull_orders(self.project, path, opening_assumption=ASSUMPTIONS)
        view = self.view()
        self.assertEqual(view["total_funding_cad"], "300")
        self.assertEqual(view["total_buy_cost_cad"], "250")
        self.assertEqual(view["cash_cad"], "50")
        self.assertEqual(view["qty_btc"], "0.001")
        self.assertEqual(view["qty_lbtc"], "0.0015")
        self.assertEqual(view["btc_equivalent_qty"], "0.0025")
        self.assertEqual({row["network"] for row in view["orders"]}, {None, "bitcoin", "liquid"})
        self.assertEqual(view["monthly"][0]["contribution_cad"], "300")
        self.assertEqual(view["monthly"][0]["buy_cost_cad"], "250")
        archived = self.project / result["source_path"]
        self.assertEqual(archived.read_bytes(), path.read_bytes())
        if os.name == "posix":
            self.assertEqual(archived.stat().st_mode & 0o777, 0o400)
            self.assertEqual((self.project / "data/db/portfolio.sqlite3").stat().st_mode & 0o777, 0o600)
        self.assertTrue(view["source"]["sources"][0]["integrity_ok"])
        rendered = json.dumps(view)
        for private in ("private-full-order-", "private-source-address", "private-source-transaction",
                        "private-source-message", "private-order-number", "ORDER_ID", "ADDRESS", "TRANSACTION_ID"):
            self.assertNotIn(private, rendered)
        self.assertEqual(view["meta"]["quantity_status"], "order_derived_unadjusted_for_wallet_fees")
        self.assertIn("order_derived_quantity", [row["code"] for row in view["issues"]])

    def test_exact_dedup_cumulative_import_and_missing_months(self):
        initial = [order("fund-jan", amount="100"), order("buy-jan", "Buy Bitcoin", "100", "BTC", ".001", completed="2026-01-01T02:00:00Z")]
        self.ingest(initial)
        duplicate = self.ingest(initial)
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(self.counts(), (1, 2))
        cumulative = initial + [order("fund-mar", amount="50", created="2026-03-10T01:00:00Z", completed="2026-03-10T02:00:00Z")]
        result = self.ingest(cumulative, "later.csv")
        self.assertEqual((result["new_orders"], result["unchanged_orders"]), (1, 2))
        self.assertEqual(self.counts(), (2, 3))
        view = self.view()
        self.assertEqual(view["total_funding_cad"], "150")
        self.assertEqual(view["total_buy_cost_cad"], "100")
        self.assertEqual([row["month"] for row in view["monthly"]], ["2026-01", "2026-03"])
        self.assertFalse(view["meta"]["monthly_observations_generated"])
        self.assertFalse(view["coverage"]["absence_outside_range_confirmed"])

    def test_monthly_purchase_price_weights_delivery_and_excludes_funding(self):
        self.ingest([order("fund", amount="1000"),
                     order("btc", "Buy Bitcoin", "100", "BTC", ".001", completed="2026-01-01T02:00:00Z"),
                     order("liquid", "Buy Bitcoin", "600", "LBTC", ".003", completed="2026-01-03T03:00:00Z")])
        self.assertEqual(self.view()["monthly"][0]["average_purchase_price_cad_per_btc"], "175000")
        earlier = self.view("2026-01-02T23:59:59Z")
        self.assertEqual(earlier["monthly"][0]["average_purchase_price_cad_per_btc"], "100000")

    def test_funding_only_month_has_no_purchase_price(self):
        self.ingest([order("only-funding", amount="500")])
        self.assertIsNone(self.view()["monthly"][0]["average_purchase_price_cad_per_btc"])

    def test_semantic_dedup_preserves_distinct_raw_sources(self):
        rows = [order("one"), order("two", amount="25", completed="2026-01-01T02:00:00Z")]
        self.ingest(rows)
        second = self.ingest(list(reversed(rows)), "reordered.csv")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(self.counts(), (2, 2))
        self.assertEqual(len(self.view()["source"]["sources"]), 2)

    def test_pending_revision_and_old_export_do_not_revert_completion(self):
        pending = order("progress", status="Pending", completed="")
        self.ingest([pending], "pending.csv")
        self.assertEqual(self.view()["total_funding_cad"], "0")
        self.assertEqual(self.view()["meta"]["pending_order_count"], 1)
        completed = order("progress")
        result = self.ingest([completed], "completed.csv")
        self.assertEqual((result["status"], result["revised_orders"]), ("revision", 1))
        self.assertEqual(self.counts(), (2, 2))
        self.assertEqual(self.view()["total_funding_cad"], "100")
        self.assertEqual(self.ingest([pending], "pending.csv")["status"], "duplicate")
        pending["ORDER_SUBTYPE"] = "Auto Buy Order"
        before = (self.project / "data/db/portfolio.sqlite3").read_bytes()
        with self.assertRaisesRegex(ValueError, "cannot be changed or reverted"):
            self.ingest([pending], "stale-pending.csv")
        self.assertEqual((self.project / "data/db/portfolio.sqlite3").read_bytes(), before)
        self.assertFalse(any(self.project.rglob("stale-pending.csv")))

    def test_completed_conflict_rejects_whole_batch_before_archive_or_database_write(self):
        self.ingest([order("stable")])
        before = (self.project / "data/db/portfolio.sqlite3").read_bytes()
        rows = [order("new-valid"), order("stable", amount="999")]
        with self.assertRaisesRegex(ValueError, "Completed order economics"):
            self.ingest(rows, "conflict.csv")
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual((self.project / "data/db/portfolio.sqlite3").read_bytes(), before)
        self.assertFalse(any(self.project.rglob("conflict.csv")))

    def test_same_batch_conflicting_ids_reject_and_identical_ids_dedup(self):
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate order ID"):
            self.ingest([order("same"), order("same", amount="101")])
        self.assertFalse(self.project.exists())
        result = self.ingest([order("same"), order("same")])
        self.assertEqual((result["new_orders"], result["duplicate_rows"]), (1, 1))
        self.assertEqual(self.view()["total_funding_cad"], "100")

    def test_cutoff_is_inclusive_timezone_aware_and_uses_all_three_statuses(self):
        partial = order("partial", status="Completed", completed="2026-01-01T04:00:00Z")
        partial["PAYOUT_STATUS"] = "Pending"
        self.ingest([order("first"), order("second", amount="20", completed="2026-01-01T02:00:00Z"), partial])
        self.assertEqual(self.view("2025-12-31T19:59:59-05:00")["total_funding_cad"], "0")
        view = self.view("2025-12-31T20:00:00-05:00")
        self.assertEqual(view["total_funding_cad"], "100")
        self.assertEqual(view["meta"]["excluded_after_cutoff_count"], 1)
        self.assertEqual(view["meta"]["pending_order_count"], 1)
        self.assertEqual(self.view()["total_funding_cad"], "120")
        with self.assertRaisesRegex(ValueError, "require a time zone"):
            self.view("2026-01-01T12:00:00")

    def test_unsupported_types_networks_and_funding_fee_are_not_silently_skipped(self):
        for row, message in [
            ({**order("sell"), "ORDER_TYPE": "Sell Bitcoin"}, "Unsupported Bull order type"),
            ({**order("wrong-network", "Buy Bitcoin", "100", "LBTC", ".001"), "PAYOUT_METHOD": "Bitcoin On-Chain"}, "currency/network"),
            ({**order("funding-fee"), "PAYOUT_AMOUNT": "99"}, "fee treatment"),
            (order("too-precise", "Buy Bitcoin", "100", "BTC", ".000000001"), "eight decimal"),
        ]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.ingest([row])
                self.assertFalse(self.project.exists())

    def test_stored_assumptions_are_frozen_and_reused(self):
        self.ingest([order("one")])
        path = self.csv([order("two")], "later.csv")
        import_bull_orders(self.project, path)
        changed = {**ASSUMPTIONS, "basis": "changed retroactively"}
        with self.assertRaisesRegex(ValueError, "cannot be silently changed"):
            import_bull_orders(self.project, path, opening_assumption=changed)
        self.assertEqual(self.view()["assumptions"], ASSUMPTIONS)

    def test_namespace_separation_and_existing_wealthsimple_tables_are_untouched(self):
        db = self.project / "data/db/portfolio.sqlite3"
        db.parent.mkdir(parents=True)
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY, as_of TEXT)")
            conn.execute("INSERT INTO snapshots VALUES(1,'frozen-wealthsimple-baseline')")
        first = self.ingest([order("account-a-order")], source_account="account-a")
        second = self.ingest([order("account-b-order")], "second.csv", source_account="account-b")
        self.assertNotEqual(first["account_id"], second["account_id"])
        self.assertEqual(self.view(source_account="account-a")["total_funding_cad"], "100")
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute("SELECT * FROM snapshots").fetchall(), [(1, "frozen-wealthsimple-baseline")])

    def test_negative_cash_and_source_integrity_are_flagged_without_invented_adjustments(self):
        result = self.ingest([order("buy-only", "Buy Bitcoin", "100", "BTC", ".001")])
        view = self.view()
        self.assertEqual(view["cash_cad"], "-100")
        self.assertIn("negative_cash_ledger", [row["code"] for row in view["issues"]])
        archive = self.project / result["source_path"]
        archive.chmod(0o600)
        archive.write_bytes(b"corrupt synthetic source")
        view = self.view()
        self.assertFalse(view["source"]["sources"][0]["integrity_ok"])
        self.assertIn("crypto_source_integrity", [row["code"] for row in view["issues"]])
        self.assertEqual(view["qty_btc"], "0.001")


if __name__ == "__main__":
    unittest.main()
