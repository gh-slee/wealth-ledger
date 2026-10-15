"""Offline issuer format, reconciliation, identity, recursion, and replay tests."""
import copy
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from wealth_ledger.fund_sources import (holding,parse_blackrock,parse_vaneck,parse_fidelity,parse_ci,
                                      parse_bmo,parse_invesco,vanguard,weight,fetch_fund,REGISTRY)
from wealth_ledger.lookthrough import calculate,attach_analysis,normalize_name
from test_core import write_holdings,FX
from wealth_ledger.core import import_holdings,make_payload
import test_workbook as wbfixtures
from wealth_ledger.workbook import build_workbook,BASELINE_CHART_KEYS,verify_workbook,NS,tag
from wealth_ledger.validation import validate_formula_caches

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT/'tests/fixtures/fund_sources'
ALIASES = json.loads((PROJECT/'config/company-aliases.json').read_text(encoding="utf-8"))


def security(name,symbol,amount,kind='EXCHANGE_TRADED_FUND',mic='XTSE',currency='CAD'):
    return {'name':name,'symbol':symbol,'market_cad':str(amount),'security_type':kind,'mic':mic,'currency':currency,'quantity':'1'}


def payload(rows,cash=0):
    return {'meta':{'as_of':'2026-10-10T17:00:00-04:00'},'securities':rows,
            'totals':{'total_cad':str(sum(D(r['market_cad']) for r in rows)+D(cash))}}


def fund(id,rows,status='ok'):
    return {'fund_id':id,'rows':rows,'status':status,'as_of':'2026-10-09','retrieved_at':'2026-10-10T21:00:00+00:00',
            'issuer':'Test issuer','official_url':'https://example.test/public','evidence':[],'latest_checked':status!='failed'}


class IssuerTests(unittest.TestCase):
    def load(self,name):return json.loads((FIXTURES/name).read_text(encoding="utf-8"),parse_float=D)
    def test_blackrock_percent_and_cash(self):
        date,rows=parse_blackrock((FIXTURES/'blackrock.csv').read_bytes())
        self.assertEqual(date,'2024-01-31')
        self.assertEqual(next(r['weight'] for r in rows if r['ticker']=='SYN-A'),'0.6')
        self.assertTrue(any(r['kind']=='cash' for r in rows))
        self.assertEqual(sum(D(r['weight']) for r in rows),D(1))
    def test_vaneck_cash_without_issuer_name(self):
        date,rows=parse_vaneck((FIXTURES/'vaneck.xlsx').read_bytes())
        self.assertEqual(date,'2024-01-31')
        cash=next(r for r in rows if r['name']=='-USD CASH-')
        self.assertEqual(cash['kind'],'cash')
        self.assertEqual(D(cash['weight']),D('.05'))
        self.assertEqual(len(rows),2)
    def test_bmo_fraction_and_identity(self):
        date,rows=parse_bmo(self.load('bmo.json'))
        self.assertEqual(date,'2024-01-31')
        self.assertEqual(D(rows[0]['weight']),D('.6'))
        self.assertTrue(rows[0]['identifiers']['isin'].startswith('US'))
    def test_invesco_adrs_and_nullable_weight(self):
        date,rows=parse_invesco(self.load('invesco.json'))
        self.assertEqual(date,'2024-01-31')
        self.assertEqual(next(r['kind'] for r in rows if r['ticker']=='SYN-ADR'),'equity')
        self.assertEqual(len(rows),3)
        self.assertNotIn('SYN-U', {r['ticker'] for r in rows})
        self.assertTrue(any(D(r['weight'])<0 and r['kind']=='cash' for r in rows))
    def test_wrong_fund_and_truncated_response_rejected(self):
        data=self.load('invesco.json');data['cusip']='wrong'
        with self.assertRaises(ValueError):parse_invesco(data)
        data=self.load('invesco.json');data['holdings'].pop()
        with self.assertRaises(ValueError):parse_invesco(data)
        data=self.load('bmo.json');data['data']['webProfiles'][0]['entityId']='wrong'
        with self.assertRaises(ValueError):parse_bmo(data)
    def test_fidelity_bitcoin_is_not_a_company_or_cash(self):
        date,rows=parse_fidelity(self.load('fidelity.json'))
        self.assertEqual(date,'2024-01-31')
        self.assertEqual(rows[0]['kind'],'crypto')
        self.assertEqual(rows[0]['weight'],'0.95')
    def test_ci_holdings_date_distinct_from_nav_and_child_fund(self):
        date,rows=parse_ci((FIXTURES/'ci.html').read_bytes())
        self.assertEqual(date,'2024-01-31')
        self.assertEqual(rows[0]['fund_id'],'XNAS:QQQM')
        self.assertEqual(D(rows[0]['weight']),D('.90'))
    def test_vanguard_all_pages_and_repeated_cursor(self):
        first=self.load('vanguard.json');second=copy.deepcopy(first)
        first['data']['borHoldings'][0]['delayeredHoldings'].update(items=first['data']['borHoldings'][0]['delayeredHoldings']['items'][:1],lastItemKey='page2')
        second['data']['borHoldings'][0]['delayeredHoldings']['items']=second['data']['borHoldings'][0]['delayeredHoldings']['items'][1:]
        class Client:
            def __init__(self):self.calls=[]
            def json(self,url,body,headers):
                self.calls.append(body['variables']['lastItemKey'])
                return first if len(self.calls)==1 else second
        client=Client();date,rows=vanguard(client,REGISTRY['XTSE:VEQT'])
        self.assertEqual(client.calls,[None,'page2']);self.assertEqual(len(rows),2)
        second['data']['borHoldings'][0]['delayeredHoldings']['lastItemKey']='page2'
        with self.assertRaises(ValueError):vanguard(Client(),REGISTRY['XTSE:VEQT'])
    def test_vanguard_missing_page_rejected(self):
        data=self.load('vanguard.json');data['data']['borHoldings'][0]['delayeredHoldings']['totalHoldings']=3
        class Client:
            def json(self,*a):return data
        with self.assertRaises(ValueError):vanguard(Client(),REGISTRY['XTSE:VEQT'])
    def test_weight_rejects_nonfinite_and_huge(self):
        for value in ['NaN','Infinity','999']:
            with self.assertRaises(ValueError):weight(value)
    def test_age_is_flagged_without_claiming_fresh_date(self):
        from datetime import date
        data=self.load('fidelity.json')
        with patch('wealth_ledger.fund_sources.Client') as client:
            client.return_value.json.return_value=data;client.return_value.evidence=[]
            result=fetch_fund('XTSE:FBTC','unused',today=date(2027,2,1))
            self.assertEqual(result['status'],'stale');self.assertTrue(result['latest_checked'])
            self.assertEqual(result['as_of'],'2024-01-31')


