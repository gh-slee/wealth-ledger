"""Copy-verified synthetic CLI adoption, unchanged evidence and failed switching."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

import test_web as foundation
from test_web_exports import complete_publication
from test_web_reports import synthetic_payload
from wealth_ledger.operations import fingerprint, start, set_state

if foundation.AVAILABLE:
    from wealth_ledger.web.adoption import prepare_adoption, confirm_adoption
    from wealth_ledger.web.backups import database_info, backup_instance, restore_instance, file_hash
    from wealth_ledger.web.storage import Store
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.jobs import digest


@unittest.skipUnless(foundation.AVAILABLE,'Optional Web dependencies are not installed')
class AdoptionTests(unittest.TestCase):
    setUp=foundation.WebTests.setUp
    bootstrap=foundation.WebTests.bootstrap
    login=foundation.WebTests.login
    mutate=foundation.WebTests.mutate
    portfolio=foundation.WebTests.portfolio

    def prepare(self):
        self.login();original=self.portfolio('Invented source');_,project=self.store.portfolio(original)
        payload=synthetic_payload(project);report,folder=complete_publication(self.store,original,payload)
        (project/'reports/latest').symlink_to(folder.name,target_is_directory=True)
        (project/'reports/latest.json').write_text(json.dumps({'path':'reports/'+folder.name,'snapshot_id':1}))
        self.legacy=self.root.parent/'legacy';shutil.copytree(project,self.legacy,symlinks=True)
        (self.legacy/'config/publish.local.toml').write_text('private authorization is never copied')
        (self.legacy/'AGENTS.override.md').write_text('private agent instructions')
        (self.legacy/'work/cache').mkdir(parents=True,exist_ok=True)
        (self.legacy/'work/cache/replaceable.txt').write_text('replaceable cache')
        self.plan=self.root.parent/'private-adoption-plan.json'
        self.before=self.hashes()
        result=prepare_adoption(self.settings,self.legacy,'Adopted synthetic ledger',self.plan)
        self.sha=result['plan_sha256'];self.pid=result['portfolio_id'];return result

    def hashes(self):
        return {p.relative_to(self.legacy).as_posix():file_hash(p) for p in self.legacy.rglob('*') if p.is_file() and p.name!='update.guard'}

    def confirm(self):return confirm_adoption(self.settings,self.plan,self.sha)

    def test_copy_preserves_ids_logical_rows_evidence_reports_settings_and_source(self):
        result=self.prepare();self.assertEqual(result['reports'],1)
        self.assertEqual(self.plan.stat().st_mode&0o777,0o600)
        with patch('urllib.request.urlopen',side_effect=AssertionError('No import or revaluation')):
            response=self.confirm()
        self.assertEqual(response['status'],'adopted');self.assertEqual(self.hashes(),self.before)
        _,target=self.store.portfolio(self.pid)
        self.assertEqual(database_info(target/'data/db/portfolio.sqlite3'),database_info(self.legacy/'data/db/portfolio.sqlite3'))
        self.assertEqual(fingerprint(target),fingerprint(self.legacy))
        self.assertFalse((target/'AGENTS.override.md').exists());self.assertFalse((target/'config/publish.local.toml').exists())
        self.assertFalse((target/'work/cache').exists())
        frozen=self.client.get(f'/api/v1/portfolios/{self.pid}/reports');self.assertEqual(frozen.status_code,200,frozen.text)
        report=frozen.json()['reports'][0]['id']
        self.assertEqual(self.client.get(f'/api/v1/portfolios/{self.pid}/reports/{report}').status_code,200)
        response=self.client.get(f'/api/v1/portfolios/{self.pid}/reports/{report}/bundle.zip')
        self.assertEqual(response.status_code,200,response.text if response.status_code!=200 else '')
        self.assertEqual(self.confirm()['status'],'already_adopted')
        archive=self.root.parent/'private.zip';backup_instance(self.settings,archive)
        settings=WebSettings(self.root.parent/'restored');restore_instance(settings,archive)
        _,restored=Store(settings).portfolio(self.pid)
        self.assertEqual(database_info(target/'data/db/portfolio.sqlite3'),database_info(restored/'data/db/portfolio.sqlite3'))

    def test_changed_source_or_digest_requires_new_preview(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,'plan or engine'):confirm_adoption(self.settings,self.plan,'0'*64)
        (self.legacy/'config/local.toml').write_text('[reporting]\nlocale="zh-TW"\n')
        with self.assertRaisesRegex(ValueError,'Source changed'):self.confirm()
        self.assertFalse((self.root/'portfolios'/self.pid).exists())

    def test_unknown_source_lock_pending_operation_and_symlink_are_not_removed(self):
        self.prepare()
        lock=self.legacy/'work/update.lock';lock.write_text('{"pid":"unknown"}')
        with self.assertRaisesRegex(ValueError,'lock'):self.confirm()
        self.assertTrue(lock.exists());lock.unlink()
        operation=start(self.legacy,{'synthetic':True})
        with self.assertRaisesRegex(ValueError,'unfinished'):prepare_adoption(self.settings,self.legacy,'New',self.root.parent/'new-plan.json')
        set_state(self.legacy,operation,'data_failed')
        outside=self.root.parent/'outside.txt';outside.write_text('retain')
        (self.legacy/'data/raw/escape').symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'symlink'):prepare_adoption(self.settings,self.legacy,'New',self.root.parent/'new-plan.json')
        self.assertEqual(outside.read_text(),'retain')

    def test_install_failure_rolls_back_only_new_target(self):
        self.prepare()
        with patch('wealth_ledger.web.adoption.os.replace',side_effect=OSError('Synthetic install failure')):
            with self.assertRaises(OSError):self.confirm()
        self.assertFalse((self.root/'portfolios'/self.pid).exists());self.assertEqual(self.hashes(),self.before)
        self.assertEqual(self.confirm()['status'],'adopted')

    def test_source_evidence_tamper_and_same_tree_destination_rejected(self):
        self.prepare()
        plan=json.loads(self.plan.read_text());evidence=next(n for n in plan['snapshot']['files'] if n.startswith('data/raw/'))
        path=self.legacy/evidence;path.chmod(0o600);path.write_bytes(b'changed')
        with self.assertRaises(ValueError):prepare_adoption(self.settings,self.legacy,'New',self.root.parent/'tampered-plan.json')
        with self.assertRaises((ValueError,OSError)):prepare_adoption(self.settings,self.root/'portfolios'/self.pid,'New',self.root.parent/'bad-plan.json')

    def test_no_browser_adoption_endpoint_or_host_path_input(self):
        self.login()
        self.assertEqual(self.mutate('POST','/api/v1/adopt',body={'workspace':'/private'}).status_code,404)

    def interrupted_copy(self):
        plan=json.loads(self.plan.read_text());target=self.root/'portfolios'/self.pid
        target.mkdir(mode=0o700)
        for name in plan['snapshot']['directories']:(target/name).mkdir(parents=True,exist_ok=True)
        for name in plan['snapshot']['files']:shutil.copyfile(self.legacy/name,target/name)
        (target/'work').mkdir()
        for name,link in plan['snapshot']['links'].items():(target/name).symlink_to(link,target_is_directory=True)
        receipt=self.root/'admin/adoptions'/f'{self.pid}.json';receipt.parent.mkdir(exist_ok=True)
        receipt.write_text(json.dumps({'plan_sha256':self.sha,'source_root':str(self.legacy),'status':'installing'}))
        return target

    def test_exact_installed_unregistered_copy_can_resume_without_a_second_identity(self):
        self.prepare();target=self.interrupted_copy()
        self.assertEqual(self.confirm()['portfolio_id'],self.pid)
        self.assertEqual(self.confirm()['status'],'already_adopted')
        self.assertEqual(self.hashes(),self.before)
        self.assertEqual(fingerprint(target),fingerprint(self.legacy))

    def test_interrupted_copy_with_unexpected_notes_is_preserved_for_host_review(self):
        self.prepare();target=self.interrupted_copy();note=target/'work/keep.txt';note.write_text('Preserve unexpected local work')
        with self.assertRaisesRegex(ValueError,'unexpected local content'):self.confirm()
        self.assertEqual(note.read_text(),'Preserve unexpected local work')
        self.assertEqual(self.hashes(),self.before)
