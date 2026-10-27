"""Matching dumps restored into two empty targets; six-row independent state oracle."""
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import uuid
from datetime import timedelta

from test_identity_support import IdentityCase
from wealth_ledger.persistence.context import execute
from wealth_ledger.persistence.identity import IdentityError,Principal
from wealth_ledger.persistence.migration import finalize_identity_restore
from wealth_ledger.web_v2.auth import digest


class IdentityRestore(IdentityCase):
    def snapshot_invites(self,store):
        with store.database.engine.begin() as conn:
            return execute(conn,'SELECT id,issue_request_id,token_digest,created_at,expires_at,incarnation,epoch,consumed_user_id FROM wl_identity.invites ORDER BY id').all()

    def login_on(self,store,username):
        nonce=digest(secrets.token_urlsafe(32));replacement=digest(secrets.token_urlsafe(32))
        store.call('issue_anonymous_v1',nonce)
        target=store.call('login_target_v1',username.lower())
        value=store.call('login_commit_v1',target['user_id'],target['credential_version'],nonce,replacement)
        return replacement,Principal.from_value(value['principal'])

    def test_double_empty_restore_quarantine_invites_history_flags_and_repeat(self):
        old_token,a=self.bootstrap();_,b=self.member()
        self.operator.call('set_user_enabled_v1',b.user_id,False)
        now=self.scalar('SELECT clock_timestamp()')
        state=self.operator.status()
        self.sql('DELETE FROM wl_identity.invites')
        records=[]
        for index in range(6):
            rid=str(uuid.uuid4());request=str(uuid.uuid4()) if index!=2 else None
            status=['issued','issued','issued','consumed','revoked','revoked'][index]
            created=now-timedelta(days=2) if index==1 else now
            reason='manual' if index==4 else 'restore' if index==5 else None
            with self.operator.database.engine.begin() as conn:
                execute(conn,'INSERT INTO wl_identity.invites VALUES(:id,:digest,:request,:created,:expires,:realm,:epoch,:status,:reason,:consumed)',
                        id=rid,digest=hashlib.sha256(('synthetic-invite-'+str(index)).encode()).hexdigest(),request=request,
                        created=created,expires=created+timedelta(days=1),realm=state['incarnation'],epoch=state['epoch'],
                        status=status,reason=reason,consumed=b.user_id if index==3 else None)
            records.append(rid)
        original=self.snapshot_invites(self.operator)
        dump=subprocess.run(['docker','exec',self.config['container'],'pg_dump','-U','postgres','--format=custom','--no-owner','--no-acl','--dbname='+self.name],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
        # Post-backup changes are deliberately NOT claimed to survive an older dump.
        self.operator.call('reset_user_v1',a.user_id,self.encoded)
        self.operator.call('set_user_enabled_v1',a.user_id,False)
        incarnations=[]
        for _ in range(2):
            name,configs,operator,gateway,financial=self.target(migrate=False)
            subprocess.run(['docker','exec','-i',self.config['container'],'pg_restore','-U','postgres','--exit-on-error','--no-owner','--no-acl','--role='+self.config['migration_role'],'--dbname='+name],input=dump,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            with self.assertRaises(IdentityError):gateway.status()
            finalized=finalize_identity_restore(operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
            incarnations.append(finalized['incarnation'])
            self.assertEqual(self.snapshot_invites(operator),original)
            with operator.database.engine.begin() as conn:
                counts=execute(conn,"SELECT count(*),count(issue_request_id),count(*) FILTER(WHERE status='issued'),count(*) FILTER(WHERE status='consumed'),count(*) FILTER(WHERE status='revoked'),count(*) FILTER(WHERE revocation_reason='restore'),count(*) FILTER(WHERE revocation_reason='manual') FROM wl_identity.invites").one()
                self.assertEqual(tuple(counts),(6,5,0,1,5,4,1))
                self.assertEqual(execute(conn,'SELECT enabled FROM wl_identity.users WHERE id=:id',id=a.user_id).scalar_one(),True)
                self.assertEqual(execute(conn,'SELECT enabled FROM wl_identity.users WHERE id=:id',id=b.user_id).scalar_one(),False)
            with self.assertRaisesRegex(IdentityError,'authentication_required'):gateway.session(digest(old_token))
            self.assertFalse(gateway.call('login_target_v1','adminexample')['usable'])
            self.assertFalse(gateway.call('login_target_v1','memberexample')['usable'])
            operator.call('reset_user_v1',a.user_id,self.encoded)
            token,principal=self.login_on(gateway,'AdminExample')
            self.assertTrue(principal.is_instance_admin)
            operator.call('reset_user_v1',b.user_id,self.encoded)
            self.assertFalse(gateway.call('login_target_v1','memberexample')['usable'])
            operator.call('set_user_enabled_v1',b.user_id,True)
            self.assertTrue(gateway.call('login_target_v1','memberexample')['usable'])
            for record in records[:3]:
                with self.assertRaisesRegex(IdentityError,'invite_not_active'):
                    gateway.call('admin_revoke_invite_v1',token,principal.user_id,principal.credential_version,record)
            finalize_identity_restore(operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
            self.assertEqual(self.snapshot_invites(operator),original)
            with operator.database.engine.begin() as conn:
                self.assertEqual(execute(conn,"SELECT count(*) FROM wl_identity.auth_audit WHERE action='restore_finalized'").scalar_one(),2)
                self.assertEqual(execute(conn,"SELECT count(*) FROM wl_identity.auth_audit WHERE action='admin_invite_revoked'").scalar_one(),0)
            self.assertTrue(operator.status()['bootstrap_closed'])
        self.assertNotEqual(*incarnations)

    def test_restore_every_named_fault_is_atomic_and_nonce_precedes_credentials(self):
        old_token,a=self.bootstrap();nonce=digest(self.anonymous())
        invite=self.operator.call('issue_invite_v1','a'*64)
        initial=self.operator.status()
        for point in ['after_restore_invites','after_restore_epoch','after_restore_audit','before_restore_commit']:
            def fault(stage):
                if stage==point:raise RuntimeError('Synthetic restore interruption')
            with self.assertRaises(RuntimeError):
                finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),fault=fault)
            self.assertEqual(self.operator.status(),initial)
            self.assertEqual(self.scalar('SELECT status FROM wl_identity.invites WHERE id=:id',id=invite['invite_id']),'issued')
            self.assertEqual(self.scalar("SELECT count(*) FROM wl_identity.auth_audit WHERE action='restore_finalized'"),0)
        finalize_identity_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
        with self.assertRaisesRegex(IdentityError,'session_changed'):
            self.gateway.call('login_commit_v1',a.user_id,a.credential_version,nonce,'b'*64)
        with self.assertRaisesRegex(IdentityError,'session_changed'):
            self.gateway.call('register_commit_v1','a'*64,'AfterRestore',self.encoded,nonce)
        from wealth_ledger.persistence.context import RequestDatabase
        from wealth_ledger.persistence.repositories import Candidates
        with self.assertRaises(Exception):Candidates(RequestDatabase(self.financial,a)).read(a.context,str(uuid.uuid4()))

    def test_actual_empty_restore_lost_key_uses_new_private_file_and_manifest(self):
        from wealth_ledger.web_v2.operator import new_private
        from wealth_ledger.web_v2.auth import Auth
        from wealth_ledger.web_v2.config import Settings
        _,a=self.bootstrap();_,b=self.member()
        self.operator.call('set_user_enabled_v1',b.user_id,False)
        source_key=self.operator.status()['key_digest']
        dump=subprocess.run(['docker','exec',self.config['container'],'pg_dump','-U','postgres','--format=custom','--no-owner','--no-acl','--dbname='+self.name],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
        name,configs,operator,gateway,financial=self.target(migrate=False)
        subprocess.run(['docker','exec','-i',self.config['container'],'pg_restore','-U','postgres','--exit-on-error','--no-owner','--no-acl','--role='+self.config['migration_role'],'--dbname='+name],input=dump,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        evidence=Path(self.config['key_file']).parent/('key-recovery-'+uuid.uuid4().hex)
        evidence.mkdir(mode=0o700)
        new_key=secrets.token_bytes(32);key_path=evidence/'new-instance.key';new_private(key_path,new_key)
        key_digest=hashlib.sha256(new_key).hexdigest()
        finalized=finalize_identity_restore(operator.database,self.config['runtime_role'],self.config['identity_role'],key_digest,replace_missing_key=True)
        manifest={'format':'wealth-ledger-synthetic-key-recovery','dump_sha256':hashlib.sha256(dump).hexdigest(),
                  'old_key_sha256':source_key,'new_key_sha256':key_digest,'key_mode':key_path.stat().st_mode&0o777,'old_key_supplied_to_recovery':False,
                  'target_incarnation':finalized['incarnation'],'target_epoch':finalized['restore_epoch']}
        new_private(evidence/'manifest.json',json.dumps(manifest,indent=2).encode())
        self.assertEqual(manifest['key_mode'],0o600)
        self.assertEqual(self.operator.status()['key_digest'],source_key)
        with self.assertRaises(IdentityError):Auth(Settings(configs['identity'],configs['runtime'],self.key,'http://localhost'))
        app=Auth(Settings(configs['identity'],configs['runtime'],new_key,'http://localhost'));self.addCleanup(app.close)
        self.assertFalse(gateway.call('login_target_v1','adminexample')['usable'])
        operator.call('reset_user_v1',a.user_id,self.encoded)
        self.assertTrue(gateway.call('login_target_v1','adminexample')['usable'])
        self.assertFalse(gateway.call('login_target_v1','memberexample')['usable'])
        with operator.database.engine.begin() as conn:
            self.assertFalse(execute(conn,'SELECT enabled FROM wl_identity.users WHERE id=:id',id=b.user_id).scalar_one())
            self.assertEqual(execute(conn,'SELECT sum(fact_generation) FROM wl_pg.portfolios').scalar_one(),0)
