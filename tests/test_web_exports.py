"""Frozen export scope, archive links, exact money, auth and hostile input handling."""
from contextlib import closing
from datetime import date
import csv
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import test_web as foundation
from test_web_reports import synthetic_payload, publish_fixture

if foundation.AVAILABLE:
    from wealth_ledger.web.storage import Store


def complete_publication(store, pid, payload):
    report, path = publish_fixture(store, pid, payload)
    with closing(store.connect()) as conn:
        operation = conn.execute("SELECT core_operation_id FROM jobs WHERE id=?",(report,)).fetchone()[0]
    folder = path.parent
    files={"report.md":b"![chart](charts/allocation.png)\n", "report.pdf":b"synthetic PDF bytes",
           "portfolio.ods":b"synthetic ODS bytes", "charts/allocation.png":b"synthetic PNG bytes"}
    for name,raw in files.items():
        target=folder/name;target.parent.mkdir(exist_ok=True);target.write_bytes(raw)
    hashes={p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
    (folder/'manifest.json').write_text(json.dumps({'bundle_files':hashes,'data_sha256':hashes['data.json'],
        'import':{'operation_id':operation},'snapshot_id':payload['meta']['snapshot_id'],'workbook_validation':{}}))
    for p in folder.rglob('*'):
        if p.is_file():store.register_artifact(pid,report,p.relative_to(folder.parents[1]).as_posix())
    return report, folder


@unittest.skipUnless(foundation.AVAILABLE,"Optional Web dependencies are not installed")
class ExportTests(unittest.TestCase):
    setUp=foundation.WebTests.setUp
    bootstrap=foundation.WebTests.bootstrap
    login=foundation.WebTests.login
    mutate=foundation.WebTests.mutate
    portfolio=foundation.WebTests.portfolio

    def prepare(self):
        self.login();self.pid=self.portfolio()
        _,self.project=self.store.portfolio(self.pid)
        self.payload=synthetic_payload(self.project)
        self.report,self.folder=complete_publication(self.store,self.pid,self.payload)
        self.prefix=f'/api/v1/portfolios/{self.pid}/reports/{self.report}'

    def test_zip_preserves_every_registered_byte_and_markdown_relative_links(self):
        self.prepare()
        before={p.relative_to(self.project).as_posix():p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        with patch('urllib.request.urlopen',side_effect=AssertionError('No reference downloads')):
            response=self.client.get(self.prefix+'/bundle.zip')
        self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else '')
        self.assertIn('no-store',response.headers['cache-control'])
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in archive.namelist():self.assertEqual(archive.read(name),(self.folder/name).read_bytes())
            self.assertIn('charts/allocation.png',archive.namelist())
            self.assertIn('portfolio.ods',archive.namelist())
        self.assertEqual(before,{p.relative_to(self.project).as_posix():p.read_bytes() for p in self.project.rglob('*') if p.is_file()})

    def test_json_csv_exact_values_unknowns_ranges_and_formula_text(self):
        self.prepare()
        self.payload['positions'][0]['name']='=SYNTHETIC_FORMULA()'
        self.payload['positions'][0]['avg_cost']=None
        self.payload['history'][0]['as_of']='2024-02-01T00:30:00+00:00'
        raw=json.dumps(self.payload).encode();(self.folder/'data.json').write_bytes(raw)
        with self.store.transaction() as conn:
            conn.execute('UPDATE artifacts SET sha256=?,byte_size=? WHERE portfolio_id=? AND relative_path LIKE ?',
                         (hashlib.sha256(raw).hexdigest(),len(raw),self.pid,'%/data.json'))
        response=self.client.get(self.prefix+'/export',params={'dataset':'holdings','format':'json'})
        self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertIsNone(result['rows'][0]['avg_cost'])
        self.assertEqual(result['rows'][0]['market_cad'],self.payload['positions'][0]['market_cad'])
        self.assertEqual(result['rows'][0]['name'],'=SYNTHETIC_FORMULA()')
        response=self.client.get(self.prefix+'/export',params={'dataset':'holdings'})
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['name'],"'=SYNTHETIC_FORMULA()")
        self.assertEqual(rows[0]['avg_cost'],'')
        self.assertEqual(rows[0]['market_cad'],self.payload['positions'][0]['market_cad'])
        for dataset in ('history','cash_flows','btc_monthly'):
            response=self.client.get(self.prefix+'/export',params={'dataset':dataset,'format':'json','start':'2099-01-01'})
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['rows'],[])
        response=self.client.get(self.prefix+'/export',params={'dataset':'btc_monthly','format':'json','start':'2024-01-31','end':'2024-01-31'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['range_semantics'],'inclusive months')
        self.assertTrue(all(row['month']=='2024-01' for row in response.json()['rows']))
        boundary=self.client.get(self.prefix+'/export',params={'dataset':'history','format':'json','start':'2024-01-31','end':'2024-01-31'})
        self.assertEqual(len(boundary.json()['rows']),1)
        for params in ({'dataset':'holdings','start':'2024-01-01'}, {'dataset':'history','start':'2024-02-01','end':'2024-01-01'}, {'dataset':'arbitrary'}, {'dataset':'history','start':'invalid'}):
            self.assertEqual(self.client.get(self.prefix+'/export',params=params).status_code,422)

    def test_scope_auth_pending_integrity_and_limits_fail_closed(self):
        self.prepare()
        other=self.portfolio('Other invented ledger')
        for suffix in ('bundle.zip','export?dataset=holdings'):
            self.assertEqual(self.client.get(f'/api/v1/portfolios/{other}/reports/{self.report}/'+suffix).status_code,404)
        from wealth_ledger.web.jobs import Jobs
        Jobs(self.store).state(self.report,'data_committed')
        self.assertEqual(self.client.get(self.prefix+'/bundle.zip').status_code,404)
        Jobs(self.store).state(self.report,'published',result={'valuation_as_of':self.payload['meta']['as_of']})
        with patch('wealth_ledger.web.exports.MAX_BUNDLE',1):
            self.assertEqual(self.client.get(self.prefix+'/bundle.zip').status_code,413)
            self.assertEqual(self.client.get(self.prefix+'/export?dataset=holdings').status_code,413)
        (self.folder/'report.pdf').write_bytes(b'changed')
        self.assertEqual(self.client.get(self.prefix+'/bundle.zip').status_code,409)
        self.mutate('POST','/api/v1/auth/logout')
        self.assertEqual(self.client.get(self.prefix+'/bundle.zip').status_code,401)
        self.assertEqual(self.client.get(self.prefix+'/export?dataset=holdings').status_code,401)
