"""Synthetic-only tests use isolated system temporary projects."""
import csv
import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from wealth_ledger.core import (initialize, import_holdings, make_payload,
                               import_cash_flows, mark_flow_period)

PROJECT = Path(__file__).resolve().parents[1]
FX = {"usd_cad": "2", "usd_twd": "30", "usd_cad_date": "2026-10-09",
      "usd_twd_date": "2026-10-08", "usd_cad_source": "https://example.test/cad",
      "usd_twd_source": "https://example.test/twd"}
HEADER = ["Account Name", "Account Type", "Account Classification", "Account Number",
          "Symbol", "Exchange", "MIC", "Name", "Security Type", "Quantity",
          "Position Direction", "Market Price", "Market Price Currency", "Book Value (CAD)",
          "Book Value Currency (CAD)", "Book Value (Market)", "Book Value Currency (Market)",
          "Market Value", "Market Value Currency", "Market Unrealized Returns",
          "Market Unrealized Returns Currency"]


def row(account, number, symbol, currency, quantity, price, book, cash=False, book_cad=None):
    quantity, price, book = map(Decimal, (str(quantity), str(price), str(book)))
    market = quantity * price
    return [account, account, "Trade", number, symbol, "" if cash else "TSX" if currency == "CAD" else "NASDAQ",
            "" if cash else "XTSE" if currency == "CAD" else "XNAS", symbol,
            "CURRENCY" if cash else "EXCHANGE_TRADED_FUND" if symbol == "ETF" else "EQUITY",
            str(quantity), "LONG", str(price), currency,
            str(book_cad if book_cad is not None else book * (2 if currency == "USD" else 1)),
            "CAD", str(book), currency, str(market), currency, str(market - book), currency]


def synthetic_rows(tfsa_cash=100, nonregistered_cash=100):
    return [row("TFSA", "SYNTH-TFSA", "ETF", "CAD", 10, 12, 100),
            row("TFSA", "SYNTH-TFSA", "STOCK", "USD", 2, 15, 20),
            row("TFSA", "SYNTH-TFSA", "CAD", "CAD", tfsa_cash, 1, tfsa_cash, True),
            row("TFSA", "SYNTH-TFSA", "USD", "USD", 2, 1, 2, True, 99),
            row("RRSP", "SYNTH-RRSP", "ETF", "CAD", 10, 12, 80),
            row("RRSP", "SYNTH-RRSP", "CAD", "CAD", 100, 1, 100, True),
            row("Non-registered", "SYNTH-NONR", "STOCK", "USD", 3, 15, 24),
            row("Non-registered", "SYNTH-NONR", "CAD", "CAD", nonregistered_cash, 1, nonregistered_cash, True),
            row("Non-registered", "SYNTH-NONR", "USD", "USD", 2, 1, 2, True, 88)]


