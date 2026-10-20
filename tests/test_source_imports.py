"""Automatic source preparation uses real synthetic parsers and explicit choices."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_source_builtin import ROOT, fixture, ALIAS
from test_source_legacy_projection import FX, AT, quote
from test_source_projection import hashes
from test_source_publication import publisher_receipt
from wealth_ledger.source_imports import prepare_import
from wealth_ledger.source_publication import confirm_source_report, load_source_report, frozen_report
from wealth_ledger.source_submission import parse_bindings
from wealth_ledger import operations


class ImportEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-source-entry-"); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.project = self.root/'ledger'; self.project.mkdir()
        self.paths = [self.root/'holdings.csv', self.root/'orders.csv']
        for path,name in zip(self.paths,['wealthsimple-holdings.csv','bull-orders.csv']): path.write_bytes(fixture(name))
        self.options = [{}, {'account_alias':ALIAS}]
        self.directory = self.root/'preview'

    def financial(self):
        return {k:v for k,v in hashes(self.project).items() if not k.startswith("work/")}

    def preview(self, *, paths=None, **kwargs):
        selected = self.paths if paths is None else paths
        return prepare_import(self.project,selected,directory=kwargs.pop('directory',self.directory),
            context_options=kwargs.pop('context_options',self.options if paths is None else ()),
            now=AT,as_of=kwargs.pop('as_of',AT),fx=kwargs.pop('fx',FX),**kwargs)

    def bind(self, result):
        return parse_bindings({'schema_version':1,'bindings':[r['suggested_choice'] for r in result['preview']['account_review']]})

    def approved(self, **kwargs):
        return self.preview(bindings=self.bind(self.preview(**kwargs)), **kwargs)

    def publish(self, result):
        with patch('wealth_ledger.lookthrough.attach_analysis'),patch('wealth_ledger.publishing.publish',side_effect=publisher_receipt):
            return confirm_source_report(self.project,self.directory,result['preview']['approval_sha256'])

    def test_default_contexts_detect_both_sources_and_missing_bindings_are_readonly(self):
        before=self.financial()
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network')):result=self.preview()
        self.assertEqual(result['preview']['status'],'mapping_required');self.assertFalse(self.directory.exists())
        self.assertEqual(self.financial(),before)
        self.assertTrue(all(r['source_reference'].startswith('sha256:') for r in result['preparation']['contexts']))
        self.assertEqual({r['adapter']['provider_id'] for r in result['preparation']['inputs']},{'wealthsimple','bullbitcoin'})

    def test_one_parse_per_preparation_and_confirmation_never_parses(self):
        review=self.preview()
        from wealth_ledger.source_imports import parse_sources
        with patch('wealth_ledger.source_imports.parse_sources',wraps=parse_sources) as parsing:
            result=self.preview(bindings=self.bind(review))
        self.assertEqual(parsing.call_count,1)
        with patch('wealth_ledger.source_submission.parse_sources',side_effect=AssertionError('No reparse')):job=self.publish(result)
        self.assertEqual(job['status'],'published')

    def test_only_holdings_default_uses_actual_snapshot_date(self):
        rates=json.loads((ROOT/'examples/data/fx.json').read_text())
        result=self.preview(paths=[self.paths[0]],as_of=None,fx=rates)
        self.assertEqual(result['preparation']['valuation_policy'],'incoming_holdings_time')
        self.assertNotEqual(result['preparation']['valuation_as_of'],AT)

    def test_only_orders_default_uses_frozen_execution_not_purchase_date(self):
        result=self.preview(paths=[self.paths[1]],context_options=[self.options[1]],as_of=None)
        self.assertEqual(result['preparation']['valuation_policy'],'execution_time')
        self.assertEqual(result['preparation']['valuation_as_of'],AT.replace('Z','+00:00'))

    def test_missing_alias_is_rejected_without_inventing_account_identity(self):
        with self.assertRaises(ValueError):self.preview(paths=[self.paths[1]])
        self.assertEqual(self.financial(),{})

    def test_missing_fx_is_pending_and_not_an_approvable_plan(self):
        review=self.preview()
        result=self.preview(bindings=self.bind(review),fx=None)
        self.assertEqual(result['preview']['status'],'reference_required')
        self.assertEqual(result['preview']['missing_references'],['fx'])
        self.assertFalse(self.directory.exists())

    def test_wallet_total_only_is_frozen_and_committed_once_with_stable_ids(self):
        result=self.preview(paths=[],balance={'quantity_btc':'0.01234567','as_of':AT},btc_price=quote())
        self.assertEqual(result['preview']['status'],'awaiting_confirmation')
        manifest,_=load_source_report(self.project,self.directory,result['preview']['approval_sha256'])
        self.assertEqual(manifest['schema_version'],2)
        self.assertEqual(self.financial(),{})
        job=self.publish(result);saved=operations.get(self.project,job['operation_id'])
        payload=frozen_report(self.project,saved)
        self.assertEqual(payload['source_crypto']['quantity_btc'],'0.01234567')
        self.assertIsNone(payload['source_crypto']['actual_full_cost_cad'])
        self.assertEqual(payload['source_projection']['wallet']['anchor']['record_id'],'B000001')

    def test_balance_with_both_csvs_and_reference_quote_commits_atomically(self):
        review=self.preview()
        result=self.preview(bindings=self.bind(review),balance={'quantity_btc':'0.01234567','as_of':AT},btc_price=quote())
        job=self.publish(result);self.assertEqual(job['status'],'published')
        from wealth_ledger.wallet import records
        self.assertEqual(len(records(self.project,'balance')),1)

    def test_failed_publication_retry_keeps_same_balance_and_frozen_price(self):
        result=self.preview(paths=[],balance={'quantity_btc':'0.01','as_of':AT},btc_price=quote())
        with patch('wealth_ledger.lookthrough.attach_analysis'),patch('wealth_ledger.publishing.publish',side_effect=RuntimeError),self.assertRaises(operations.ReportOperationError):
            confirm_source_report(self.project,self.directory,result['preview']['approval_sha256'])
        from wealth_ledger.source_publication import resume_source_report
        with patch('wealth_ledger.publishing.publish',side_effect=publisher_receipt):resume_source_report(self.project,result['preview']['operation_id'])
        from wealth_ledger.wallet import records
        self.assertEqual(len(records(self.project,'balance')),1)

    def test_saved_facts_only_can_prepare_new_explicit_dated_valuation(self):
        first=self.approved();self.publish(first)
        result=self.preview(paths=[],directory=self.root/'saved-preview')
        self.assertEqual(result['preview']['status'],'awaiting_confirmation')
        self.assertEqual(result['preparation']['inputs'],[])

    def test_fetch_public_references_is_explicit_and_saved_only_never_fetches(self):
        with patch('wealth_ledger.fx.resolve_rates',return_value=FX) as fetch:
            self.preview(paths=[],fx=None)
            fetch.assert_not_called()
            result=self.preview(paths=[],fx=None,reference_policy='fetch_public')
            self.assertEqual(result['preview']['status'],'awaiting_confirmation');fetch.assert_called_once()

        # First-time public quote caching must remain a recognizable, unbooked
        # workspace, then support the exact same offline quote without a fetch.
        import hashlib
        fresh=self.root/'cached-ledger';fresh.mkdir()
        def cache_price(project, at):
            value=quote();key=datetime.fromisoformat(at).strftime('%Y-%m-%dT%H%M%S%z')
            evidence=project/'data/prices/evidence'/('coinbase-'+key+'.json')
            evidence.parent.mkdir(parents=True);evidence.write_bytes(b'[]')
            value.update(evidence_path=str(evidence.relative_to(project)),evidence_sha256=hashlib.sha256(b'[]').hexdigest())
            (project/'data/prices'/('btc-usd-'+key+'.json')).write_text(json.dumps(value))
            return value
        options={'now':AT,'as_of':AT,'fx':FX,'balance':{'quantity_btc':'0.01','as_of':AT}}
        with patch('wealth_ledger.prices.resolve_btc_price',side_effect=cache_price) as fetch_price:
            result=prepare_import(fresh,directory=self.root/'cache-review',reference_policy='fetch_public',**options)
            self.assertEqual(result['preview']['status'],'awaiting_confirmation')
            result=prepare_import(fresh,directory=self.root/'offline-cache-review',**options)
            self.assertEqual(result['preview']['status'],'awaiting_confirmation');fetch_price.assert_called_once()
        self.assertFalse((fresh/'data/db/portfolio.sqlite3').exists())

    def test_bad_context_future_cutoff_and_balance_after_cutoff_fail_without_facts(self):
        for change in ({'context_options':[{'module':'untrusted'}]}, {'as_of':'2034-01-01T00:00:00Z'},
                       {'balance':{'quantity_btc':'1','as_of':'2024-03-02T00:00:00Z'}}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.preview(paths=[],**change)
        self.assertEqual(self.financial(),{})

    def test_cli_regular_update_supports_mapping_review_and_exact_confirmation(self):
        import subprocess, sys
        from wealth_ledger.core import import_holdings
        raw=self.paths[0].read_bytes().replace(b'VEQT',b'DEMO-ETF').replace(b'QQQ',b'DEMO-ETF-US');self.paths[0].write_bytes(raw)
        fx=self.root/'fx.json';fx.write_text(json.dumps(FX))
        command=[sys.executable,str(ROOT/'scripts/update.py'),'--workspace',str(self.project)]
        args=[str(self.paths[0]),'--plan-directory',str(self.directory),'--fx-file',str(fx),'--valuation-as-of',AT]
        result=subprocess.run(command+args,capture_output=True,text=True,timeout=60);self.assertEqual(result.returncode,0,result.stderr)
        reviewed=json.loads(result.stdout);bindings=self.root/'bindings.json'
        bindings.write_text(json.dumps({'schema_version':1,'bindings':[row['suggested_choice'] for row in reviewed['preview']['account_review']]}))
        result=subprocess.run(command+args+['--source-bindings',str(bindings)],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr);ready=json.loads(result.stdout)
        self.assertFalse((self.project/'data/db/portfolio.sqlite3').exists())
        result=subprocess.run(command+['--confirm-source-preview',str(self.directory),'--approval-sha256',ready['preview']['approval_sha256']],capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['status'],'published')

    def test_balances_and_saved_data_retry_use_original_application_service_route(self):
        from wealth_ledger.application import ApplicationService
        from wealth_ledger.workspace import resolve_workspace
        result=self.preview(paths=[],balance={'quantity_btc':'0.01','as_of':AT},btc_price=quote());job=self.publish(result)
        service=ApplicationService(resolve_workspace(explicit=self.project))
        self.assertEqual(service.update({},resume=job['operation_id'])['status'],'already_published')

    def test_preparatory_workspace_never_accepts_other_files_or_escapes(self):
        from wealth_ledger.workspace import resolve_workspace
        work=self.project/'work';work.mkdir();(work/'update.guard').touch()
        self.assertEqual(resolve_workspace(explicit=self.project).workspace_root,self.project)
        prices=self.project/'data/prices/evidence';prices.mkdir(parents=True)
        (prices/'coinbase-2024-03-01T000000+0000.json').write_text('[]')
        self.assertEqual(resolve_workspace(explicit=self.project).workspace_root,self.project)
        (prices/'coinbase-arbitrary.json').write_text('[]')
        with self.assertRaises(ValueError):resolve_workspace(explicit=self.project)
        (prices/'coinbase-arbitrary.json').unlink()
        (work/'unrelated.txt').write_text('synthetic-unrelated')
        with self.assertRaises(ValueError):resolve_workspace(explicit=self.project)

    def test_later_wallet_observation_survives_an_older_incoming_holdings_default(self):
        from wealth_ledger.wallet import add_balance
        from wealth_ledger.source_submission import mapping_review
        add_balance(self.project,'0.01',AT,now=AT)
        # A fresh review first establishes the explicit source mapping choices.
        review=self.preview(paths=[self.paths[0]],as_of=None)
        result=self.preview(paths=[self.paths[0]],as_of=None,bindings=self.bind(review),btc_price=quote())
        self.assertEqual(result['preparation']['valuation_as_of'],AT.replace('Z','+00:00'))
        self.assertEqual(result['preparation']['valuation_policy'],'execution_time')
