"""Reporting preferences are explicit, local, and do not rewrite financial history."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from wealth_ledger.settings import btc_cost_policy
from wealth_ledger.btc_performance import btc_cost_estimate


class ReportingSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def config(self, text):
        path = self.project / 'config/local.toml'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_fresh_project_uses_actual_only_without_writes(self):
        self.assertEqual(btc_cost_policy(self.project), 'actual_only')
        self.assertEqual(list(self.project.iterdir()), [])

    def test_explicit_local_opt_in_and_cli_priority(self):
        self.config('[reporting]\nbtc_cost_policy = "bull_average_proxy"\n')
        self.assertEqual(btc_cost_policy(self.project), 'bull_average_proxy')
        self.assertEqual(btc_cost_policy(self.project, 'actual_only'), 'actual_only')

    def test_invalid_or_malformed_policy_is_rejected(self):
        for text in ('[reporting]\nbtc_cost_policy="unknown"', 'invalid [', 'reporting="wrong"'):
            with self.subTest(text=text):
                self.config(text)
                with self.assertRaises(ValueError):
                    btc_cost_policy(self.project)

    def test_actual_only_retains_known_purchase_average_but_disables_proxy(self):
        crypto={'purchased_btc_equivalent_qty':'0.06','total_buy_cost_cad':'6000',
                'btc_equivalent_qty':'0.08','cost_estimate_policy':'actual_only',
                'valuation':{'market_cad':'9600','unrealized_cad':None}}
        before=deepcopy(crypto)
        estimate=btc_cost_estimate(crypto)
        self.assertEqual(estimate['status'], 'proxy_disabled')
        self.assertEqual(estimate['average_price_cad_per_btc'], 100000)
        for key in ('estimated_cost_cad','estimated_gain_cad','estimated_return'):
            self.assertIsNone(estimate[key])
        self.assertEqual(before,crypto)

    def test_legacy_saved_payload_keeps_its_existing_report_method(self):
        crypto={'purchased_btc_equivalent_qty':'0.06','total_buy_cost_cad':'6000',
                'btc_equivalent_qty':'0.08','valuation':{'market_cad':'9600'}}
        self.assertEqual(btc_cost_estimate(crypto)['estimated_cost_cad'],8000)

    def test_policy_changes_are_not_new_financial_observations(self):
        import csv,json,sqlite3
        from unittest.mock import patch
        from wealth_ledger.core import import_holdings
        from wealth_ledger.crypto import import_bull_orders
        from wealth_ledger.combined import make_combined_payload
        from test_core import FX,write_holdings
        from test_crypto import ASSUMPTIONS,FIELDS,order
        from test_combined import quote
        holdings=write_holdings(self.project/'input/holdings.csv')
        import_holdings(self.project,holdings,'baseline',FX)
        orders=self.project/'input/orders.csv'
        with orders.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,FIELDS);writer.writeheader()
            writer.writerows([order('fund'),order('buy','Buy Bitcoin','100','BTC','.001')])
        import_bull_orders(self.project,orders,opening_assumption=ASSUMPTIONS)
        with patch('wealth_ledger.combined.resolve_btc_price',side_effect=lambda p,t,f:quote(t)):
            actual=make_combined_payload(self.project)
            proxy=make_combined_payload(self.project,btc_cost_policy='bull_average_proxy')
        self.assertEqual(actual['crypto']['cost_estimate_policy'],'actual_only')
        self.assertEqual(proxy['crypto']['cost_estimate_policy'],'bull_average_proxy')
        self.assertEqual(actual['meta']['combined_observation_id'],proxy['meta']['combined_observation_id'])
        with sqlite3.connect(self.project/'data/db/portfolio.sqlite3') as conn:
            saved=json.loads(conn.execute('SELECT payload_json FROM combined_observations').fetchone()[0])
            self.assertNotIn('cost_estimate_policy',json.dumps(saved))

    def test_actual_only_has_no_proxy_formulas_and_passes_three_format_checks(self):
        import csv
        from unittest.mock import patch
        from wealth_ledger.core import import_holdings
        from wealth_ledger.crypto import import_bull_orders
        from wealth_ledger.combined import make_combined_payload
        from wealth_ledger.reporting import generate_reports
        from wealth_ledger.workbook import build_workbook
        from wealth_ledger.report_checks import validate_report_presentation
        from test_core import FX,write_holdings
        from test_crypto import ASSUMPTIONS,FIELDS,order
        from test_combined import quote
        holdings=write_holdings(self.project/'input/holdings.csv')
        import_holdings(self.project,holdings,'baseline',FX)
        orders=self.project/'input/orders.csv'
        with orders.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,FIELDS);writer.writeheader()
            writer.writerows([order('fund'),order('buy','Buy Bitcoin','100','BTC','.001')])
        import_bull_orders(self.project,orders,opening_assumption=ASSUMPTIONS)
        with patch('wealth_ledger.combined.resolve_btc_price',side_effect=lambda p,t,f:quote(t)):
            payload=make_combined_payload(self.project)
        output=self.project/'output'
        artifacts=generate_reports(payload,output)
        build_workbook(payload,output/'portfolio.ods',chart_images=artifacts['charts'])
        result=validate_report_presentation(payload,output)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['btc_cost_policy'],'actual_only')
        self.assertEqual(result['policy'],'active_state_actual_costs_only')
        self.assertIn('未啟用成本代理',(output/'report.md').read_text(encoding='utf-8'))