def write_holdings(path, rows=None, when="2026-10-09 22:28 GMT-04:00"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows if rows is not None else synthetic_rows())
        writer.writerow([])
        writer.writerow(["As of " + when])
    return path


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="core-test-")
        self.project = Path(self.temp.name)
        self.input = self.project / "incoming"
        self.path = write_holdings(self.input / "initial.csv")
        self.first = import_holdings(self.project, self.path, "baseline", FX)

    def tearDown(self):
        self.temp.cleanup()

    def test_native_cash_and_fx(self):
        payload = make_payload(self.project)
        self.assertEqual(payload["totals"]["native_cad"], "540")
        self.assertEqual(payload["totals"]["native_usd"], "79")
        self.assertEqual(payload["totals"]["total_cad"], "698")
        self.assertEqual(payload["totals"]["total_usd"], "349")
        self.assertEqual(payload["totals"]["total_twd"], "10470")
        self.assertEqual(payload["totals"]["cash_cad"], "308")
        self.assertEqual(payload["meta"]["security_count"], 2)
        self.assertEqual(payload["meta"]["position_count"], 4)
        self.assertEqual(payload["meta"]["cash_row_count"], 5)
        self.assertEqual(sum(i["code"] == "cash_cad_book_anomaly" for i in payload["issues"]), 2)
        stock = next(s for s in payload["securities"] if s["symbol"] == "STOCK")
        self.assertEqual(stock["quantity"], "5")
        self.assertEqual(stock["avg_cost"], "8.8")
        self.assertEqual(stock["unrealized_native"], "31")
        self.assertNotIn("SYNTH-TFSA", json.dumps(payload))
        self.assertEqual(payload["periods"], [])
        self.assertFalse(payload["changes"]["available"])

    def test_exact_semantic_dedup_and_frozen_fx(self):
        changed_fx = {**FX, "usd_cad": "3"}
        result = import_holdings(self.project, self.path, "interim", changed_fx)
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["snapshot_id"], self.first["snapshot_id"])
        reordered = write_holdings(self.input / "reordered.csv", list(reversed(synthetic_rows())))
        result = import_holdings(self.project, reordered, "baseline", changed_fx)
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(make_payload(self.project)["fx"]["usd_cad"], "2")

    def test_revision_retains_original(self):
        corrected = write_holdings(self.input / "corrected.csv", synthetic_rows(tfsa_cash=101))
        result = import_holdings(self.project, corrected, "interim", FX)
        self.assertEqual(result["status"], "revision")
        self.assertEqual(result["revision"], 2)
        self.assertEqual(make_payload(self.project)["totals"]["total_cad"], "699")
        self.assertEqual(make_payload(self.project, self.first["snapshot_id"])["totals"]["total_cad"], "698")
        self.assertEqual(len(make_payload(self.project)["history"]), 1)
        archive = self.project / self.first["source_path"]
        self.assertEqual(archive.read_bytes(), self.path.read_bytes())

    def test_future_comparison_and_missing_account(self):
        future = write_holdings(self.input / "november.csv", synthetic_rows(tfsa_cash=110), "2026-11-09 22:28 GMT-05:00")
        import_holdings(self.project, future, "monthly", {**FX, "usd_cad": "3"})
        payload = make_payload(self.project)
        self.assertTrue(payload["changes"]["available"])
        self.assertEqual(len(payload["history"]), 2)
        self.assertEqual(payload["history"][0]["totals"]["total_cad"], "698")
        self.assertEqual(payload["periods"][0]["status"], "not_provided")
        missing = [r for r in synthetic_rows() if r[1] != "RRSP"]
        future = write_holdings(self.input / "december.csv", missing, "2026-12-09 22:28 GMT-05:00")
        result = import_holdings(self.project, future, "monthly", FX)
        self.assertFalse(result["is_complete"])
        self.assertFalse(make_payload(self.project)["changes"]["available"])
        self.assertTrue(make_payload(self.project)["meta"]["missing_account_ids"])

    def write_flows(self, flows):
        path = self.input / "flows.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["flow_id", "date", "account_id", "flow_type", "currency", "amount", "transfer_id"])
            writer.writeheader()
            writer.writerows(flows)
        return path

    def test_contribution_adjustment(self):
        aid = next(a["account_id"] for a in make_payload(self.project)["accounts"] if a["account_type"] == "TFSA")
        future = write_holdings(self.input / "next.csv", synthetic_rows(tfsa_cash=200), "2026-11-09 22:28 GMT-05:00")
        import_holdings(self.project, future, "monthly", FX)
        flows = self.write_flows([{ "flow_id": "deposit-one", "date": "2026-10-20", "account_id": aid, "flow_type": "deposit", "currency": "CAD", "amount": "100"}])
        self.assertEqual(import_cash_flows(self.project, flows)["imported"], 1)
        self.assertEqual(import_cash_flows(self.project, flows)["status"], "duplicate")
        mark_flow_period(self.project, "2026-10-09", "2026-11-09", "complete")
        period = next(p for p in make_payload(self.project)["periods"] if p["scope"] == "portfolio")
        self.assertTrue(period["available"])
        self.assertEqual(period["investment_gain_cad"], "0")
        self.assertEqual(period["modified_dietz"], "0")
        self.assertLess(abs(Decimal(period["xirr"])), Decimal("0.000000001"))

    def test_conflicting_ids_in_new_flow_csv_are_rejected_before_writes(self):
        aid = make_payload(self.project)["accounts"][0]["account_id"]
        first = {"flow_id": "valid-first", "date": "2026-10-20", "account_id": aid,
                 "flow_type": "deposit", "currency": "CAD", "amount": "50"}
        duplicate = {**first, "flow_id": "conflicting", "amount": "100"}
        path = self.write_flows([first, duplicate, {**duplicate, "amount": "200"}])
        db = self.project / "data/db/portfolio.sqlite3"
        before = db.read_bytes()
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate flow ID"):
            import_cash_flows(self.project, path)
        self.assertEqual(db.read_bytes(), before)
        self.assertEqual(list((self.project / "data/raw/activity").rglob("*.csv")), [])
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cash_flows").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)

    def test_identical_ids_in_new_flow_csv_still_deduplicate(self):
        aid = make_payload(self.project)["accounts"][0]["account_id"]
        flow = {"flow_id": "identical", "date": "2026-10-20", "account_id": aid,
                "flow_type": "deposit", "currency": "CAD", "amount": "100"}
        path = self.write_flows([flow, dict(flow)])
        self.assertEqual(import_cash_flows(self.project, path)["imported"], 1)
        with sqlite3.connect(self.project / "data/db/portfolio.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cash_flows").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT amount_cad FROM cash_flows").fetchone()[0], "100")
        self.assertEqual(import_cash_flows(self.project, path)["status"], "duplicate")

    def test_transfers_cancel_and_unmatched_blocks(self):
        accounts = {a["account_type"]: a["account_id"] for a in make_payload(self.project)["accounts"]}
        future = write_holdings(self.input / "next.csv", synthetic_rows(tfsa_cash=50, nonregistered_cash=150), "2026-11-09 22:28 GMT-05:00")
        import_holdings(self.project, future, "monthly", FX)
        outflow = {"flow_id": "transfer-out", "date": "2026-10-20", "account_id": accounts["TFSA"], "flow_type": "transfer_out", "currency": "CAD", "amount": "50", "transfer_id": "pair-one"}
        path = self.write_flows([outflow])
        import_cash_flows(self.project, path)
        mark_flow_period(self.project, "2026-10-09", "2026-11-09", "complete")
        self.assertEqual(make_payload(self.project)["periods"][0]["status"], "unmatched_transfers")
        path = self.write_flows([outflow, {**outflow, "flow_id": "transfer-in", "account_id": accounts["Non-registered"], "flow_type": "transfer_in"}])
        import_cash_flows(self.project, path)
        periods = make_payload(self.project)["periods"]
        self.assertEqual(periods[0]["net_flow_cad"], "0")
        self.assertEqual(periods[0]["investment_gain_cad"], "0")
        account_period = next(p for p in periods if p["account_id"] == accounts["TFSA"])
        self.assertEqual(account_period["net_flow_cad"], "-50")
        self.assertEqual(account_period["investment_gain_cad"], "0")

    def test_confirmed_no_flows_enables_performance(self):
        future = write_holdings(self.input / "next.csv", synthetic_rows(tfsa_cash=110), "2026-11-09 22:28 GMT-05:00")
        import_holdings(self.project, future, "monthly", FX)
        mark_flow_period(self.project, "2026-10-09", "2026-11-09", "no_external")
        period = make_payload(self.project)["periods"][0]
        self.assertEqual(period["investment_gain_cad"], "10")
        self.assertEqual(Decimal(period["modified_dietz"]), Decimal(10) / Decimal(698))
        self.assertGreater(Decimal(period["xirr"]), 0)

    def test_reject_duplicates_bad_currency_and_backfill(self):
        with self.assertRaises(ValueError):
            import_holdings(self.project, write_holdings(self.input / "bad.csv", synthetic_rows() + [synthetic_rows()[0]]), "monthly", FX)
        with self.assertRaises(ValueError):
            import_holdings(self.project, write_holdings(self.input / "early.csv", when="2026-10-08 22:28 GMT-04:00"), "interim", {**FX, "usd_cad_date": "2026-10-08"})
        bad = synthetic_rows()
        bad[0][18] = "TWD"
        with self.assertRaises(ValueError):
            import_holdings(self.project, write_holdings(self.input / "badcurrency.csv", bad), "monthly", FX)

    def test_monthly_and_baseline_comparisons_ignore_interims(self):
        ids = []
        for label, when, kind, balance in [
            ("oct-interim", "2026-10-20 22:28 GMT-04:00", "interim", 110),
            ("oct-month", "2026-10-31 22:28 GMT-04:00", "monthly", 120),
            ("nov-interim", "2026-11-03 22:28 GMT-05:00", "interim", 130),
            ("nov-month", "2026-11-30 22:28 GMT-05:00", "monthly", 140),
        ]:
            path = write_holdings(self.input / (label + ".csv"), synthetic_rows(tfsa_cash=balance), when)
            ids.append(import_holdings(self.project, path, kind, FX)["snapshot_id"])
        payload = make_payload(self.project)
        self.assertEqual(payload["comparisons"]["previous"]["previous_snapshot_id"], ids[2])
        self.assertEqual(payload["comparisons"]["previous_month"]["previous_snapshot_id"], ids[1])
        self.assertEqual(payload["comparisons"]["baseline"]["previous_snapshot_id"], self.first["snapshot_id"])
        self.assertEqual(payload["meta"]["official_snapshot_ids"], [ids[1], ids[3]])

    def test_modified_dietz_weights_midperiod_flow(self):
        aid = next(a["account_id"] for a in make_payload(self.project)["accounts"] if a["account_type"] == "TFSA")
        future = write_holdings(self.input / "next.csv", synthetic_rows(tfsa_cash=210), "2026-11-09 22:28 GMT-05:00")
        import_holdings(self.project, future, "monthly", FX)
        path = self.write_flows([{ "flow_id": "weighted", "date": "2026-10-20", "account_id": aid, "flow_type": "deposit", "currency": "CAD", "amount": "100"}])
        import_cash_flows(self.project, path)
        mark_flow_period(self.project, "2026-10-09", "2026-11-09", "complete")
        payload = make_payload(self.project)
        period = payload["periods"][0]
        expected = Decimal(10) / (Decimal(698) + Decimal(100) * Decimal(20) / Decimal(31))
        self.assertEqual(Decimal(period["modified_dietz"]), expected)
        self.assertEqual(period["investment_gain_cad"], "10")
        self.assertTrue(payload["cash_flows"][0]["source_path"].startswith("data/raw/activity/"))

    def test_zero_cost_quantity_and_source_integrity(self):
        rows = synthetic_rows()
        rows[0] = row("TFSA", "SYNTH-TFSA", "ETF", "CAD", 0, 12, 0)
        correction = write_holdings(self.input / "zero.csv", rows)
        result = import_holdings(self.project, correction, "baseline", FX)
        payload = make_payload(self.project)
        position = next(p for p in payload["positions"] if p["account_type"] == "TFSA" and p["symbol"] == "ETF")
        self.assertIsNone(position["avg_cost"])
        self.assertIsNone(position["unrealized_pct"])
        archive = self.project / result["source_path"]
        archive.chmod(0o600)
        archive.write_text("tampered synthetic input", encoding="utf-8")
        payload = make_payload(self.project)
        self.assertFalse(payload["source"]["integrity_ok"])
        self.assertTrue(any(i["code"] == "source_integrity" for i in payload["issues"]))

    def test_no_external_conflicts_and_internal_income(self):
        aid = next(a["account_id"] for a in make_payload(self.project)["accounts"] if a["account_type"] == "TFSA")
        future = write_holdings(self.input / "next.csv", synthetic_rows(tfsa_cash=110), "2026-11-09 22:28 GMT-05:00")
        import_holdings(self.project, future, "monthly", FX)
        path = self.write_flows([{ "flow_id": "income", "date": "2026-10-20", "account_id": aid, "flow_type": "income", "currency": "CAD", "amount": "10"}])
        import_cash_flows(self.project, path)
        mark_flow_period(self.project, "2026-10-09", "2026-11-09", "no_external")
        self.assertEqual(make_payload(self.project)["periods"][0]["investment_gain_cad"], "10")
        path = self.write_flows([{ "flow_id": "deposit", "date": "2026-10-20", "account_id": aid, "flow_type": "deposit", "currency": "CAD", "amount": "10"}])
        import_cash_flows(self.project, path)
        period = make_payload(self.project)["periods"][0]
        self.assertFalse(period["available"])
        self.assertEqual(period["status"], "no_external_conflicts_with_flows")

    def test_global_no_external_allows_paired_account_transfers(self):
        accounts = {a["account_type"]: a["account_id"] for a in make_payload(self.project)["accounts"]}
        future = write_holdings(self.input / "next.csv", synthetic_rows(tfsa_cash=50, nonregistered_cash=150), "2026-11-09 22:28 GMT-05:00")
        import_holdings(self.project, future, "monthly", FX)
        transfer = {"date": "2026-10-20", "currency": "CAD", "amount": "50", "transfer_id": "pair-one"}
        path = self.write_flows([
            {**transfer, "flow_id": "transfer-out", "account_id": accounts["TFSA"], "flow_type": "transfer_out"},
            {**transfer, "flow_id": "transfer-in", "account_id": accounts["Non-registered"], "flow_type": "transfer_in"},
        ])
        import_cash_flows(self.project, path)
        mark_flow_period(self.project, "2026-10-09", "2026-11-09", "no_external")
        periods = make_payload(self.project)["periods"]
        self.assertTrue(periods[0]["available"])
        self.assertEqual(periods[0]["net_flow_cad"], "0")
        account = next(p for p in periods if p["account_id"] == accounts["TFSA"])
        self.assertTrue(account["available"])
        self.assertEqual(account["status"], "complete")
        self.assertEqual(account["net_flow_cad"], "-50")
        self.assertEqual(account["investment_gain_cad"], "0")
        mark_flow_period(self.project, "2026-10-09", "2026-11-09", "no_external", accounts["TFSA"])
        periods = make_payload(self.project)["periods"]
        self.assertTrue(periods[0]["available"])
        account = next(p for p in periods if p["account_id"] == accounts["TFSA"])
        self.assertEqual(account["status"], "no_external_conflicts_with_flows")

    def test_adjacent_monthly_declarations_support_baseline_with_gaps_and_overrides(self):
        aid = next(a["account_id"] for a in make_payload(self.project)["accounts"] if a["account_type"] == "TFSA")
        first = write_holdings(self.input / "nov.csv", synthetic_rows(tfsa_cash=110), "2026-11-09 22:28 GMT-05:00")
        second = write_holdings(self.input / "dec.csv", synthetic_rows(tfsa_cash=220), "2026-12-09 22:28 GMT-05:00")
        import_holdings(self.project, first, "monthly", FX)
        import_holdings(self.project, second, "monthly", FX)
        path = self.write_flows([{ "flow_id": "deposit", "date": "2026-11-20", "account_id": aid, "flow_type": "deposit", "currency": "CAD", "amount": "100"}])
        import_cash_flows(self.project, path)
        mark_flow_period(self.project, "2026-10-09", "2026-11-09", "no_external")
        mark_flow_period(self.project, "2026-11-10", "2026-12-09", "complete")
        baseline = next(p for p in make_payload(self.project)["periods"] if p["scope"] == "portfolio" and p["start_as_of"].startswith("2026-10-09"))
        self.assertFalse(baseline["available"])
        self.assertEqual(baseline["status"], "not_provided")
        mark_flow_period(self.project, "2026-11-09", "2026-11-10", "no_external")
        baseline = next(p for p in make_payload(self.project)["periods"] if p["scope"] == "portfolio" and p["start_as_of"].startswith("2026-10-09"))
        self.assertTrue(baseline["available"])
        self.assertEqual(baseline["investment_gain_cad"], "20")
        self.assertEqual(baseline["net_flow_cad"], "100")
        mark_flow_period(self.project, "2026-11-15", "2026-11-16", "partial")
        self.assertFalse(make_payload(self.project)["periods"][0]["available"])
        mark_flow_period(self.project, "2026-11-15", "2026-11-16", "complete")
        self.assertTrue(make_payload(self.project)["periods"][0]["available"])


if __name__ == "__main__":
    unittest.main()
