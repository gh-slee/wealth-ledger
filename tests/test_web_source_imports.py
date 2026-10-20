"""Regular parser entry prepares exact Web approvals using synthetic evidence."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_web as foundation
import test_web_source_reports as publication
from test_source_legacy_projection import FX, AT, quote
from test_source_publication import publisher_receipt
from wealth_ledger import operations

if publication.submission.AVAILABLE:
    from wealth_ledger.web.jobs import Jobs
    from wealth_ledger.web.worker import execute_job


@unittest.skipUnless(publication.submission.AVAILABLE,'Optional Web dependencies are not installed')
class SourceImportWebTests(unittest.TestCase):
    setUp=foundation.WebTests.setUp
    bootstrap=foundation.WebTests.bootstrap
    login=foundation.WebTests.login
    mutate=foundation.WebTests.mutate
    portfolio=foundation.WebTests.portfolio
    confirm=publication.SourceReportWebTests.confirm
    view=publication.SourceReportWebTests.view

    def prepare(self):
        publication.SourceReportWebTests.prepare(self,actual=True)
        self.options=[{}, {'account_alias':publication.submission.CONTEXTS[1].account_alias}]

    def reference(self, value, kind):
        response=self.client.post(self.prefix+'/uploads',params={'kind':kind,'filename':kind+'.json'},content=json.dumps(value),
            headers={'Origin':foundation.ORIGIN,'X-CSRF-Token':self.csrf,'Content-Type':'application/json'})
        self.assertEqual(response.status_code,201,response.text);return response.json()['id']

    def preview(self, body, key='synthetic-automatic-entry', expected=202):
        response=self.mutate('POST',self.prefix+'/source-import-previews',body=body,headers={'Idempotency-Key':key})
        self.assertEqual(response.status_code,expected,response.text)
        if expected!=202:return response.json()
        execute_job(self.settings,response.json()['id'])
        return self.jobs.view(self.jobs.get(self.pid,response.json()['id']))

    def base(self):
        return {'upload_ids':self.uploads,'context_options':self.options,'as_of':AT}

    def test_mapping_then_reference_then_exact_confirmation_never_commits_early(self):
        self.prepare();body=self.base();first=self.preview(body)
        self.assertEqual(first['result']['preview']['status'],'mapping_required')
        self.assertFalse((self.project/'data/db/portfolio.sqlite3').exists())
        choices=[r['suggested_choice'] for r in first['result']['preview']['account_review']]
        pending=self.preview({**body,'bindings':choices},key='mapped-no-references')
        self.assertEqual(pending['result']['preview']['status'],'reference_required')
        self.confirm({**pending,'result':pending['result']['preview']},expected=409)
        fx_id=self.reference(FX,'fx')
        ready=self.preview({**body,'upload_ids':[*self.uploads,fx_id],'bindings':choices},key='mapped-and-referenced')
        self.assertEqual(ready['status'],'ready',ready['error_code'])
        self.assertEqual(ready['result']['preview']['status'],'awaiting_confirmation')
        self.assertFalse((self.project/'data/db/portfolio.sqlite3').exists())
        job=self.confirm({**ready,'result':ready['result']['preview']})
        self.assertEqual(job['status'],'published',job['error_code'])
        self.assertEqual(self.view(job)['source_basis']['report_model'],'source-neutral-1')

    def test_btc_total_alone_uses_same_approval_and_balance_is_not_a_contribution(self):
        self.prepare();fx=self.reference(FX,'fx');price=self.reference(quote(),'price')
        ready=self.preview({'upload_ids':[fx,price],'as_of':AT,'balance':{'quantity_btc':'0.01234567','as_of':AT}})
        self.assertEqual(ready['status'],'ready',ready['error_code'])
        self.assertEqual(ready['result']['preview']['balance']['quantity_btc'],'0.01234567')
        job=self.confirm({**ready,'result':ready['result']['preview']})
        self.assertEqual(job['status'],'published',job['error_code'])
        view=self.view(job)
        self.assertEqual(view['btc']['quantity_btc'],'0.01234567')
        self.assertIsNone(view['source_basis']['complete_contributions_cad'])
        self.assertEqual([row['provider'] for row in view['source_dates']],['wallet'])

    def test_explicit_reference_fetch_updates_preview_fingerprint_then_confirms(self):
        self.prepare()
        def synthetic_cache(root, day):
            path=Path(root)/'data/fx'/f'{day}.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(FX));return FX
        with patch('wealth_ledger.fx.resolve_rates',side_effect=synthetic_cache) as fetch:
            first=self.preview({'reference_policy':'fetch_public','as_of':AT})
        self.assertEqual(first['status'],'ready',first['error_code']);fetch.assert_called_once()
        job=self.confirm({**first,'result':first['result']['preview']})
        self.assertEqual(job['status'],'published',job['error_code'])

    def test_closed_context_source_selection_upload_scopes_and_precision(self):
        self.prepare()
        self.preview({**self.base(),'context_options':[{'module':'untrusted'}]},expected=422)
        self.preview({**self.base(),'context_options':[{}]},key='wrong-context-count',expected=422)
        self.preview({'balance':{'quantity_btc':0.1,'as_of':AT}},key='numeric-btc',expected=422)
        self.preview({'reference_policy':'silent_network'},key='bad-reference-policy',expected=422)
        bad=self.preview({**self.base(),'selections':{'1':'untrusted.adapter'}},key='unknown-adapter')
        self.assertEqual(bad['status'],'blocked')
        self.assertEqual(operations.list_operations(self.project),[])

    def test_settings_change_stales_automatically_prepared_approval(self):
        self.prepare();fx=self.reference(FX,'fx')
        ready=self.preview({'upload_ids':[fx],'as_of':AT})
        self.assertEqual(ready['status'],'ready')
        (self.project/'config/local.toml').write_text('[reporting]\nlocale="zh-TW"\n')
        self.confirm({**ready,'result':ready['result']['preview']},expected=409)
        self.assertEqual(operations.list_operations(self.project),[])
