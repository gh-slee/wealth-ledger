"""Real SQL identity provisioning, privilege, nonce and restore-state invariants."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import secrets
import threading
import uuid

from test_identity_support import IdentityCase
from wealth_ledger.persistence.identity import IdentityError,IdentityStore,role_inventory
from wealth_ledger.persistence.context import execute,RequestDatabase
from wealth_ledger.persistence.migration import migrate_identity,finalize_identity_restore
from wealth_ledger.web_v2.auth import digest

ORACLE=json.loads((Path(__file__).parent/'fixtures/identity_v2/oracle.json').read_text())


class IdentityTransactions(IdentityCase):
    def test_first_admin_member_empty_finance_and_closed_setup(self):
        _,a=self.bootstrap();_,b=self.member()
        expected=ORACLE['setup_and_member']
        for table,key in [('users','users')]:self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.'+table),expected[key])
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.tenant_roots'),expected['roots'])
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.portfolios'),expected['portfolios'])
        self.assertEqual(self.scalar('SELECT sum(fact_generation) FROM wl_pg.portfolios'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.candidate_batches'),0)
        self.assertTrue(a.is_instance_admin);self.assertFalse(b.is_instance_admin)
        with self.assertRaisesRegex(IdentityError,'setup_closed'):self.operator.call('arm_setup_v1',digest(secrets.token_urlsafe(32)))
        with self.assertRaisesRegex(IdentityError,'setup_closed'):
            self.gateway.call('bootstrap_commit_v1','a'*64,'AnotherAdmin',self.encoded,digest(self.anonymous()))
        with self.assertRaisesRegex(IdentityError,'registration_rejected'):
            code=secrets.token_urlsafe(32);self.operator.call('issue_invite_v1',digest(code))
            self.gateway.call('register_commit_v1',digest(code),'adminexample',self.encoded,digest(self.anonymous()))

    def test_register_requires_setup_and_setup_code_one_live(self):
        with self.assertRaisesRegex(IdentityError,'setup_required'):
            self.gateway.call('register_commit_v1','a'*64,'Example',self.encoded,digest(self.anonymous()))
        armed=self.operator.call('arm_setup_v1','a'*64)
        with self.assertRaisesRegex(IdentityError,'setup_already_armed'):self.operator.call('arm_setup_v1','b'*64)
        self.operator.call('revoke_setup_v1',armed['setup_id'])
        self.operator.call('arm_setup_v1','b'*64)
        self.assertEqual(self.scalar("SELECT count(*) FROM wl_identity.setup_codes WHERE status='issued'"),1)

    def test_privileges_are_exact_and_temp_shadows_do_not_redirect(self):
        self.assertTrue(role_inventory(self.gateway.database,gateway=True))
        self.assertTrue(role_inventory(self.financial,gateway=False))
        for db,statements in [(self.gateway.database,["SELECT * FROM wl_identity.users","SELECT * FROM wl_pg.portfolios","SELECT wl_identity.issue_invite_v1(repeat('a',64))","SELECT wl_identity._clock_timestamp_v1()"]),
                              (self.financial,["SELECT * FROM wl_identity.users","SELECT wl_identity.issue_anonymous_v1(repeat('a',64))","INSERT INTO wl_pg.tenant_roots VALUES(gen_random_uuid(),gen_random_uuid())"])]:
            for statement in statements:
                with self.assertRaises(Exception):
                    with db.engine.begin() as conn:execute(conn,statement)
        with self.gateway.database.engine.begin() as conn:
            execute(conn,'CREATE TEMP TABLE users(id uuid)')
            execute(conn,'CREATE TEMP TABLE instance_auth_state(id integer)')
            execute(conn,'SET LOCAL search_path=pg_temp,public,wl_identity')
            self.assertTrue(execute(conn,'SELECT wl_identity.identity_status_v1()').scalar_one()['ok'])
            self.assertTrue(execute(conn,"SELECT wl_identity.issue_anonymous_v1(repeat('f',64))").scalar_one()['ok'])
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.users'),0)

    def test_reset_disable_session_precedence_and_no_cross_user_logout(self):
        ta,a=self.bootstrap();tb,b=self.member()
        self.operator.call('reset_user_v1',a.user_id,self.encoded)
        with self.assertRaisesRegex(IdentityError,'authentication_required'):self.gateway.session(digest(ta))
        with self.assertRaisesRegex(IdentityError,'credentials_changed'):self.gateway.call('touch_session_v1',digest(ta))
        self.assertEqual(self.gateway.session(digest(tb)).user_id,b.user_id)
        self.operator.call('set_user_enabled_v1',a.user_id,False)
        with self.assertRaisesRegex(IdentityError,'authentication_required'):self.gateway.call('logout_session_v1',digest(ta))
        self.operator.call('set_user_enabled_v1',a.user_id,True)
        with self.assertRaisesRegex(IdentityError,'authentication_required'):self.gateway.session(digest(ta))
        self.gateway.call('logout_session_v1',digest(tb))
        with self.assertRaisesRegex(IdentityError,'authentication_required'):self.gateway.session(digest(tb))

    def test_same_nonce_loser_does_not_consume_second_invite(self):
        self.bootstrap();nonce=digest(self.anonymous());codes=['1'*64,'2'*64]
        for code in codes:self.operator.call('issue_invite_v1',code)
        self.gateway.call('register_commit_v1',codes[0],'FirstMember',self.encoded,nonce)
        with self.assertRaisesRegex(IdentityError,'session_changed'):
            self.gateway.call('register_commit_v1',codes[1],'SecondMember',self.encoded,nonce)
        self.assertEqual(self.scalar("SELECT status FROM wl_identity.invites WHERE token_digest=:code",code=codes[1]),'issued')

    def race(self,setup):
        if not setup:self.bootstrap()
        code=hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        self.operator.call('arm_setup_v1' if setup else 'issue_invite_v1',code)
        nonces=[digest(self.anonymous()) for _ in range(16)]
        stores=[IdentityStore(self.configs['identity']) for _ in range(16)]
        for store in stores:self.addCleanup(store.close)
        barrier=threading.Barrier(16)
        def run(index):
            barrier.wait(timeout=10)
            try:
                stores[index].call('bootstrap_commit_v1' if setup else 'register_commit_v1',code,'RaceExample'+str(index),self.encoded,nonces[index])
                return 'committed'
            except IdentityError as error:return error.code
        with ThreadPoolExecutor(max_workers=16) as pool:values=list(pool.map(run,range(16)))
        self.assertEqual(values.count('committed'),1,values)
        self.assertEqual(values.count('setup_closed' if setup else 'registration_rejected'),15,values)
        expected=1 if setup else 2
        for table in ['users']:
            self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.'+table),expected)
        for table in ['tenant_roots','portfolios']:
            self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.'+table),expected)

    def test_sixteen_registration_transactions_one_commit(self):self.race(False)
    def test_sixteen_first_setup_transactions_one_admin(self):self.race(True)

    def test_admin_session_matching_idempotency_and_restore_reason(self):
        token,a=self.bootstrap();bt,b=self.member()
        request_id=str(uuid.uuid4())
        issued=self.gateway.call('admin_issue_invite_v1',digest(token),a.user_id,a.credential_version,request_id,'a'*64)
        with self.assertRaisesRegex(IdentityError,'invite_already_issued'):
            self.gateway.call('admin_issue_invite_v1',digest(token),a.user_id,a.credential_version,request_id,'b'*64)
        with self.assertRaisesRegex(IdentityError,'session_changed'):
            self.gateway.call('admin_issue_invite_v1',digest(bt),a.user_id,a.credential_version,str(uuid.uuid4()),'b'*64)
        with self.assertRaisesRegex(IdentityError,'admin_required'):
            self.gateway.call('admin_issue_invite_v1',digest(bt),b.user_id,b.credential_version,str(uuid.uuid4()),'b'*64)
        items=self.gateway.call('admin_read_invites_v1',digest(token),a.user_id,a.credential_version,request_id,None,50)['items']
        self.assertEqual(items[0]['id'],issued['id']);self.assertNotIn('token_digest',items[0])
        finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
        self.assertEqual(self.scalar('SELECT revocation_reason FROM wl_identity.invites WHERE id=:id',id=issued['id']),'restore')
        self.assertFalse(self.gateway.call('login_target_v1','adminexample')['usable'])
        self.operator.call('reset_user_v1',a.user_id,self.encoded)
        token,new=self.login('AdminExample')
        with self.assertRaisesRegex(IdentityError,'invite_not_active'):
            self.gateway.call('admin_revoke_invite_v1',digest(token),new.user_id,new.credential_version,issued['id'])
        revoked=digest(self.anonymous())
        self.sql('UPDATE wl_identity.sessions SET revoked=true WHERE token_digest=:digest',digest=revoked)
        with self.assertRaisesRegex(IdentityError,'session_changed'):
            self.gateway.call('login_commit_v1',a.user_id,a.credential_version,revoked,'b'*64)

    def test_real_clock_lock_wait_and_backwards_highwater(self):
        before=self.scalar('SELECT last_observed_at FROM wl_identity.instance_auth_state')
        with self.operator.database.engine.begin() as conn:
            execute(conn,'SELECT id FROM wl_identity.instance_auth_state WHERE id=1 FOR UPDATE')
            with ThreadPoolExecutor(max_workers=1) as pool:
                result=pool.submit(self.gateway.call,'issue_anonymous_v1','b'*64)
                # Observe the actual backend waiting, not an assumed sleep barrier.
                import time
                deadline=time.monotonic()+1
                while time.monotonic()<deadline:
                    waiting=execute(conn,"SELECT count(*) FROM pg_locks l WHERE NOT l.granted AND pg_backend_pid()=ANY(pg_blocking_pids(l.pid))").scalar_one()
                    if waiting:break
                    time.sleep(.01)
                self.assertTrue(waiting)
                released=execute(conn,'SELECT clock_timestamp()').scalar_one()
                conn.commit()
                result.result(timeout=5)
        high=self.scalar('SELECT last_observed_at FROM wl_identity.instance_auth_state')
        self.assertGreaterEqual(high,released);self.assertGreater(high,before)
        self.clock((high-timedelta(microseconds=1)).isoformat())
        with self.assertRaisesRegex(IdentityError,'instance_not_ready'):self.gateway.call('issue_anonymous_v1','c'*64)
        self.assertEqual(self.scalar('SELECT last_observed_at FROM wl_identity.instance_auth_state'),high)

    def test_expected_rejection_retains_clock_and_exact_nonce_expiry(self):
        self.bootstrap();token=self.anonymous();nonce=digest(token)
        expiry=self.scalar('SELECT expires_at FROM wl_identity.sessions WHERE token_digest=:d',d=nonce)
        self.clock(expiry.isoformat())
        with self.assertRaisesRegex(IdentityError,'session_changed'):
            self.gateway.call('register_commit_v1','b'*64,'ExpiredNonce',self.encoded,nonce)
        self.assertEqual(self.scalar('SELECT last_observed_at FROM wl_identity.instance_auth_state'),expiry)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.users'),1)

    def test_migration_repeat_fault_rollback_and_uninitialized_restore_denied(self):
        self.assertEqual(migrate_identity(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())['schema_revision'],'0002_identity')
        with self.assertRaises(Exception):
            finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
        _,configs,o,g,f=self.target(migrate=False)
        def fail(stage):raise RuntimeError('Synthetic migration interruption')
        with self.assertRaises(RuntimeError):migrate_identity(o.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),fault=fail)
        with o.database.engine.begin() as conn:
            self.assertEqual(execute(conn,"SELECT count(*) FROM pg_tables WHERE schemaname IN ('wl_pg','wl_identity')").scalar_one(),0)