class CalculationTests(unittest.TestCase):
    def test_overlap_direct_and_recursive_adrs(self):
        p=payload([security('ETF A','A',100),security('ETF B','B',200),security('Advanced Micro Devices Inc','AMD',50,'EQUITY','XNAS'),security('BTC','BTC',50,'CRYPTO','CRYPTO')],cash=100)
        f={'XTSE:A':fund('XTSE:A',[holding('Advanced Micro Devices',50),holding('Alphabet Inc Class A',25),holding('Alphabet Inc Class C',25)]),
           'XTSE:B':fund('XTSE:B',[holding('Child',50,'fund',fund_id='XNAS:CHILD'),holding('BITCOIN',50,'crypto')]),
           'XNAS:CHILD':fund('XNAS:CHILD',[holding('Advanced Micro Devices Inc',50),holding('Taiwan Semiconductor Manufacturing Co L',50)])}
        r=calculate(p,f,ALIASES);amd=next(c for c in r['companies'] if c['company_id']=='company:amd')
        self.assertEqual(D(amd['total_cad']),D(150));self.assertEqual(D(amd['direct_cad']),D(50));self.assertEqual(D(amd['investment_weight']),D('.375'));self.assertEqual(D(amd['asset_weight']),D('.30'))
        self.assertEqual(len([c for c in r['companies'] if c['name']=='Alphabet']),1)
        self.assertEqual(D(r['noncompany']['crypto']),D(150));self.assertEqual(D(r['company_total_cad']),D(250))
    def test_cycle_preserves_unknown_and_reconciles(self):
        p=payload([security('A','A',100)])
        f={'XTSE:A':fund('XTSE:A',[holding('B',100,'fund',fund_id='XTSE:B')]),'XTSE:B':fund('XTSE:B',[holding('A',100,'fund',fund_id='XTSE:A')])}
        r=calculate(p,f,ALIASES);self.assertEqual(r['noncompany']['unknown'],'100');self.assertTrue(r['issues'])
    def test_unregistered_failed_fund_is_unknown_not_zero(self):
        r=calculate(payload([security('Unknown','X',100)]),{},ALIASES)
        self.assertEqual(r['unknown_weight'],'1');self.assertEqual(r['top20'],[])
    def test_positive_unreported_weight_and_negative_cash(self):
        p=payload([security('A','A',100)])
        f={'XTSE:A':fund('XTSE:A',[holding('Apple Inc',101),holding('Cash',-2,'cash')])}
        r=calculate(p,f,ALIASES);self.assertEqual(r['noncompany']['unknown'],'1.00');self.assertEqual(r['noncompany']['cash'],'-2.00');self.assertEqual(r['company_total_cad'],'101.00')
    def test_rounding_not_normalized_and_excess_rejected(self):
        p=payload([security('A','A',100)])
        f={'XTSE:A':fund('XTSE:A',[holding('Apple Inc',100.01)])}
        r=calculate(p,f,ALIASES);self.assertEqual(D(r['companies'][0]['total_cad']),D('100.01'));self.assertEqual(D(r['noncompany']['adjustment']),D('-.01'))
        f['XTSE:A']['rows'][0]['weight']='1.2'
        with self.assertRaises(ValueError):calculate(p,f,ALIASES)
    def test_same_fund_multiple_trading_currencies_are_added(self):
        p=payload([security('A','A',100),security('A','A',200,currency='USD')]);r=calculate(p,{'XTSE:A':fund('XTSE:A',[holding('Apple Inc',100)])},ALIASES)
        self.assertEqual(D(r['companies'][0]['total_cad']),D(300))
    def test_security_id_spelling_bridge_and_ambiguous_names(self):
        p=payload([security('A','A',100)])
        rows=[holding('Example International',20,identifiers={'isin':'US1234567890'},country='US'),holding('Example Intl',30,identifiers={'cusip':'123456789'},country='US'),holding('Generic Bank',25,country='US'),holding('Generic Bank',25,country='CA')]
        r=calculate(p,{'XTSE:A':fund('XTSE:A',rows)},ALIASES)
        self.assertEqual(len(r['companies']),3);self.assertEqual(max(D(c['total_cad']) for c in r['companies']),D(50))
    def test_normalization_merges_share_classes_and_adr_names(self):
        self.assertEqual(normalize_name('Alphabet Inc. Cap Stk Cl C'),normalize_name('Alphabet Inc Class A'))
        self.assertEqual(normalize_name('Example Co Ltd ADR'),normalize_name('Example Co Ltd'))
    def test_reviewed_company_alias_merges_cross_market_countries(self):
        p=payload([security('A','A',100)])
        rows=[holding('STMicroelectronics NV',50,country='Italy'),holding('STMicroelectronics Nv',50,country='NL')]
        r=calculate(p,{'XTSE:A':fund('XTSE:A',rows)},ALIASES)
        self.assertEqual(len(r['companies']),1);self.assertEqual(r['companies'][0]['company_id'],'company:stmicroelectronics')
        self.assertEqual(D(r['noncompany']['unknown']),D(0))

    def test_issuer_words_are_not_stripped_as_share_descriptors(self):
        self.assertEqual(normalize_name('Preferred Bank'),'preferred bank')
        self.assertEqual(normalize_name('ADS-TEC Energy Inc'),'ads tec energy')
        self.assertEqual(normalize_name('Class A Networks Inc'),'class a networks')

    def test_short_portfolio_rejected(self):
        with self.assertRaises(ValueError):calculate(payload([security('A','A',-1)]),{},ALIASES)
    def test_zero_empty_portfolio_does_not_divide(self):
        r=calculate(payload([],cash=100),{},ALIASES);self.assertIsNone(r['top20_weight']);self.assertEqual(r['top20'],[])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='lookthrough-test-');self.project=Path(self.temp.name)
        (self.project/'data/db').mkdir(parents=True);(self.project/'config').mkdir();(self.project/'config/company-aliases.json').write_text(json.dumps(ALIASES), encoding="utf-8")
    def tearDown(self):self.temp.cleanup()
    def test_latest_each_run_then_frozen_replay_without_calls(self):
        p=payload([security('VFV','VFV',100)])
        calls=[]
        def fetch(id,directory):calls.append(id);return fund(id,[holding('Apple Inc',100)])
        r=attach_analysis(self.project,p,fetcher=fetch);first=r['run_id']
        attach_analysis(self.project,p,fetcher=fetch);self.assertEqual(len(calls),2)
        def prohibited(*a):raise AssertionError('Offline replay must not fetch')
        replay=attach_analysis(self.project,p,run_id=first,fetcher=prohibited);self.assertEqual(replay['mode'],'frozen_replay')
        p['securities'][0]['market_cad']='101'
        with self.assertRaises(ValueError):attach_analysis(self.project,p,run_id=first,fetcher=prohibited)
    def test_download_failure_does_not_reuse_previous_source(self):
        p=payload([security('VFV','VFV',100)])
        attach_analysis(self.project,p,fetcher=lambda id,directory:fund(id,[holding('Apple Inc',100)]))
        def failed(*a):raise OSError('simulated failure')
        r=attach_analysis(self.project,p,fetcher=failed)
        self.assertEqual(r['top20'],[]);self.assertEqual(r['unknown_weight'],'1');self.assertFalse(r['sources'][0]['latest_checked'])
        with sqlite3.connect(self.project/'data/db/portfolio.sqlite3') as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM fund_sources').fetchone()[0],1)
    def test_analysis_does_not_mutate_holdings_history(self):
        import_holdings(self.project,write_holdings(self.project/'input.csv'),'baseline',FX)
        p=make_payload(self.project)
        with sqlite3.connect(self.project/'data/db/portfolio.sqlite3') as conn:before=conn.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0]
        attach_analysis(self.project,p)
        with sqlite3.connect(self.project/'data/db/portfolio.sqlite3') as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0],before)


