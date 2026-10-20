"""Canonical investment declarations retain date precision and evidence integrity."""
import csv
from decimal import Decimal as D
import io
import json
import sqlite3
import unittest

import test_source_defaults as defaults
from test_source_legacy_projection import AT, FX
from wealth_ledger.core import import_cash_flows, mark_flow_period
from wealth_ledger.source_ingestion import verify_store, state_fingerprint
from wealth_ledger.source_legacy_projection import project_compatible_sources
from wealth_ledger.source_profiles import investment_accounts
from wealth_ledger.application import ApplicationService
from wealth_ledger.workspace import resolve_workspace


class SourceManualFlowTests(unittest.TestCase):
    setUp = defaults.DefaultSourceTests.setUp
    financial = defaults.DefaultSourceTests.financial
    preview = defaults.DefaultSourceTests.preview
    bind = defaults.DefaultSourceTests.bind
    approved = defaults.DefaultSourceTests.approved
    publish = defaults.DefaultSourceTests.publish
    seed = defaults.DefaultSourceTests.seed

    def flows(self, rows, name='cash.csv'):
        output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=['date','account_id','flow_type','currency','amount','flow_id','usd_cad','fx_date','fx_source'])
        writer.writeheader()
        for row in rows:writer.writerow({'date':'2024-02-15','flow_type':'deposit','currency':'CAD','amount':'100',**row})
        path=self.root/name;path.write_text(output.getvalue());return path

    def model(self):
        return project_compatible_sources(self.project,as_of=AT,period_start='2024-01-01T00:00:00Z',fx=FX)

    def test_source_account_forms_historical_fx_and_coverage_without_native_rows(self):
        self.seed();accounts=ApplicationService(resolve_workspace(explicit=self.project)).accounts()
        self.assertEqual(len(accounts),3);self.assertTrue(all(r['account_id'].startswith('src_') for r in accounts))
        aid=accounts[0]['account_id'];before=state_fingerprint(self.project)
        result=import_cash_flows(self.project,self.flows([{'account_id':aid,'flow_id':'cad-1'},
            {'account_id':aid,'flow_id':'usd-1','currency':'USD','usd_cad':'1.4','fx_date':'2024-02-14','fx_source':'https://example.test/historical-fx'}]))
        self.assertEqual(result['imported'],2);self.assertNotEqual(state_fingerprint(self.project),before)
        mark_flow_period(self.project,'2024-01-01','2024-03-01','complete',aid)
        model=self.model();flows=model['legacy_cash_flows']
        self.assertEqual(D(flows['known_recorded_external_cad']),D('240'))
        self.assertEqual({r['date'] for r in flows['records']},{'2024-02-15'})
        usd=next(row for row in flows['records'] if row['currency']=='USD')
        self.assertEqual(D(usd['amount_cad']),D('140'));self.assertEqual(usd['fx_date'],'2024-02-14')
        covered=next(row for row in flows['covered_account_periods'] if row['account_id']==aid)
        self.assertTrue(covered['available']);self.assertEqual(D(covered['external_net_cad']),D('240'))
        self.assertIsNone(flows['full_period_net_external_cad'])
        with sqlite3.connect(self.project/'data/db/portfolio.sqlite3') as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM accounts').fetchone()[0],0)
            self.assertFalse(conn.execute('PRAGMA foreign_key_check').fetchall())
        self.assertGreater(verify_store(self.project)['batches'],0)

    def test_duplicates_conflicts_unknown_accounts_and_missing_fx_fail_closed(self):
        self.seed();aid=investment_accounts(self.project)[0]['account_id']
        path=self.flows([{'account_id':aid,'flow_id':'reviewed-flow'}]);import_cash_flows(self.project,path)
        before=state_fingerprint(self.project)
        self.assertEqual(import_cash_flows(self.project,path)['status'],'duplicate')
        cases=[[{'account_id':aid,'flow_id':'reviewed-flow','amount':'101'}],
               [{'account_id':'src_'+'f'*32,'flow_id':'wrong-account'}],
               [{'account_id':aid,'flow_id':'unsourced-usd','currency':'USD'}]]
        for index,rows in enumerate(cases):
            with self.subTest(rows=rows),self.assertRaises(ValueError):import_cash_flows(self.project,self.flows(rows,'bad'+str(index)+'.csv'))
            self.assertEqual(state_fingerprint(self.project),before)

    def test_manual_payload_and_source_archive_tampering_are_detected(self):
        self.seed();aid=investment_accounts(self.project)[0]['account_id']
        import_cash_flows(self.project,self.flows([{'account_id':aid,'flow_id':'reviewed-flow'}]))
        database=self.project/'data/db/portfolio.sqlite3'
        with sqlite3.connect(database) as conn:
            raw=conn.execute('SELECT payload_json FROM manual_cash_flows').fetchone()[0]
            changed=json.loads(raw);changed['amount_cad']='999'
            conn.execute('UPDATE manual_cash_flows SET payload_json=?',(json.dumps(changed),))
        with self.assertRaisesRegex(ValueError,'manual_flow_integrity'):verify_store(self.project)
        with sqlite3.connect(database) as conn:
            conn.execute('UPDATE manual_cash_flows SET payload_json=?',(raw,))
            source=conn.execute('SELECT path FROM sources ORDER BY id DESC LIMIT 1').fetchone()[0]
        verify_store(self.project)
        archive=self.project/source;archive.chmod(0o600);archive.write_bytes(archive.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'manual_flow_integrity'):verify_store(self.project)

    def test_native_and_canonical_rows_keep_separate_ids_and_one_recorded_subtotal(self):
        self.seed();aid=investment_accounts(self.project)[0]['account_id'];native='a_'+'b'*16
        with sqlite3.connect(self.project/'data/db/portfolio.sqlite3') as conn:
            conn.execute('INSERT INTO accounts VALUES(?,?,?,?)',(native,'non-registered','Synthetic native account','****0011'))
        path=self.flows([{'account_id':native,'flow_id':'legacy-deposit','amount':'75'},
                         {'account_id':aid,'flow_id':'source-withdrawal','flow_type':'withdrawal','amount':'25'}])
        self.assertEqual(import_cash_flows(self.project,path)['imported'],2)
        self.assertEqual(D(self.model()['legacy_cash_flows']['known_recorded_external_cad']),D('50'))
        with sqlite3.connect(self.project/'data/db/portfolio.sqlite3') as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM cash_flows').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM manual_cash_flows').fetchone()[0],1)
        before=state_fingerprint(self.project)
        with self.assertRaises(ValueError):import_cash_flows(self.project,self.flows([{'account_id':aid,'flow_id':'legacy-deposit','amount':'75'}],'conflict.csv'))
        self.assertEqual(state_fingerprint(self.project),before)
