"""Synthetic declaration preview/commit/recovery and owner-scope acceptance."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch
import uuid

import test_web as foundation
from wealth_ledger.operations import fingerprint, input_fingerprint, list_operations
from wealth_ledger import wallet

if foundation.AVAILABLE:
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.worker import execute_job, reconcile


@unittest.skipUnless(foundation.AVAILABLE,'Optional Web dependencies are not installed')
class FinancialTests(unittest.TestCase):
    setUp=foundation.WebTests.setUp
    bootstrap=foundation.WebTests.bootstrap
    login=foundation.WebTests.login
    mutate=foundation.WebTests.mutate
    portfolio=foundation.WebTests.portfolio

    def prepare(self):
        self.login();self.pid=self.portfolio();_,self.project=self.store.portfolio(self.pid)
        self.prefix='/api/v1/portfolios/'+self.pid;self.jobs=Jobs(self.store)

    def submit(self, value, *, confirm=True):
        response=self.mutate('POST',self.prefix+'/financial/previews',body=value,headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(response.status_code,202,response.text);preview=response.json()
        before=input_fingerprint(self.project)
        execute_job(self.settings,preview['id'])
        self.assertEqual(before,input_fingerprint(self.project))
        row=self.jobs.get(self.pid,preview['id'])
        self.assertEqual(row['status'],'ready',row)
        if not confirm:return row
        response=self.mutate('POST',self.prefix+'/financial/jobs',body={'preview_id':preview['id']},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(response.status_code,202,response.text);job=response.json();execute_job(self.settings,job['id'])
        result=self.jobs.get(self.pid,job['id']);self.assertEqual(result['status'],'recorded',result)
        return result

    def balance(self, qty='0.10000000', stamp='2023-01-01T12:00:00-05:00'):
        return {'command':'balance','quantity_btc':qty,'as_of':stamp,'source':'Synthetic wallet total'}

    def test_preview_offline_readonly_and_commit_atomic_marker_no_report(self):
        self.prepare()
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            row=self.submit(self.balance())
        self.assertFalse((self.project/'reports/latest.json').exists())
        records=wallet.records(self.project,'balance');self.assertEqual(len(records),1)
        op=list_operations(self.project)[0];self.assertEqual(op['operation_id'],row['core_operation_id']);self.assertEqual(op['status'],'data_only_complete')
        self.assertEqual(op['fingerprint'],fingerprint(self.project))
        self.assertFalse(json.loads(row['result_json'])['report_published'])
        response=self.client.get(self.prefix+'/financial');self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('source_path',response.text);self.assertNotIn(str(self.root),response.text)

    def test_event_link_revision_void_and_record_history(self):
        self.prepare();self.submit(self.balance())
        self.submit(self.balance('0.09900000','2023-02-01T12:00:00-05:00'))
        event={'command':'event','type':'fee','quantity_btc':'0.00100000','occurred_at':'2023-01-20T12:00:00-05:00',
               'source':'Synthetic wallet','reference':'fee-001','balance_id':'B000002'}
        self.submit(event)
        self.submit({'command':'revision','record_id':'E000003','expected_revision':1,'action':'unlink','reason':'Correct attribution'})
        self.submit({'command':'revision','record_id':'E000003','expected_revision':2,'action':'link','balance_id':'B000002','reason':'Reviewed interval'})
        response=self.client.get(self.prefix+'/financial/records/B000002');self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['reconciliation']['status'],'arithmetic_match')
        self.submit({'command':'revision','record_id':'E000003','expected_revision':3,'action':'void','reason':'Replace duplicate fee'})
        row=self.client.get(self.prefix+'/financial/records/E000003').json();self.assertTrue(row['record']['void']);self.assertEqual(len(row['revisions']),4)

    def test_stale_preview_idempotency_cross_portfolio_and_csrf(self):
        self.prepare();preview=self.submit(self.balance(),confirm=False)
        (self.project/'config/local.toml').write_text('[reporting]\nlocale="zh-TW"\n')
        response=self.mutate('POST',self.prefix+'/financial/jobs',body={'preview_id':preview['id']},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(response.status_code,409)
        other=self.portfolio('Other synthetic')
        self.assertEqual(self.client.get('/api/v1/portfolios/'+other+'/financial/records/B000001').status_code,404)
        response=self.client.post(self.prefix+'/financial/previews',json=self.balance());self.assertEqual(response.status_code,403)
        bad={**self.balance(),'quantity_btc':0.1}
        self.assertEqual(self.mutate('POST',self.prefix+'/financial/previews',body=bad,headers={'Idempotency-Key':uuid.uuid4().hex}).status_code,422)
        self.assertEqual(self.mutate('POST',self.prefix+'/financial/previews',body={**self.balance(),'path':'/private'},headers={'Idempotency-Key':uuid.uuid4().hex}).status_code,422)

    def test_committed_record_recovers_without_duplicate_after_web_state_failure(self):
        self.prepare();row=self.submit(self.balance())
        self.jobs.state(row['id'],'running')
        reconcile(self.store)
        self.assertEqual(self.jobs.get(self.pid,row['id'])['status'],'recorded')
        self.assertEqual(len(wallet.records(self.project,'balance')),1)
        self.assertEqual(len(list_operations(self.project)),1)

    def test_cash_flow_usd_evidence_coverage_and_no_duplicate_funding(self):
        self.prepare()
        from wealth_ledger.core import import_holdings
        from test_core import FX,write_holdings
        source=write_holdings(self.root.parent/'invented.csv');import_holdings(self.project,source,'baseline',FX)
        account=self.client.get(self.prefix+'/financial').json()['accounts'][0]['account_id']
        flow={'command':'cash_flow','date':'2023-01-01','account_id':account,'flow_type':'deposit','currency':'USD','amount':'10.25',
              'flow_id':'bank-unique-001','usd_cad':'1.4','fx_date':'2023-01-01','fx_source':'Synthetic settlement record'}
        self.submit(flow)
        self.submit(flow)
        self.submit({'command':'coverage','start_date':'2023-01-01','end_date':'2023-02-01','status':'complete'})
        state=self.client.get(self.prefix+'/financial').json();self.assertEqual(len(state['cash_flows']),1)
        self.assertEqual(state['cash_flows'][0]['amount_cad'],'14.35');self.assertEqual(len(state['coverage']),1)

    def test_explicit_flow_upload_preserved_and_report_preview_rejects_wrong_kind(self):
        self.prepare()
        from wealth_ledger.core import import_holdings
        from test_core import FX,write_holdings
        import_holdings(self.project,write_holdings(self.root.parent/'invented.csv'),'baseline',FX)
        account=self.client.get(self.prefix+'/financial').json()['accounts'][0]['account_id']
        raw=f'date,account_id,flow_type,currency,amount\n2023-01-01,{account},deposit,CAD,12.50\n'.encode()
        response=self.client.post(self.prefix+'/uploads?kind=cash_flows&filename=flows.csv',content=raw,
            headers={'Origin':foundation.ORIGIN,'X-CSRF-Token':self.csrf,'Content-Type':'text/csv'})
        self.assertEqual(response.status_code,201,response.text);identifier=response.json()['id']
        row=self.submit({'command':'cash_flow_upload','upload_id':identifier})
        self.assertEqual(len(self.client.get(self.prefix+'/financial').json()['cash_flows']),1)
        self.assertEqual(self.client.get(self.prefix+'/uploads/'+identifier).content,raw)
        result=self.mutate('POST',self.prefix+'/previews',body={'upload_ids':[identifier]},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(result.status_code,422)

    def test_invalid_or_ambiguous_declarations_do_not_modify_finances(self):
        self.prepare();before=fingerprint(self.project)
        for value in (self.balance(stamp='2999-01-01T00:00:00Z'),
                      {'command':'event','type':'fee','quantity_btc':'0.001','occurred_at':'2023-01-20T12:00:00-05:00','source':'Bull Bitcoin','reference':'duplicate-buy'}):
            response=self.mutate('POST',self.prefix+'/financial/previews',body=value,headers={'Idempotency-Key':uuid.uuid4().hex})
            self.assertEqual(response.status_code,202,response.text);execute_job(self.settings,response.json()['id'])
            self.assertEqual(self.jobs.get(self.pid,response.json()['id'])['status'],'blocked')
        self.assertEqual(before,fingerprint(self.project))

    def test_opening_revision_is_explicit_and_later_balances_never_recalculate_it(self):
        import csv
        from wealth_ledger.crypto import import_bull_orders
        from wealth_ledger.crypto_opening import latest_opening
        from test_crypto import FIELDS, ASSUMPTIONS, order
        self.now[0]=__import__('datetime').datetime.fromisoformat('2026-10-12T12:00:00-04:00').timestamp()
        self.prepare()
        source=self.root.parent/'invented-bull.csv'
        with source.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,FIELDS);writer.writeheader()
            writer.writerows([order('invented-funding'),order('invented-buy','Buy Bitcoin','100','BTC','0.001')])
        import_bull_orders(self.project,source,opening_assumption=ASSUMPTIONS)
        declaration={'command':'opening','expected_revision':0,'reported_total_btc_equivalent':'0.0015',
            'reference_as_of':'2026-10-09T18:00:00-04:00','declared_on':'2026-10-10','balance_scope':'all_wallets_btc_plus_lbtc',
            'basis':'Invented pre-Bull quantity declaration','confirmed_by':'Synthetic user'}
        self.submit(declaration)
        self.assertEqual(latest_opening(self.project)['opening_btc_equivalent_qty'],'0.0005')
        self.submit(self.balance('0.0014','2026-10-10T18:00:00-04:00'))
        self.assertEqual(latest_opening(self.project)['opening_btc_equivalent_qty'],'0.0005')
        self.submit({**declaration,'expected_revision':1,'reported_total_btc_equivalent':'0.0016','basis':'Corrected explicit opening declaration'})
        self.assertEqual(latest_opening(self.project)['revision'],2)
        self.assertEqual(latest_opening(self.project)['opening_btc_equivalent_qty'],'0.0006')
        self.assertIsNone(latest_opening(self.project)['cost_cad'])

    def test_financial_preview_and_confirmation_idempotency(self):
        self.prepare();key=uuid.uuid4().hex
        def preview(value):
            return self.mutate('POST',self.prefix+'/financial/previews',body=value,headers={'Idempotency-Key':key})
        first=preview(self.balance());self.assertEqual(first.status_code,202)
        self.assertEqual(first.json()['id'],preview(self.balance()).json()['id'])
        self.assertEqual(preview(self.balance('0.2')).status_code,409)
        execute_job(self.settings,first.json()['id']);confirm_key=uuid.uuid4().hex
        def confirm():
            return self.mutate('POST',self.prefix+'/financial/jobs',body={'preview_id':first.json()['id']},headers={'Idempotency-Key':confirm_key})
        row=confirm();self.assertEqual(row.status_code,202);execute_job(self.settings,row.json()['id'])
        self.assertEqual(confirm().json()['id'],row.json()['id'])
        execute_job(self.settings,row.json()['id'])
        self.assertEqual(len(wallet.records(self.project,'balance')),1)

    def test_interruption_inside_record_transaction_rolls_back_rows_and_completion(self):
        self.prepare();preview=self.submit(self.balance(),confirm=False)
        response=self.mutate('POST',self.prefix+'/financial/jobs',body={'preview_id':preview['id']},headers={'Idempotency-Key':uuid.uuid4().hex})
        identifier=response.json()['id']
        from wealth_ledger.operations import atomic_data
        def interrupted(project,action,*,finalize=None):
            def crash(conn,result,value):
                finalize(conn,result,value)
                raise SystemExit('Synthetic process interruption inside commit')
            return atomic_data(project,action,finalize=crash)
        with patch('wealth_ledger.operations.atomic_data',side_effect=interrupted):
            with self.assertRaises(SystemExit):execute_job(self.settings,identifier)
        self.assertEqual(wallet.records(self.project,'balance'),[])
        self.assertEqual(list_operations(self.project)[0]['status'],'data_started')
        reconcile(self.store)
        self.assertEqual(self.jobs.get(self.pid,identifier)['status'],'needs_review')
        execute_job(self.settings,identifier)
        self.assertEqual(wallet.records(self.project,'balance'),[])

    def test_saved_data_report_preview_needs_no_new_evidence_and_keeps_cutoff(self):
        self.prepare()
        from wealth_ledger.core import import_holdings
        from test_core import FX,write_holdings
        import_holdings(self.project,write_holdings(self.root.parent/'invented.csv'),'baseline',FX)
        response=self.mutate('POST',self.prefix+'/previews',body={'render_saved':True},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(response.status_code,202,response.text)
        before=input_fingerprint(self.project);execute_job(self.settings,response.json()['id'])
        job=self.jobs.get(self.pid,response.json()['id']);self.assertEqual(job['status'],'ready',job)
        self.assertEqual(before,input_fingerprint(self.project))
        self.assertFalse((self.project/'reports/latest.json').exists())
