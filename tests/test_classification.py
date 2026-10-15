"""Offline classification provenance, coverage and reconciliation scenarios."""
import copy
from decimal import Decimal as D
import json
from pathlib import Path
import tempfile
import unittest

from wealth_ledger.fund_sources import holding, vanguard, REGISTRY
from wealth_ledger.lookthrough import calculate
from wealth_ledger.classification import country_code
from wealth_ledger.classification_reports import write_exports, report_section
from test_lookthrough import ALIASES, payload, security, fund


class ClassificationTests(unittest.TestCase):
    def analysis(self):
        p=payload([security('Test ETF','ETF',1000),security('Advanced Micro Devices Inc','AMD',100,'EQUITY','XNAS'),
                   security('Taiwan Semiconductor Manufacturing Co Ltd','TSM',200,'EQUITY','XNYS'),security('Bitcoin','BTC',50,'CRYPTO','CRYP')],cash=30)
        rows=[holding('Advanced Micro Devices Inc',50,country='US',gics_sector='Information Technology'),
              holding('Taiwan Semiconductor Manufacturing Co Ltd',30,country='TW',gics_sector='Information Technology'),
              holding('Apple Inc',10,country='US',gics_sector='Information Technology'),
              holding('Unclassified Company',5,country='XE',icb_sector='Technology'),holding('Cash',5,'cash')]
        return p,calculate(p,{'XTSE:ETF':fund('XTSE:ETF',rows)},ALIASES)

    def test_direct_and_indirect_totals_country_not_exchange(self):
        p,a=self.analysis();c=a['classification']
        sector=c['dimensions']['sector'];country=c['dimensions']['country']
        self.assertEqual(D(sector['classified_cad']),D(1200))
        self.assertEqual(D(sector['unclassified_equity_cad']),D(50))
        self.assertEqual(D(sector['equity_coverage']),D(1200)/D(1250))
        self.assertEqual(D(sector['investment_coverage']),D(1200)/D(1350))
        tw=next(r for r in country['rows'] if r['key']=='TW')
        self.assertEqual(D(tw['market_cad']),D(500))
        direct=next(r for r in c['components'] if r['root']=='XNYS:TSM')
        self.assertEqual(direct['assignments']['country']['value'],'TW')
        self.assertEqual(direct['assignments']['country']['method'],'same_company_latest_official')
        self.assertTrue(direct['assignments']['country']['evidence'][0]['official_url'])

    def test_all_dimensions_reconcile_noncompany_separately(self):
        _,a=self.analysis()
        for summary in a['classification']['dimensions'].values():
            self.assertEqual(sum(D(r['market_cad']) for r in summary['rows']),D(1350))
            self.assertEqual(next(D(r['market_cad']) for r in summary['rows'] if r['key']=='crypto'),D(50))
            self.assertEqual(next(D(r['market_cad']) for r in summary['rows'] if r['key']=='cash'),D(50))
        self.assertEqual(a['classification']['dimensions']['sector']['as_of_min'],'2026-10-09')

    def test_listing_and_currency_alone_do_not_classify(self):
        a=calculate(payload([security('Unknown','UNKNOWN',100,'EQUITY','XNAS','USD')]),{},ALIASES)
        c=a['classification']
        self.assertEqual(D(c['dimensions']['country']['classified_cad']),D(0))
        self.assertEqual(D(c['dimensions']['sector']['unclassified_equity_cad']),D(100))
        self.assertIsNone(c['components'][0]['assignments']['country']['value'])

    def test_latest_same_day_conflict_unknown_but_own_rows_retained(self):
        p=payload([security('A','A',100),security('B','B',100),security('Advanced Micro Devices Inc','AMD',100,'EQUITY','XNAS')])
        a=calculate(p,{'XTSE:A':fund('XTSE:A',[holding('Advanced Micro Devices Inc',100,country='US',gics_sector='Information Technology')]),
                       'XTSE:B':fund('XTSE:B',[holding('Advanced Micro Devices Inc',100,country='CA',gics_sector='Industrials')])},ALIASES)
        direct=next(r for r in a['classification']['components'] if r['root']=='XNAS:AMD')
        self.assertIsNone(direct['assignments']['sector']['value'])
        self.assertEqual(direct['assignments']['sector']['method'],'conflicting_latest_official_classification')
        self.assertEqual(len(direct['assignments']['sector']['evidence']),2)
        self.assertEqual(D(a['classification']['dimensions']['country']['classified_cad']),D(200))

    def test_latest_official_classification_and_stale_provenance(self):
        p=payload([security('A','A',100),security('B','B',100),security('Advanced Micro Devices Inc','AMD',100,'EQUITY','XNAS')])
        old=fund('XTSE:A',[holding('Advanced Micro Devices Inc',100,country='CA',gics_sector='Industrials')]);old['as_of']='2026-08-31'
        new=fund('XTSE:B',[holding('Advanced Micro Devices Inc',100,country='US',gics_sector='Information Technology')],status='stale')
        a=calculate(p,{'XTSE:A':old,'XTSE:B':new},ALIASES)
        direct=next(r for r in a['classification']['components'] if r['root']=='XNAS:AMD')
        self.assertEqual(direct['assignments']['country']['value'],'US')
        self.assertEqual(direct['assignments']['country']['evidence'][0]['status'],'stale')
        self.assertEqual(a['classification']['dimensions']['sector']['as_of_min'],'2026-08-31')

    def test_unknown_issuer_sector_is_not_guessed_gics(self):
        row=holding('AMD',100,country='US',issuer_sector='Technology',icb_sector='Technology')
        a=calculate(payload([security('ETF','ETF',100)]),{'XTSE:ETF':fund('XTSE:ETF',[row])},ALIASES)
        self.assertEqual(D(a['classification']['dimensions']['sector']['classified_cad']),D(0))
        self.assertEqual(D(a['classification']['dimensions']['country']['classified_cad']),D(100))

    def test_recursive_fund_coefficient_and_residual(self):
        p=payload([security('Root','ROOT',1000)])
        a=calculate(p,{'XTSE:ROOT':fund('XTSE:ROOT',[holding('Child',90,'fund',fund_id='XNAS:CHILD')]),
            'XNAS:CHILD':fund('XNAS:CHILD',[holding('AMD',80,country='US',gics_sector='Information Technology'),holding('Cash',20,'cash')])},ALIASES)
        c=a['classification'];self.assertEqual(D(c['dimensions']['sector']['classified_cad']),D(720))
        group=next(r for r in c['root_groups'] if r['dimension']=='sector' and r['key']=='Information Technology')
        self.assertEqual(D(group['weight']),D('.72'))
        self.assertEqual(c['components'][0]['assignments']['sector']['evidence'][0]['fund_id'],'XNAS:CHILD')

    def test_failed_fund_and_empty_portfolio_do_not_hide_unknown(self):
        a=calculate(payload([security('ETF','ETF',100)]),{'XTSE:ETF':fund('XTSE:ETF',[],status='failed')},ALIASES)
        s=a['classification']['dimensions']['sector'];self.assertIsNone(s['equity_coverage'])
        self.assertEqual(s['rows'][0]['key'],'unknown');self.assertEqual(D(s['rows'][0]['market_cad']),D(100))
        e=calculate(payload([]),{},ALIASES)['classification']
        self.assertEqual(e['dimensions']['country']['rows'],[])

    def test_vanguard_explicit_gics_while_primary_icb(self):
        data=json.loads((Path(__file__).parent/'fixtures/fund_sources/vanguard.json').read_text(encoding="utf-8"))
        data['data']['funds'][0]['profile']['primarySectorEquityClassification']='ICB Sectors'
        for row in data['data']['borHoldings'][0]['delayeredHoldings']['items']:
            row['gicsSectorDescription']='Communication Services';row['icbIndustryDescription']='Technology'
        class Client:
            def json(self,*args):return copy.deepcopy(data)
        _,rows=vanguard(Client(),REGISTRY['XTSE:VEQT'])
        self.assertEqual(rows[0]['gics_sector'],'Communication Services')
        self.assertEqual(rows[0]['icb_sector'],'Technology')

    def test_exports_and_shared_report_tables(self):
        p,a=self.analysis();p['lookthrough']=a;p['fx']={'usd_cad':'1.4','usd_twd':'30'}
        with tempfile.TemporaryDirectory() as tmp:
            write_exports(p,Path(tmp))
            self.assertIn('market_usd',(Path(tmp)/'allocation-exposure.csv').read_text('utf-8-sig'))
            self.assertIn('same_company_latest_official',(Path(tmp)/'classification-detail.csv').read_text('utf-8-sig'))
        section=report_section(p,{})
        self.assertEqual(section.title,'產業、國別與地區配置')
        self.assertTrue(any(kind=='table' and block.headers[0]=='持倉' for kind,block in section.blocks))

    def test_shared_root_in_two_currencies_does_not_double_coefficients(self):
        p=payload([security('ETF','ETF',100,currency='CAD'),security('ETF','ETF',200,currency='USD')])
        a=calculate(p,{'XTSE:ETF':fund('XTSE:ETF',[holding('Apple Inc',90,country='US',gics_sector='Information Technology'),
                                                    holding('Cash',10,'cash')])},ALIASES)
        c=a['classification']
        group=next(r for r in c['root_groups'] if r['dimension']=='sector' and r['key']=='Information Technology')
        self.assertEqual(D(group['weight']),D('.9'))
        self.assertEqual(D(group['market_cad']),D(270))
        self.assertEqual(len(c['root_coverage']),1)
        self.assertEqual(D(c['root_coverage'][0]['market_cad']),D(300))

    def test_signed_cash_and_rounding_remain_reconciled(self):
        p=payload([security('ETF','ETF',1000)])
        rows=[holding('Apple Inc',100.3,country='US',gics_sector='Information Technology'),holding('Cash',-.2,'cash')]
        a=calculate(p,{'XTSE:ETF':fund('XTSE:ETF',rows)},ALIASES)
        for summary in a['classification']['dimensions'].values():
            values={r['key']:D(r['market_cad']) for r in summary['rows']}
            self.assertEqual(values['cash'],D(-2))
            self.assertEqual(values['adjustment'],D(-1))
            self.assertEqual(sum(values.values()),D(1000))
            self.assertEqual(D(summary['equity_coverage']),D(1))

    def test_country_normalization_and_geography_groups(self):
        self.assertEqual(country_code('United States'),'US')
        self.assertEqual(country_code('Korea (South)'),'KR')
        self.assertIsNone(country_code('XE'));self.assertIsNone(country_code('NASDAQ'))


if __name__=='__main__':unittest.main()
