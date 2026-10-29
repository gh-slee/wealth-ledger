"""All declared migration barriers and matching source restores into empty targets."""
import hashlib
import json
import secrets
import subprocess
import unittest

from test_source_lifecycle import SourceCase,ConfiguredSourceCase,CONTENT_ENABLED,installation_fixture
from wealth_ledger.persistence.context import Database,execute
from wealth_ledger.persistence.identity import IdentityStore,IdentityError,Principal
from wealth_ledger.persistence.errors import PersistenceError
from wealth_ledger.persistence.source_migration import migrate_sources,finalize_sources_restore,structure_snapshot
from wealth_ledger.persistence.source_store import SourceStore
from wealth_ledger.data_sources.lifecycle_v1 import SourceError
from wealth_ledger.web_v2.auth import digest


class SourceMigrationFaultTests(SourceCase):
    def test_all_declared_fresh_migration_faults_roll_back_every_schema_and_grant(self):
        for stage in ('after_new_schema','after_tables','after_replacement_guards','after_source_functions','after_grants','after_catalog','after_inventory','before_commit'):
            name,configs,operator,gateway,financial=self.target(migrate=False)
            target=Database(configs['migration'],schema_mode='sources');self.addCleanup(target.close)
            def fault(point):
                if point==stage:raise RuntimeError('Synthetic source migration fault')
            with self.subTest(stage=stage),self.assertRaisesRegex(RuntimeError,'Synthetic source migration fault'):
                migrate_sources(target,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),self.catalog,fault=fault)
            with operator.database.engine.begin() as conn:
                self.assertEqual(execute(conn,"SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname IN ('wl_pg','wl_identity','wl_sources')").scalar_one(),0)


@unittest.skipUnless(CONTENT_ENABLED,'Explicit immutable source image and artifact required')
class SourceRestoreTests(ConfiguredSourceCase):
    def test_matching_backup_restores_twice_preserving_sources_and_fencing_forms(self):
        # Establish epoch7 while this fresh marked target still has no users or
        # sessions. All subsequent identities/receipts are issued normally at7.
        self.sql('UPDATE wl_pg.instance_state SET restore_epoch=7 WHERE id=1')
        _,principal=self.bootstrap();self.enable(principal);create_body,created=self.create(principal)
        codes=[secrets.token_urlsafe(32) for _ in range(6)]
        issued=[self.operator.call('issue_invite_v1',digest(code)) for code in codes]
        self.gateway.call('register_commit_v1',digest(codes[0]),'MemberExample',self.encoded,digest(self.anonymous()))
        self.operator.call('revoke_invite_v1',issued[1]['invite_id'])
        before={table:self.scalar("SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY to_jsonb(x)::text),'[]'::jsonb) FROM wl_sources."+table+' x')
                for table in ('catalog_state','installations','lifecycle_roots','enablements','connection_lifecycle','lifecycle_receipts','lifecycle_audit')}
        with self.operator.database.engine.begin() as conn:original_structure=structure_snapshot(conn)
        dump=subprocess.run(['docker','exec',self.config['container'],'pg_dump','-U','postgres','--format=custom','--no-owner','--no-acl','--dbname='+self.name],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
        catalog,proofs=installation_fixture();incarnations=[]
        for _ in range(2):
            name,configs,operator,gateway,financial=self.target(migrate=False)
            subprocess.run(['docker','exec','-i',self.config['container'],'pg_restore','-U','postgres','--exit-on-error','--no-owner','--no-acl','--role='+self.config['migration_role'],'--dbname='+name],input=dump,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            target=Database(configs['migration'],schema_mode='sources');self.addCleanup(target.close)
            with target.engine.begin() as conn:
                restored_structure=structure_snapshot(conn)
                for section,rows in original_structure.items():
                    for old,new in zip(rows,restored_structure[section],strict=True):
                        self.assertEqual(new,old,section)
            state=finalize_sources_restore(target,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),catalog,proofs=proofs)
            self.assertEqual(state['restore_epoch'],8);incarnations.append(state['incarnation'])
            restored_operator=IdentityStore(configs['migration'],schema_mode='sources');restored_gateway=IdentityStore(configs['identity'],schema_mode='sources')
            restored_source=SourceStore(configs['identity'],catalog)
            for item in (restored_operator,restored_gateway,restored_source):self.addCleanup(item.close)
            with target.engine.begin() as conn:
                for table,expected in before.items():
                    actual=execute(conn,"SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY to_jsonb(x)::text),'[]'::jsonb) FROM wl_sources."+table+' x').scalar_one()
                    self.assertEqual(actual,expected,table)
                self.assertEqual(execute(conn,"SELECT count(*) FROM wl_identity.invites WHERE status='issued'").scalar_one(),0)
                self.assertEqual(execute(conn,"SELECT count(*) FROM wl_identity.invites WHERE status='consumed'").scalar_one(),1)
                self.assertEqual(execute(conn,"SELECT count(*) FROM wl_identity.invites WHERE status='revoked' AND revocation_reason='restore'").scalar_one(),4)
                self.assertEqual(execute(conn,"SELECT count(*) FROM wl_identity.invites WHERE revocation_reason='manual'").scalar_one(),1)
                self.assertEqual(execute(conn,"SELECT count(*) FROM wl_identity.auth_audit WHERE action='restore_finalized'").scalar_one(),1)
                self.assertTrue(execute(conn,'SELECT bootstrap_closed FROM wl_identity.instance_auth_state').scalar_one())
            with self.assertRaises(IdentityError):restored_gateway.session(principal.session_digest)
            restored_operator.call('reset_user_v1',principal.user_id,self.encoded)
            nonce=secrets.token_urlsafe(32);restored_gateway.call('issue_anonymous_v1',digest(nonce));target_user=restored_gateway.call('login_target_v1','adminexample')
            logged=restored_gateway.call('login_commit_v1',target_user['user_id'],target_user['credential_version'],digest(nonce),'a'*64)
            fresh=Principal.from_value(logged['principal'])
            with self.assertRaisesRegex(SourceError,'source_repreview_required'):
                restored_source.call('create_source_connection_v1',fresh,create_body)
            with self.assertRaisesRegex(IdentityError,'setup_closed'):restored_operator.call('arm_setup_v1','b'*64)
        self.assertNotEqual(incarnations[0],incarnations[1])

    def test_uninitialized_restore_and_named_finalization_faults_fail_atomically(self):
        catalog,proofs=installation_fixture()
        with self.assertRaisesRegex(PersistenceError,'restore_required'):
            finalize_sources_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),catalog,proofs=proofs)
        self.bootstrap();before=self.operator.database.status()
        for stage in ('after_catalog_verification','after_restore_invites','after_restore_epoch','after_restore_audit','before_source_ready','before_restore_commit'):
            def fault(point):
                if point==stage:raise RuntimeError('Synthetic source restore fault')
            with self.subTest(stage=stage),self.assertRaisesRegex(RuntimeError,'Synthetic source restore fault'):
                finalize_sources_restore(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),catalog,proofs=proofs,fault=fault)
            self.assertEqual(self.operator.database.status(),before)
            self.assertEqual(self.scalar("SELECT count(*) FROM wl_identity.auth_audit WHERE action='restore_finalized'"),0)
