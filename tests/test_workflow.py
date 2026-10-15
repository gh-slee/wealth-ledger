"""Automatic one/two-file updates, source dates, and idempotent history."""
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import csv
import json
import sqlite3
import tempfile
import unittest

from wealth_ledger.workflow import identify_inputs, prepare_update
from wealth_ledger.reporting import generate_reports
from wealth_ledger.workbook import build_workbook
from wealth_ledger.validation import validate_formula_caches
from test_core import FX,write_holdings
from test_crypto import FIELDS,ASSUMPTIONS,order
from test_combined import quote


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.project=self.root/"project"
        (self.project/"config").mkdir(parents=True)
        (self.project / "config/local.toml").write_text("[reporting]\nbtc_cost_policy = 'bull_average_proxy'\n", encoding="utf-8")
        (self.project/"config/bull-opening.json").write_text(json.dumps(ASSUMPTIONS), encoding="utf-8")
        self.ws=write_holdings(self.root/"unhelpful-name-a.csv")
        self.bull=self.write_orders([order("fund",amount="300"),
            order("buy1","Buy Bitcoin","100","BTC",".001",completed="2026-01-01T02:00:00Z"),
            order("buy2","Buy Bitcoin","150","LBTC",".0015",completed="2026-01-01T03:00:00Z")],"unhelpful-name-b.csv")
        self.now=datetime.fromisoformat("2026-10-10T12:30:45-04:00")
        self.fxp=patch("wealth_ledger.workflow.resolve_rates",side_effect=lambda project,day,override: {
            **FX,"usd_cad_date":day,"usd_twd_date":day})
        self.pp=patch("wealth_ledger.combined.resolve_btc_price",side_effect=lambda project,stamp,override:quote(stamp))
        self.fxp.start();self.pp.start()

    def tearDown(self):
        self.fxp.stop();self.pp.stop();self.temp.cleanup()

    def write_orders(self,rows,name):
        path=self.root/name
        with path.open("w",newline="", encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,FIELDS);writer.writeheader();writer.writerows(rows)
        return path

    def run_update(self,paths=(),**kwargs):
        return prepare_update(self.project,paths,now=kwargs.pop("now",self.now),**kwargs)

    def counts(self):
        with sqlite3.connect(self.project/"data/db/portfolio.sqlite3") as conn:
            return tuple(conn.execute("SELECT COUNT(*) FROM "+table).fetchone()[0] for table in ("snapshots","crypto_order_revisions","combined_observations"))

    def test_content_detection_accepts_either_order_and_dedups_same_path(self):
        found=identify_inputs([self.bull,self.ws,self.bull])
        self.assertEqual(found,{"bullbitcoin":self.bull.resolve(),"wealthsimple":self.ws.resolve()})
        other=write_holdings(self.root/"extra.csv")
        with self.assertRaisesRegex(ValueError,"Only one"):
            identify_inputs([self.ws,other])
        unknown=self.root/"unknown.csv";unknown.write_text("a,b\n1,2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Unsupported"):
            self.run_update([unknown])
        self.assertFalse((self.project/"data/db/portfolio.sqlite3").exists())

    def test_both_sources_use_holdings_cutoff_and_repeat_preserves_observation(self):
        first,_=self.run_update([self.bull,self.ws])
        second,_=self.run_update([self.ws,self.bull])
        self.assertEqual(first["meta"]["as_of"],"2026-10-09T22:28:00-04:00")
        self.assertTrue(first["meta"]["is_complete"])
        self.assertEqual(first["meta"]["data_status"],"sources_updated")
        self.assertEqual(first["meta"]["combined_observation_id"],second["meta"]["combined_observation_id"])
        self.assertEqual(self.counts(),(1,3,1))

    def test_wealthsimple_only_refresh_labels_carried_bull(self):
        self.run_update([self.ws,self.bull])
        later=write_holdings(self.root/"november.csv",when="2026-11-09 22:28 GMT-05:00")
        payload,_=self.run_update([later],now=datetime.fromisoformat("2026-11-10T12:30:00-05:00"))
        self.assertEqual(payload["meta"]["as_of"],"2026-11-09T22:28:00-05:00")
        self.assertEqual(payload["meta"]["source_updates"]["bullbitcoin"]["status"],"carried_forward")
        self.assertEqual(payload["meta"]["data_status"],"carried_source")
        self.assertFalse(payload["meta"]["is_complete"])
        self.assertFalse(payload["changes"]["available"])
        self.assertEqual(self.counts()[0],2)

    def test_bull_only_auto_values_now_repeat_same_day_and_no_file_regeneration(self):
        self.run_update([self.ws,self.bull])
        payload,result=self.run_update([self.bull])
        self.assertEqual(payload["meta"]["as_of"],"2026-10-10T12:30:00-04:00")
        self.assertEqual(payload["meta"]["wealthsimple_as_of"],"2026-10-09T22:28:00-04:00")
        self.assertEqual(payload["meta"]["data_status"],"mixed_dates")
        self.assertFalse(payload["meta"]["is_complete"])
        self.assertEqual(result["detected_inputs"],["bullbitcoin"])
        duplicate,_=self.run_update([self.bull],now=datetime.fromisoformat("2026-10-10T20:30:00-04:00"))
        regenerated,_=self.run_update(now=datetime.fromisoformat("2026-12-10T20:30:00-05:00"))
        self.assertEqual(payload["meta"]["combined_observation_id"],duplicate["meta"]["combined_observation_id"])
        self.assertEqual(payload["meta"]["combined_observation_id"],regenerated["meta"]["combined_observation_id"])
        self.assertEqual(self.counts(),(1,3,2))
        next_day,_=self.run_update([self.bull],now=datetime.fromisoformat("2026-10-11T20:30:00-04:00"))
        self.assertEqual(next_day["meta"]["as_of"],"2026-10-11T20:30:00-04:00")
        self.assertEqual(self.counts(),(1,3,3))

    def test_later_bull_transactions_are_included_without_manual_date(self):
        self.run_update([self.ws,self.bull])
        rows=[order("newfund",amount="100",created="2026-11-09T09:00:00Z",completed="2026-11-09T10:00:00Z"),
              order("newbuy","Buy Bitcoin","100","BTC",".001",created="2026-11-09T10:00:00Z",completed="2026-11-09T11:00:00Z")]
        newer=self.write_orders(rows,"later-bull.csv")
        payload,_=self.run_update([self.ws,newer],now=datetime.fromisoformat("2026-11-10T12:30:00-05:00"))
        self.assertEqual(payload["crypto"]["btc_equivalent_qty"],"0.0035")
        self.assertEqual(payload["meta"]["as_of"],"2026-11-10T12:30:00-05:00")
        self.assertEqual(payload["meta"]["data_status"],"mixed_dates")
        self.assertEqual(self.counts(),(1,5,2))

    def test_bull_first_report_and_adding_broker_do_not_fake_growth(self):
        first,_=self.run_update([self.bull])
        self.assertIsNone(first["meta"]["snapshot_id"])
        self.assertEqual(first["meta"]["data_status"],"btc_only")
        self.assertEqual(first["totals"]["total_cad"],"550")
        self.assertEqual(self.counts(),(0,3,1))
        output=self.project/"work/btc-only-report"
        artifacts=generate_reports(first,output)
        build_workbook(first,output/"portfolio.ods",chart_images=artifacts["charts"])
        self.assertEqual(validate_formula_caches(output/"portfolio.ods")["cache_mismatches"],0)
        combined,_=self.run_update([self.ws,self.bull])
        self.assertNotEqual(first["meta"]["scope_id"],combined["meta"]["scope_id"])
        self.assertFalse(combined["changes"]["available"])
        self.assertEqual(len(combined["history"]),1)

    def test_broker_only_first_and_historical_selection(self):
        first,_=self.run_update([self.ws])
        self.assertNotIn("crypto",first)
        self.run_update([self.bull])
        historical,_=self.run_update(snapshot_id=first["meta"]["snapshot_id"])
        self.assertEqual(historical["meta"]["as_of"],first["meta"]["as_of"])
        with self.assertRaisesRegex(ValueError,"regenerating"):
            self.run_update([self.ws],snapshot_id=1)

    def test_mixed_report_and_history_retain_original_stock_observation_dates(self):
        self.run_update([self.ws,self.bull])
        payload,_=self.run_update([self.bull])
        self.assertEqual(len(payload["wealthsimple_history"]),1)
        self.assertEqual(payload["accounts"][0]["observed_as_of"],"2026-10-09T22:28:00-04:00")
        output=self.project/"work/mixed-report"
        artifacts=generate_reports(payload,output)
        build_workbook(payload,output/"portfolio.ods",chart_images=artifacts["charts"])
        self.assertEqual(len(artifacts["charts"]),11)
        self.assertEqual(validate_formula_caches(output/"portfolio.ods")["cache_mismatches"],0)
        text=(output/"report.md").read_text(encoding="utf-8")
        self.assertIn("沿用已保存資料",text)
        self.assertIn("不同日期資料",text)