class WorkbookLookthroughTests(unittest.TestCase):
    setUp = wbfixtures.WorkbookTests.setUp
    tearDown = wbfixtures.WorkbookTests.tearDown
    payload = wbfixtures.WorkbookTests.payload
    chart_fixture = wbfixtures.WorkbookTests.chart_fixture
    def test_report_status_respects_saved_classification_availability(self):
        from wealth_ledger.reporting import _sections
        p=self.payload()
        r=calculate(p,{'XTSE:ETF':fund('XTSE:ETF',[holding('Apple Inc',100,country='US',gics_sector='Information Technology')])},ALIASES)
        r['run_id']=1;p['lookthrough']=r
        charts={key:Path(key+'.png') for key in (*BASELINE_CHART_KEYS,'12_company_exposure','13_sector_exposure','14_country_exposure','15_region_exposure')}
        sections=_sections(p,charts)
        pending=[text for section in sections for kind,text in section.blocks if kind=='paragraph' and text.startswith('尚未啟用：')]
        self.assertTrue(pending);self.assertNotIn('實際地區／產業曝險',pending[0])
        del r['classification']
        sections=_sections(p,charts)
        pending=[text for section in sections for kind,text in section.blocks if kind=='paragraph' and text.startswith('尚未啟用：')]
        self.assertIn('實際地區／產業曝險',pending[0])

    def test_company_table_formulas_and_embedded_chart(self):
        p=self.payload();rows=[holding('Apple Inc',75),holding('Cash',25,'cash')]
        r=calculate(p,{'XTSE:ETF':fund('XTSE:ETF',rows)},ALIASES);r['run_id']=1;p['lookthrough']=r
        output=self.project/'company.ods'
        charts=self.chart_fixture((*BASELINE_CHART_KEYS,'12_company_exposure','13_sector_exposure','14_country_exposure','15_region_exposure'))
        build_workbook(p,output,chart_images=charts)
        check=validate_formula_caches(output);self.assertEqual(check['cache_mismatches'],0)
        import zipfile
        with zipfile.ZipFile(output) as archive:
            files={name:archive.read(name) for name in archive.namelist()}
        self.assertIn('前 20 大公司',files['content.xml'].decode())
        import xml.etree.ElementTree as ET
        for name in ('content.xml','styles.xml'):
            root=ET.fromstring(files[name])
            for parent in root.iter():
                for child in list(parent):
                    if child.tag==tag('style:style') and child.get(tag('style:name'))=='input_percent':
                        parent.remove(child)
            files[name]=ET.tostring(root)
        bad=self.project/'missing-percentage-style.ods'
        with zipfile.ZipFile(bad,'w') as archive:
            for name,body in files.items():archive.writestr(name,body)
        with self.assertRaisesRegex(ValueError,'Undefined workbook style'):
            verify_workbook(bad)
