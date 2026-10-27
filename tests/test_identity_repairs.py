"""Regression evidence for independent implementation-review findings."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import gc
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
import uuid
from unittest.mock import patch

from test_identity_support import IdentityCase
from wealth_ledger.persistence.context import Database,execute
from wealth_ledger.persistence.errors import PersistenceError
from wealth_ledger.persistence.identity import IdentityError,IdentityStore
from wealth_ledger.persistence.migration import migrate,migrate_identity,finalize_identity_restore
from wealth_ledger.web_v2.auth import Auth,digest
from wealth_ledger.web_v2.config import Settings


class IdentityReviewRepairs(IdentityCase):
    def test_database_owner_roles_refuse_startup_readiness_and_operator_changes(self):
        from fastapi.testclient import TestClient
        from wealth_ledger.web_v2.api import create_app
        import subprocess
        self.bootstrap()
        settings=Settings(self.configs['identity'],self.configs['runtime'],self.key,'http://localhost')
        app=create_app(settings)
        owner=self.config['migration_role']
        def admin(statement):
            subprocess.run(['docker','exec',self.config['container'],'psql','-U','postgres','-d','postgres',
                            '-v','ON_ERROR_STOP=1','-c',statement],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        with TestClient(app,base_url='http://localhost') as client:
            for name in ['identity_role','runtime_role']:
                role=self.config[name]
                before=self.operator.status()
                audit=self.scalar('SELECT count(*) FROM wl_identity.auth_audit')
                admin('ALTER DATABASE "'+self.name+'" OWNER TO "'+role+'"')
                # Keep the operator independently authorized, so refusal exercises
                # the login-role guard rather than only the operator CREATE guard.
                admin('GRANT CREATE ON DATABASE "'+self.name+'" TO "'+owner+'"')
                try:
                    with self.assertRaisesRegex(IdentityError,'instance_not_ready'):Auth(settings)
                    with self.assertRaisesRegex(IdentityError,'instance_not_ready'):app.state.auth.ready()
                    response=client.get('/readyz')
                    self.assertEqual(response.status_code,503)
                    self.assertNotIn(role,response.text)
                    with self.assertRaisesRegex(PersistenceError,'migration_role_required'):
                        migrate_identity(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
                    with self.assertRaisesRegex(PersistenceError,'migration_role_required'):
                        finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
                    self.assertEqual(self.operator.status(),before)
                    self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.auth_audit'),audit)
                finally:
                    admin('ALTER DATABASE "'+self.name+'" OWNER TO "'+owner+'"')
                self.assertTrue(app.state.auth.ready())

    def test_missing_revision_denies_direct_gateway_and_already_running_http(self):
        from fastapi.testclient import TestClient
        from wealth_ledger.web_v2.api import create_app
        app=create_app(Settings(self.configs['identity'],self.configs['runtime'],self.key,'http://localhost'))
        with TestClient(app,base_url='http://localhost') as client:
            self.sql('DELETE FROM wl_pg.alembic_version')
            count=self.scalar('SELECT count(*) FROM wl_identity.sessions')
            with self.assertRaisesRegex(IdentityError,'instance_not_ready'):
                self.gateway.call('issue_anonymous_v1','a'*64)
            self.assertEqual(client.get('/api/v2/auth/csrf').status_code,503)
            self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.sessions'),count)

    def test_null_expected_versions_cannot_bypass_reset_or_admin_fences(self):
        token,user=self.bootstrap();nonce=digest(self.anonymous())
        self.operator.call('reset_user_v1',user.user_id,self.encoded)
        with self.assertRaisesRegex(IdentityError,'credentials_changed'):
            self.gateway.call('login_commit_v1',user.user_id,user.credential_version,nonce,'b'*64)
        with self.assertRaisesRegex(IdentityError,'instance_not_ready'):
            self.gateway.call('login_commit_v1',user.user_id,None,nonce,'b'*64)
        self.assertEqual(self.scalar("SELECT count(*) FROM wl_identity.sessions WHERE token_digest=:d",d='b'*64),0)
        token,user=self.login('AdminExample')
        with self.assertRaisesRegex(IdentityError,'instance_not_ready'):
            self.gateway.call('admin_issue_invite_v1',digest(token),user.user_id,None,str(uuid.uuid4()),'c'*64)
        with self.assertRaisesRegex(IdentityError,'instance_not_ready'):
            self.gateway.call('change_password_v1',user.user_id,None,digest(token),self.encoded)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.invites'),0)

    def test_unmanaged_routines_refused_on_empty_base_and_current_targets(self):
        for revision in ['empty','base','current']:
            _,configs,operator,gateway,financial=self.target(migrate=revision=='current')
            if revision=='base':
                base=Database(configs['migration']);self.addCleanup(base.close)
                migrate(base,self.config['runtime_role'])
            with operator.database.engine.begin() as conn:
                execute(conn,"CREATE FUNCTION public.synthetic_unmanaged() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
            with self.assertRaisesRegex(PersistenceError,'migration_target_invalid'):
                migrate_identity(operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
            with operator.database.engine.begin() as conn:
                self.assertTrue(execute(conn,"SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname='synthetic_unmanaged'").scalar())
                if revision=='empty':
                    self.assertEqual(execute(conn,"SELECT count(*) FROM pg_tables WHERE schemaname IN ('wl_pg','wl_identity')").scalar_one(),0)
                else:self.assertEqual(execute(conn,'SELECT version_num FROM wl_pg.alembic_version').scalar_one(),'0001_foundation' if revision=='base' else '0002_identity')

    def test_unmanaged_columns_types_constraints_and_indexes_refused(self):
        changes=[('ALTER TABLE wl_identity.users ADD COLUMN unmanaged text','ALTER TABLE wl_identity.users DROP COLUMN unmanaged'),
                 ("CREATE TYPE public.synthetic_unmanaged AS ENUM ('x')",'DROP TYPE public.synthetic_unmanaged'),
                 ('ALTER TABLE wl_identity.users ADD CONSTRAINT unmanaged CHECK(length(username)>0)','ALTER TABLE wl_identity.users DROP CONSTRAINT unmanaged'),
                 ('CREATE INDEX unmanaged ON wl_identity.users(username)','DROP INDEX wl_identity.unmanaged')]
        for addition,removal in changes:
            self.sql(addition)
            try:
                with self.assertRaisesRegex(PersistenceError,'migration_target_invalid'):
                    migrate_identity(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
            finally:self.sql(removal)
        self.assertEqual(migrate_identity(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())['schema_revision'],'0002_identity')

    def test_repeat_migration_waits_for_both_instance_and_auth_guard(self):
        other=Database(self.configs['migration'],schema_mode='identity');self.addCleanup(other.close)
        for table in ['wl_pg.instance_state','wl_identity.instance_auth_state']:
            with self.operator.database.engine.begin() as conn:
                execute(conn,'SELECT id FROM '+table+' WHERE id=1 FOR UPDATE').all()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(migrate_identity,other,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
                    deadline=time.monotonic()+1
                    waiting=0
                    while time.monotonic()<deadline:
                        waiting=execute(conn,'SELECT count(*) FROM pg_locks l WHERE NOT l.granted AND pg_backend_pid()=ANY(pg_blocking_pids(l.pid))').scalar_one()
                        if waiting:break
                        time.sleep(.01)
                    self.assertTrue(waiting);self.assertFalse(future.done())
                    conn.commit()
                    self.assertTrue(future.result(timeout=5)['ready'])

    def test_isolated_missing_key_recovery_quarantines_all_and_fences_old_app(self):
        token,a=self.bootstrap();_,b=self.member()
        self.operator.call('set_user_enabled_v1',b.user_id,False)
        old_app=Auth(Settings(self.configs['identity'],self.configs['runtime'],self.key,'http://localhost'))
        self.addCleanup(old_app.close)
        new_key=secrets.token_bytes(32)
        new_digest=hashlib.sha256(new_key).hexdigest()
        before=self.operator.status()
        with self.assertRaises(PersistenceError):
            finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],new_digest)
        self.assertEqual(self.operator.status(),before)
        finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],new_digest,replace_missing_key=True)
        self.assertEqual(self.operator.status()['key_digest'],new_digest)
        self.assertNotEqual(self.operator.status()['incarnation'],before['incarnation'])
        self.assertEqual(self.operator.status()['epoch'],before['epoch']+1)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.users'),2)
        self.assertFalse(self.scalar('SELECT enabled FROM wl_identity.users WHERE id=:id',id=b.user_id))
        self.assertFalse(self.gateway.call('login_target_v1','adminexample')['usable'])
        for operation in [lambda:old_app.resolve(token),lambda:old_app.anonymous('127.0.0.1')]:
            with self.assertRaisesRegex(IdentityError,'instance_not_ready'):operation()
        new_app=Auth(Settings(self.configs['identity'],self.configs['runtime'],new_key,'http://localhost'))
        self.addCleanup(new_app.close)
        self.operator.call('reset_user_v1',a.user_id,self.encoded)
        replacement,user=self.login('AdminExample')
        self.assertEqual(new_app.resolve(replacement).user_id,a.user_id)
        self.assertTrue(user.is_instance_admin)
        with self.assertRaises(PersistenceError):
            finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],new_digest,replace_missing_key=True)

    def test_clock_correction_then_isolated_finalize_preserves_watermark_and_history(self):
        token,user=self.bootstrap()
        created=self.scalar('SELECT created_at FROM wl_identity.users WHERE id=:id',id=user.user_id)
        high=self.scalar('SELECT last_observed_at FROM wl_identity.instance_auth_state')
        old=self.operator.status()
        self.clock((high-timedelta(seconds=1)).isoformat())
        with self.assertRaisesRegex(IdentityError,'instance_not_ready'):self.gateway.session(digest(token))
        with self.assertRaises(PersistenceError):
            finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
        self.assertEqual(self.scalar('SELECT last_observed_at FROM wl_identity.instance_auth_state'),high)
        self.clock((high+timedelta(seconds=1)).isoformat())
        finalized=finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
        self.assertEqual(finalized['restore_epoch'],old['epoch']+1)
        self.assertFalse(self.gateway.call('login_target_v1','adminexample')['usable'])
        self.assertEqual(self.scalar('SELECT created_at FROM wl_identity.users WHERE id=:id',id=user.user_id),created)
        self.assertGreaterEqual(self.scalar('SELECT last_observed_at FROM wl_identity.instance_auth_state'),high)
        self.operator.call('reset_user_v1',user.user_id,self.encoded)
        self.assertTrue(self.login('AdminExample')[1].is_instance_admin)

    def test_late_readiness_failure_is_consumed_after_timeout(self):
        from wealth_ledger.web_v2.api import Boundary
        started=threading.Event();release=threading.Event()
        class Fake:
            def ready(self):
                started.set();release.wait(3)
                raise RuntimeError('SYNTHETIC_READY_DIAGNOSTIC_CANARY')
        async def unused(scope,receive,send):raise AssertionError()
        boundary=Boundary(unused,settings=type('Settings',(),{'host':'localhost','cookie_name':'wealth_v2_session'})(),auth=Fake())
        async def run():
            seen=[];loop=asyncio.get_running_loop();loop.set_exception_handler(lambda _,context:seen.append(str(context)))
            original=asyncio.wait_for
            async def fast_probe(awaitable,timeout):return await original(awaitable,.02 if timeout==15 else timeout)
            scope={'type':'http','headers':[(b'host',b'localhost')],'path':'/readyz','method':'GET','query_string':b''}
            async def receive():return {'type':'http.request','body':b''}
            async def send(message):pass
            with patch('wealth_ledger.web_v2.api.asyncio.wait_for',side_effect=fast_probe):
                await boundary(scope,receive,send)
            self.assertTrue(started.is_set());release.set()
            await asyncio.sleep(.05)
            boundary.ready_task=None;gc.collect();await asyncio.sleep(0)
            self.assertFalse(seen,seen)
        asyncio.run(run())
