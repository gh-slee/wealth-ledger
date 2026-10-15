"""Combined history must not double-count funding or rewrite the broker baseline."""
import csv
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wealth_ledger.core import import_holdings,make_payload
from wealth_ledger.crypto import import_bull_orders
from wealth_ledger.combined import make_combined_payload
from wealth_ledger.reporting import generate_reports
from wealth_ledger.workbook import build_workbook, verify_workbook
from wealth_ledger.validation import validate_formula_caches
from test_core import FX,write_holdings
from test_crypto import FIELDS,ASSUMPTIONS,order


def quote(as_of):
    from datetime import timedelta
    from wealth_ledger.prices import parse_time
    stamp=parse_time(as_of)
    return {"provider":"offline-test","pair":"BTC-USD","as_of":as_of,"close":"100000",
            "candle_start":(stamp-timedelta(minutes=1)).isoformat(),"candle_end":stamp.isoformat(),
            "source_url":"https://example.test/quote","evidence_sha256":"synthetic-public-evidence"}


class CombinedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root / "config").mkdir(parents=True)
        (self.root / "config/local.toml").write_text("[reporting]\nbtc_cost_policy = 'bull_average_proxy'\n", encoding="utf-8")
        self.ws=write_holdings(self.root/"incoming/ws.csv")
        self.first=import_holdings(self.root,self.ws,"baseline",FX)
        path=self.root/"incoming/bull.csv"
        with path.open("w",newline="", encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,FIELDS);writer.writeheader()
            writer.writerows([order("fund",amount="300"),
              order("buy1","Buy Bitcoin","100","BTC",".001",completed="2026-01-01T02:00:00Z"),
              order("buy2","Buy Bitcoin","150","LBTC",".0015",completed="2026-01-01T03:00:00Z")])
        import_bull_orders(self.root,path,opening_assumption=ASSUMPTIONS)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self,as_of=None):
        effective=as_of or make_payload(self.root)["meta"]["as_of"]
        with patch("wealth_ledger.combined.resolve_btc_price",return_value=quote(effective)):
            return make_combined_payload(self.root,as_of=as_of)

    def test_combined_totals_include_quantity_and_remaining_cash_once(self):
        result=self.payload()
        self.assertEqual(result["crypto"]["btc_equivalent_qty"],"0.0025")
        self.assertEqual(result["crypto"]["valuation"]["market_cad"],"500")
        self.assertEqual(result["totals"]["total_cad"],"1248")
        self.assertEqual(result["totals"]["cash_cad"],"358")
        self.assertEqual(make_payload(self.root)["totals"]["total_cad"],"698")
        self.assertEqual(len(result["history"]),1)
        self.assertFalse(result["changes"]["available"])
        self.assertNotIn("external_deposit",json.dumps(result["crypto"]["orders"]))
        self.assertEqual([r["security_type"] for r in result["instrument_types"]].count("CRYPTO"),1)

    def test_regeneration_does_not_add_observations(self):
        first=self.payload();second=self.payload()
        self.assertEqual(first["meta"]["combined_observation_id"],second["meta"]["combined_observation_id"])
        self.assertEqual(first["meta"]["revision"],second["meta"]["revision"])
        with sqlite3.connect(self.root/"data/db/portfolio.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM combined_observations").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],1)

    def test_skipped_months_and_mixed_dates_preserve_honest_history(self):
        self.payload()
        second=write_holdings(self.root/"incoming/later.csv",when="2026-12-09 22:28 GMT-05:00")
        rates={**FX,"usd_cad_date":"2026-12-09","usd_twd_date":"2026-12-09"}
        import_holdings(self.root,second,"monthly",rates)
        result=self.payload()
        self.assertEqual([h["as_of"][:7] for h in result["history"]],["2026-10","2026-12"])
        self.assertEqual(result["meta"]["missing_official_months"],["2026-11"])
        self.assertTrue(result["changes"]["available"])
        self.assertEqual(result["changes"]["totals"]["total_cad"]["change"],"0")
        self.assertFalse(any(p["scope"]=="portfolio" and p["available"] for p in result["periods"]))
        output=self.root/"future-report"
        artifacts=generate_reports(result,output)
        self.assertEqual(len(artifacts["charts"]),11)
        build_workbook(result,output/"portfolio.ods",chart_images=artifacts["charts"])
        self.assertEqual(validate_formula_caches(output/"portfolio.ods")["cache_mismatches"],0)
        self.assertIn("2026-11",(output/"report.md").read_text(encoding="utf-8"))
        mixed=self.payload("2026-12-10T22:28:00-05:00")
        self.assertFalse(mixed["meta"]["is_complete"])
        self.assertFalse(mixed["changes"]["available"])
        self.assertEqual(mixed["meta"]["wealthsimple_as_of"][:10],"2026-12-09")

    def test_all_three_formats_and_combined_formulas(self):
        payload=self.payload()
        output=self.root/"output"
        result=generate_reports(payload,output)
        ods=output/"portfolio.ods"
        build_workbook(payload,ods,chart_images=result["charts"])
        self.assertEqual(verify_workbook(ods,payload["totals"]["total_cad"])["embedded_images"],10)
        self.assertEqual(validate_formula_caches(ods)["cache_mismatches"],0)
        text=(output/"report.md").read_text(encoding="utf-8")
        self.assertIn("BTC／LBTC",text)
        self.assertIn("0.0025",text)
        self.assertIn("不相加",text)
        self.assertGreater((output/"report.pdf").stat().st_size,1000)
