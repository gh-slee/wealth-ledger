"""Private synthetic instance backup/restore, concurrency, recovery and hostile ZIPs."""
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
import warnings
import zipfile

import test_web as foundation
from test_web_reports import synthetic_payload
from test_web_exports import complete_publication

if foundation.AVAILABLE:
    from wealth_ledger.web.backups import backup_instance, restore_instance, database_info
    from wealth_ledger.web.config import WebSettings
    from wealth_ledger.web.storage import Store, contained, WebError
    from wealth_ledger.web.maintenance import maintenance, instance_activity, clear_maintenance
    from wealth_ledger.operations import project_lock, fingerprint
    from wealth_ledger.locking import LockBusy, file_lock

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(foundation.AVAILABLE,'Optional Web dependencies are not installed')
class BackupTests(unittest.TestCase):
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
        latest=self.project/'reports/latest';latest.symlink_to(self.folder.name,target_is_directory=True)
        (self.project/'reports/latest.json').write_text(json.dumps({'path':'reports/'+self.folder.name,'snapshot_id':1}))
        self.archive=self.root.parent/'private-backup.zip'
        self.target=WebSettings(self.root.parent/'restored')

    def backup(self):
        return backup_instance(self.settings,self.archive)

    def rewrite(self, changes=None, extra=None, manifest_change=None):
        with zipfile.ZipFile(self.archive) as src:
            contents={i.filename:src.read(i) for i in src.infolist()}
        if changes:contents.update(changes)
        if manifest_change:
            manifest=json.loads(contents['backup-manifest.json']);manifest_change(manifest)
            contents['backup-manifest.json']=json.dumps(manifest).encode()
        bad=self.root.parent/'modified.zip'
        with zipfile.ZipFile(bad,'w',compression=zipfile.ZIP_DEFLATED) as out:
            for name,raw in contents.items():out.writestr(name,raw)
            if extra:out.writestr(*extra)
        return bad

    def test_full_roundtrip_keeps_finance_evidence_settings_reports_and_revokes_sessions(self):
        self.prepare()
        self.client.post(f'/api/v1/portfolios/{self.pid}/uploads?kind=csv&filename=example.csv',
            content=(ROOT/'examples/data/wealthsimple-holdings.csv').read_bytes(),
            headers={'Origin':foundation.ORIGIN,'X-CSRF-Token':self.csrf,'Content-Type':'text/csv'})
        initial=fingerprint(self.project)
        result=self.backup();self.assertEqual(result['status'],'backup_created')
        self.assertEqual(self.archive.stat().st_mode & 0o777,0o600)
        with zipfile.ZipFile(self.archive) as archive:
            manifest=json.loads(archive.read('backup-manifest.json'))
            self.assertIn('admin/app.sqlite3',manifest['databases'])
            self.assertIn(f'portfolios/{self.pid}/data/db/portfolio.sqlite3',manifest['databases'])
            self.assertFalse(any(p.endswith('.guard') for p in manifest['files']))
        saved=self.archive.read_bytes()
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network during restore')):
            response=restore_instance(self.target,self.archive)
        self.assertTrue(response['sessions_revoked']);self.assertTrue(response['financial_values_verified'])
        restored=Store(self.target);_,project=restored.portfolio(self.pid)
        with closing(restored.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],0)
        self.assertEqual(fingerprint(project),initial)
        for name,metadata in manifest['files'].items():
            if name.startswith('portfolios/'):
                self.assertEqual(hashlib.sha256((self.target.data_root/name).read_bytes()).hexdigest(),metadata['sha256'])
        self.assertEqual(self.archive.read_bytes(),saved)
        self.assertEqual((project/'reports/latest/data.json').read_bytes(),(self.folder/'data.json').read_bytes())
        from wealth_ledger.web.api import create_app
        from fastapi.testclient import TestClient
        with TestClient(create_app(self.target),base_url=foundation.ORIGIN) as client:
            client.cookies.update(self.client.cookies)
            self.assertEqual(client.get('/api/v1/portfolios').status_code,401)
            self.login(client)
            self.assertEqual(client.get(f'/api/v1/portfolios/{self.pid}/reports/{self.report}').status_code,200)
            self.assertEqual(client.get(f'/api/v1/portfolios/{self.pid}/reports/{self.report}/bundle.zip').status_code,200)
        with closing(restored.connect()) as conn:self.assertTrue(conn.execute('SELECT username FROM owner').fetchone())

    def test_restore_refuses_nonempty_target_and_never_overwrites_archive(self):
        self.prepare();self.backup()
        with self.assertRaisesRegex(ValueError,'never overwritten'):self.backup()
        self.target.data_root.mkdir();sentinel=self.target.data_root/'keep.txt';sentinel.write_text('synthetic existing data')
        with self.assertRaisesRegex(ValueError,'empty'):restore_instance(self.target,self.archive)
        self.assertEqual(sentinel.read_text(),'synthetic existing data')
        with self.assertRaisesRegex(ValueError,'outside'):backup_instance(self.settings,self.root/'backup.zip')

    def test_hostile_or_corrupt_archives_leave_target_empty(self):
        self.prepare();self.backup()
        cases=[{'extra':('../escape',b'no')},{'extra':('/absolute',b'no')},{'extra':('instance/admin/../escape',b'no')},
               {'extra':('instance\\escape',b'no')},{'extra':('instance/admin/instance.json',b'duplicate')},
               {'changes':{'instance/secrets/csrf.key':b'changed'}},
               {'manifest_change':lambda m:m.update(version=999)}, {'manifest_change':lambda m:m.update(engine='unsupported-code')},
               {'manifest_change':lambda m:m['files'].pop('secrets/csrf.key')},
               {'manifest_change':lambda m:m['databases']['admin/app.sqlite3'].update(logical_sha256='incorrect')}]
        link=zipfile.ZipInfo('instance/symlink');link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
        cases.append({'extra':(link,b'../../outside')})
        for case in cases:
            with self.subTest(case=list(case)):
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',UserWarning);bad=self.rewrite(**case)
                with self.assertRaises((ValueError,zipfile.BadZipFile)):restore_instance(self.target,bad)
                self.assertEqual(list(self.target.data_root.iterdir()),[])
        self.assertFalse((self.root.parent/'escape').exists())
        with patch('wealth_ledger.web.backups.MAX_TOTAL',1):
            with self.assertRaises(ValueError):restore_instance(self.target,self.archive)
        self.assertEqual(list(self.target.data_root.iterdir()),[])

    def test_maintenance_blocks_http_cli_and_claims_and_clears_after_failure(self):
        self.prepare()
        from wealth_ledger.web.worker import execute_job
        with maintenance(self.root):
            response=self.client.get('/healthz');self.assertEqual(response.status_code,503)
            self.assertEqual(response.json()['error']['code'],'maintenance')
            self.assertIn('no-store',response.headers['cache-control'])
            with self.assertRaises(LockBusy):
                with project_lock(self.project):pass
            with self.assertRaises(LockBusy):execute_job(self.settings,self.report)
            with self.assertRaises(LockBusy):clear_maintenance(self.root)
        self.assertEqual(self.client.get('/healthz').status_code,200)
        with patch('wealth_ledger.web.backups.snapshot_database',side_effect=ValueError('synthetic interruption')):
            with self.assertRaises(ValueError):self.backup()
        self.assertFalse(self.archive.exists());self.assertFalse((self.root/'admin/maintenance.json').exists())
        (self.root/'admin/maintenance.json').write_text('{"token":"synthetic-crashed-coordinator"}')
        self.assertEqual(self.client.get('/healthz').status_code,503)
        clear_maintenance(self.root)
        self.assertEqual(self.client.get('/healthz').status_code,200)

    def test_maintenance_drains_existing_activity_but_refuses_new_activity(self):
        self.prepare();started=threading.Event();release=threading.Event()
        def active():
            with instance_activity(self.root):
                started.set();release.wait(3)
                # Existing work may acquire its nested portfolio lock while draining.
                with project_lock(self.project):pass
        thread=threading.Thread(target=active);thread.start();self.assertTrue(started.wait(2))
        try:
            with self.assertRaises(LockBusy):
                with maintenance(self.root,timeout=0):pass
            release.set();thread.join(3);self.assertFalse(thread.is_alive())
            with maintenance(self.root,timeout=1):pass
        finally:
            release.set();thread.join(3)

    def test_sqlite_wal_snapshot_includes_committed_pages_and_financial_foreign_keys(self):
        self.prepare()
        with closing(sqlite3.connect(self.project/'data/db/portfolio.sqlite3')) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE synthetic_wal_check(value TEXT)');conn.execute('INSERT INTO synthetic_wal_check VALUES (?)',('0.00000000',));conn.commit()
            self.backup();restore_instance(self.target,self.archive)
        _,project=Store(self.target).portfolio(self.pid)
        with closing(sqlite3.connect(project/'data/db/portfolio.sqlite3')) as conn:
            self.assertEqual(conn.execute('SELECT value FROM synthetic_wal_check').fetchone()[0],'0.00000000')

    def test_restore_publication_interruption_maps_runtime_path_without_reimporting(self):
        self.prepare()
        from wealth_ledger.web.jobs import Jobs
        from wealth_ledger.application import ApplicationService
        from wealth_ledger.workspace import resolve_workspace
        from wealth_ledger.web.worker import reconcile
        jobs=Jobs(self.store)
        with self.store.transaction() as conn:
            row=jobs._insert(conn,self.pid,'update',{},'synthetic-recovery-key','synthetic')
        service=ApplicationService(resolve_workspace(explicit=self.project))
        def publisher(project_root,payload,result,run):
            folder=self.project/'reports/recovery/r1';folder.mkdir(parents=True)
            files={'data.json':json.dumps(payload).encode(),'report.md':b'synthetic report','report.pdf':b'synthetic PDF','portfolio.ods':b'synthetic ODS'}
            for name,raw in files.items():(folder/name).write_bytes(raw)
            hashes={k:hashlib.sha256(v).hexdigest() for k,v in files.items()}
            (folder/'manifest.json').write_text(json.dumps({'bundle_files':hashes,'data_sha256':hashes['data.json'],
                'import':{'operation_id':row['core_operation_id']},'snapshot_id':payload['meta']['snapshot_id'],'workbook_validation':{}}))
            return {'output':str(folder),'snapshot_id':payload['meta']['snapshot_id']}
        with patch('wealth_ledger.application.publish',side_effect=publisher):
            service.update({'snapshot_id':1,'wealthsimple_only':True},operation_id=row['core_operation_id'])
        jobs.state(row['id'],'data_committed')
        before=fingerprint(self.project);self.backup();restore_instance(self.target,self.archive)
        restored=Store(self.target);_,project=restored.portfolio(self.pid)
        with patch('urllib.request.urlopen',side_effect=AssertionError('Recovery must not fetch')):
            reconcile(restored)
        self.assertEqual(Jobs(restored).internal(row['id'])['status'],'published')
        self.assertEqual(fingerprint(project),before)
        saved=ApplicationService(resolve_workspace(explicit=project)).operation(row['core_operation_id'])
        self.assertIn(str(self.project),saved['output']['output'])

    def test_missing_original_evidence_or_unexpected_symlink_prevents_backup(self):
        self.prepare()
        with closing(sqlite3.connect(self.project/'data/db/portfolio.sqlite3')) as conn:
            source=conn.execute('SELECT path FROM sources LIMIT 1').fetchone()[0]
        target=self.project/source; raw=target.read_bytes();target.unlink()
        with self.assertRaisesRegex(ValueError,'evidence'):self.backup()
        self.assertFalse(self.archive.exists())
        target.write_bytes(raw)
        outside=self.root.parent/'synthetic-outside.txt';outside.write_text('example only')
        (self.project/'unsafe-link').symlink_to(outside)
        with self.assertRaises(ValueError):self.backup()
        self.assertFalse(self.archive.exists())

    def test_source_named_like_a_runtime_file_is_preserved(self):
        self.prepare()
        with closing(sqlite3.connect(self.project/'data/db/portfolio.sqlite3')) as conn:
            row=conn.execute('SELECT id,path FROM sources LIMIT 1').fetchone()
            original=self.project/row[1]
            renamed=original.with_name('synthetic.guard');original.rename(renamed)
            conn.execute('UPDATE sources SET path=? WHERE id=?',(renamed.relative_to(self.project).as_posix(),row[0]));conn.commit()
        self.backup();restore_instance(self.target,self.archive)
        _,project=Store(self.target).portfolio(self.pid)
        self.assertEqual((project/renamed.relative_to(self.project)).read_bytes(),renamed.read_bytes())

    def test_cache_symlink_cannot_redirect_private_staging(self):
        self.prepare()
        cache=self.root/'cache';cache.rmdir()
        outside=self.root.parent/'outside-cache';outside.mkdir()
        cache.symlink_to(outside,target_is_directory=True)
        with self.assertRaises((ValueError,WebError)):self.backup()
        self.assertEqual(list(outside.iterdir()),[])
        response=self.client.get(f'/api/v1/portfolios/{self.pid}/reports/{self.report}/bundle.zip')
        self.assertEqual(response.status_code,404)
        self.assertEqual(list(outside.iterdir()),[])

    def test_unknown_legacy_lock_is_not_silently_removed_by_backup(self):
        self.prepare()
        marker=self.project/'work/update.lock';marker.parent.mkdir(exist_ok=True)
        original=b'{"legacy_owner":"synthetic-review-required"}';marker.write_bytes(original)
        with self.assertRaisesRegex(ValueError,'legacy'):self.backup()
        self.assertEqual(marker.read_bytes(),original)
        self.assertFalse(self.archive.exists())
        self.assertFalse((self.root/'admin/maintenance.json').exists())

    def test_restore_install_failure_leaves_no_active_instance(self):
        self.prepare();self.backup()
        from wealth_ledger.web import backups
        original=backups.private_write
        def interrupted(path,raw):
            if path == self.target.data_root/'admin/instance.json':
                raise OSError('Synthetic publication interruption')
            return original(path,raw)
        with patch.object(backups,'private_write',side_effect=interrupted):
            with self.assertRaises(OSError):restore_instance(self.target,self.archive)
        self.assertEqual(list(self.target.data_root.iterdir()),[])
        self.assertTrue(self.archive.is_file())
        restore_instance(self.target,self.archive)
        self.assertTrue((self.target.data_root/'admin/instance.json').is_file())

    def test_host_cli_stdout_stdin_roundtrip_on_empty_instance(self):
        self.prepare()
        command=[sys.executable,str(ROOT/'scripts/web.py')]
        environment={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
        backup=subprocess.run([*command,'--data-root',str(self.root),'backup','--stdout'],capture_output=True,env=environment)
        self.assertEqual(backup.returncode,0,backup.stderr.decode());self.assertTrue(backup.stdout.startswith(b'PK'))
        restored=subprocess.run([*command,'--data-root',str(self.target.data_root),'restore','--stdin'],input=backup.stdout,capture_output=True,env=environment)
        self.assertEqual(restored.returncode,0,restored.stderr.decode())
        self.assertEqual(json.loads(restored.stdout)['status'],'restored')
        self.assertEqual(fingerprint(Store(self.target).portfolio(self.pid)[1]),fingerprint(self.project))
