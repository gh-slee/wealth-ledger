"""Opt-in actual source-profile schema/permission tests on fresh marked targets."""
from pathlib import Path
import hashlib
import json
import os
import re
import unittest
import uuid
from unittest.mock import patch

from test_identity_support import IdentityCase
from wealth_ledger.data_sources.contract_v1 import CatalogSnapshot,Definition,Availability,installation_id
from wealth_ledger.data_sources.catalog_v1 import catalog_digest
from wealth_ledger.data_sources.lifecycle_v1 import SourceError
from wealth_ledger.persistence.context import Database,execute
from wealth_ledger.persistence.identity import IdentityStore,IdentityError,role_inventory
from wealth_ledger.persistence.source_store import SourceStore
from wealth_ledger.persistence.source_migration import migrate_sources,verify_inventory,apply_catalog


class SourceCase(IdentityCase):
    def setUp(self):
        super().setUp()
        self.catalog=CatalogSnapshot(1,'0',(),(),())
        source_operator=Database(self.configs['migration'],schema_mode='sources');self.addCleanup(source_operator.close)
        migrate_sources(source_operator,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),self.catalog)
        self.operator.close();self.gateway.close();self.financial.close()
        self.operator=IdentityStore(self.configs['migration'],schema_mode='sources')
        self.gateway=IdentityStore(self.configs['identity'],schema_mode='sources')
        self.financial=Database(self.configs['runtime'],schema_mode='sources')
        self.sources=SourceStore(self.configs['identity'],self.catalog)
        for item in (self.operator,self.gateway,self.financial,self.sources):self.addCleanup(item.close)

    def source_read(self,principal,name='sources_catalog_v1',payload=None):
        payload=payload or {'after':None,'limit':50,'catalog_revision':None,'state_revision':None,'expected_realm':None}
        return self.sources.call(name,principal,payload)

    def common(self,principal):
        return {'operation_id':str(uuid.uuid4()),'expected_revision':'0','expected_realm':self.source_read(principal)['realm']}


class SourceLifecycleTests(SourceCase):
    def test_exact_profile_and_empty_catalog_do_not_dispatch_or_create_connections(self):
        token,principal=self.bootstrap()
        with patch('wealth_ledger.source_registry.build_registry',side_effect=AssertionError('No source execution')):
            catalog=self.source_read(principal)
            connections=self.source_read(principal,'sources_connections_v1')
        self.assertEqual((catalog['items'],connections['items']),([],[]))
        self.assertEqual((catalog['catalog_revision'],catalog['state_revision']),('0','0'))
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.connections'),0)
        self.assertEqual(self.scalar('SELECT sum(fact_generation) FROM wl_pg.portfolios'),0)
        self.assertEqual(self.operator.status()['schema_revision'],'0003_source_lifecycle')
        self.assertEqual(migrate_sources(self.operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),self.catalog)['schema_revision'],'0003_source_lifecycle')

    def test_recognized_api_unavailable_precedes_lookup_cas_without_business_rows(self):
        _,principal=self.bootstrap()
        body=self.common(principal)|{'plugin_id':'unknown','capability':'PULL_API','enabled':True,'installation_id':'a'*64}
        with self.assertRaisesRegex(SourceError,'source_capability_unavailable'):
            self.sources.call('set_source_enablement_v1',principal,body)
        body=self.common(principal)|{'plugin_id':'unknown','capability':'PULL_API','installation_id':'a'*64,'display_label':'Synthetic','parser_source_alias':None}
        with self.assertRaisesRegex(SourceError,'source_capability_unavailable'):
            self.sources.call('create_source_connection_v1',principal,body)
        for table in ('lifecycle_roots','enablements','connection_lifecycle','lifecycle_receipts','lifecycle_audit'):
            self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.'+table),0)

    def test_missing_foreign_and_stale_realm_fail_closed(self):
        _,a=self.bootstrap();_,b=self.member()
        for principal in (a,b):
            with self.assertRaisesRegex(IdentityError,'not_found'):
                self.sources.call('sources_connection_v1',principal,{'connection_id':str(uuid.uuid4())})
        body=self.common(a)|{'plugin_id':'unknown','capability':'FILE_IMPORT','enabled':False,'installation_id':None}
        with self.assertRaisesRegex(IdentityError,'not_found'):
            self.sources.call('set_source_enablement_v1',a,body)
        body['expected_realm']={'incarnation':str(uuid.uuid4()),'restore_epoch':'0'}
        with self.assertRaisesRegex(SourceError,'source_repreview_required'):
            self.sources.call('set_source_enablement_v1',a,body)

    def test_gateway_is_execute_only_and_financial_role_reads_sources_only(self):
        self.assertTrue(role_inventory(self.gateway.database,gateway=True))
        self.assertTrue(role_inventory(self.financial,gateway=False))
        for database,sql in ((self.gateway.database,'SELECT * FROM wl_sources.catalog_state'),
                             (self.gateway.database,'SELECT * FROM wl_sources.enablements'),
                             (self.financial,"DELETE FROM wl_sources.installations"),
                             (self.financial,"SELECT wl_sources.sources_catalog_v1(NULL,NULL,NULL,NULL,NULL,NULL)"),
                             (self.gateway.database,"SELECT wl_sources.guard_enablement_update_v1()")):
            with self.assertRaises(Exception):
                with database.engine.begin() as conn:execute(conn,sql)

    def test_catalog_mismatch_and_revoked_session_precedence(self):
        _,principal=self.bootstrap()
        self.sources.catalog_digest='f'*64
        with self.assertRaisesRegex(SourceError,'source_catalog_unavailable'):
            self.source_read(principal)
        self.sources.catalog_digest=catalog_digest(self.catalog)
        self.operator.call('logout_session_v1',principal.session_digest)
        with self.assertRaisesRegex(IdentityError,'session_changed'):
            self.source_read(principal)

    def test_inventory_refuses_unknown_type_and_disabled_trigger_without_repair(self):
        for sql in ("CREATE TYPE wl_sources.unreviewed AS ENUM ('x')",'ALTER TABLE wl_sources.enablements DISABLE TRIGGER immutable_source'):
            with self.assertRaisesRegex(Exception,'migration_target_invalid'):
                with self.operator.database.engine.begin() as conn:
                    execute(conn,sql)
                    verify_inventory(conn,runtime_role=self.config['runtime_role'],gateway_role=self.config['identity_role'])
        with self.operator.database.engine.begin() as conn:
            verify_inventory(conn,runtime_role=self.config['runtime_role'],gateway_role=self.config['identity_role'])


CONTENT_ENABLED=bool(os.environ.get('WEALTH_LEDGER_SOURCE_RUNTIME_IMAGE') and os.environ.get('WEALTH_LEDGER_SOURCE_ARTIFACT_FILE'))


def installation_fixture():
    from wealth_ledger.data_sources.compatibility_v1 import builtin_descriptors
    from wealth_ledger.data_sources.catalog_v1 import verify_installation
    image=os.environ['WEALTH_LEDGER_SOURCE_RUNTIME_IMAGE']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):raise RuntimeError('Immutable synthetic test source image required')
    artifact=Path(os.environ['WEALTH_LEDGER_SOURCE_ARTIFACT_FILE']).read_bytes()
    metadata=json.loads(artifact)
    descriptors=builtin_descriptors(package_distribution=metadata['package_distribution'],package_version=metadata['package_version'],
        artifact_sha256=hashlib.sha256(artifact).hexdigest(),execution_image_digest=image[7:],entry_point_target='wealth_ledger.source_builtin:registrations')
    descriptors=tuple(sorted(descriptors,key=installation_id))
    proofs=tuple(verify_installation(value,artifact,image_root='/app/src') for value in descriptors)
    definitions=tuple(sorted((Definition('wealthsimple','wealthsimple','Wealthsimple','Synthetic content test',None),
                             Definition('bullbitcoin','bullbitcoin','Bull Bitcoin','Synthetic content test',None)),key=lambda x:x.plugin_id))
    catalog=CatalogSnapshot(1,'1',definitions,descriptors,tuple(Availability(installation_id(x),'ACTIVE','1') for x in descriptors))
    return catalog,proofs


class ConfiguredSourceCase(SourceCase):
    def setUp(self):
        super().setUp()
        catalog,proofs=installation_fixture()
        apply_catalog(self.operator.database,self.config['runtime_role'],self.config['identity_role'],catalog,expected_revision='0',proofs=proofs)
        self.catalog=catalog;self.sources.close();self.sources=SourceStore(self.configs['identity'],catalog);self.addCleanup(self.sources.close)

    def installation(self,plugin='wealthsimple'):
        return installation_id(next(x for x in self.catalog.installations if x.plugin_id==plugin))

    def enable(self,principal,*,plugin='wealthsimple',enabled=True,revision='0',operation_id=None):
        body=self.common(principal)|{'plugin_id':plugin,'capability':'FILE_IMPORT','enabled':enabled,
             'installation_id':self.installation(plugin) if enabled else None,'expected_revision':revision}
        if operation_id:body['operation_id']=operation_id
        return body,self.sources.call('set_source_enablement_v1',principal,body)

    def create(self,principal,*,plugin='wealthsimple',label='Synthetic source',alias=None,operation_id=None):
        body=self.common(principal)|{'plugin_id':plugin,'capability':'FILE_IMPORT','installation_id':self.installation(plugin),
             'display_label':label,'parser_source_alias':alias}
        if operation_id:body['operation_id']=operation_id
        return body,self.sources.call('create_source_connection_v1',principal,body)

    def update(self,principal,connection,*,enabled=None,label=None,operation_id=None):
        body=self.common(principal)|{'connection_id':connection['id'],'enabled':connection['enabled'] if enabled is None else enabled,
             'installation_id':connection['installation_id'],'display_label':connection['display_label'] if label is None else label,
             'expected_revision':connection['revision']}
        if operation_id:body['operation_id']=operation_id
        return body,self.sources.call('update_source_connection_v1',principal,body)


@unittest.skipUnless(CONTENT_ENABLED,'Explicit immutable image and public source artifact required')
class ConfiguredSourceLifecycleTests(ConfiguredSourceCase):
    def test_explicit_enable_connection_label_and_auth_generations_no_financial_effects(self):
        _,principal=self.bootstrap()
        before=self.source_read(principal)
        self.assertEqual([x['plugin_id'] for x in before['items']],['bullbitcoin','wealthsimple'])
        self.assertTrue(all(x['capabilities'][0]['enablement']['enabled'] is False for x in before['items']))
        enable_body,enabled=self.enable(principal)
        self.assertEqual((enabled['resource']['revision'],enabled['resource']['generation'],enabled['state_revision']),('1','1','1'))
        replay=self.sources.call('set_source_enablement_v1',principal,enable_body)
        self.assertEqual((replay['replayed'],replay['representation'],replay['state_revision']),(True,'historical','1'))
        create_body,created=self.create(principal)
        connection=created['resource'];original_id=connection['id'];original_version=connection['connection_version']
        self.assertEqual((connection['revision'],connection['generation'],created['state_revision']),('1','0','2'))
        _,edited=self.update(principal,connection,label='Edited label');connection=edited['resource']
        self.assertEqual((connection['revision'],connection['generation'],edited['state_revision']),('2','0','3'))
        _,disabled=self.update(principal,connection,enabled=False);connection=disabled['resource']
        self.assertEqual((connection['revision'],connection['generation'],disabled['state_revision']),('3','1','4'))
        _,noop=self.update(principal,connection,enabled=False)
        self.assertEqual((noop['changed'],noop['resource']['revision'],noop['state_revision']),(False,'3','4'))
        _,reenabled=self.update(principal,connection,enabled=True);connection=reenabled['resource']
        self.assertEqual((connection['id'],connection['connection_version'],connection['revision'],connection['generation'],reenabled['state_revision']),
                         (original_id,original_version,'4','2','5'))
        _,parent_off=self.enable(principal,enabled=False,revision='1')
        self.assertEqual((parent_off['resource']['revision'],parent_off['resource']['generation']),('2','2'))
        read=self.sources.call('sources_connection_v1',principal,{'connection_id':original_id})
        self.assertEqual(read['resource']['status'],'SOURCE_DISABLED')
        _,parent_on=self.enable(principal,revision='2')
        self.assertEqual((parent_on['resource']['revision'],parent_on['resource']['generation'],parent_on['state_revision']),('3','3','7'))
        old=self.sources.call('create_source_connection_v1',principal,create_body)
        self.assertEqual((old['replayed'],old['resource']['display_label'],old['resource']['revision']),(True,'Synthetic source','1'))
        for table in ('candidate_batches','candidate_activities','operation_receipts','audit_actions','outbox'):
            self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.'+table),0)
        self.assertEqual(self.scalar('SELECT sum(fact_generation) FROM wl_pg.portfolios'),0)
        self.assertEqual(self.scalar("SELECT count(*) FROM wl_sources.lifecycle_audit WHERE action='NO_CHANGE'"),1)

    def test_two_users_reuse_explicit_connections_and_cross_scope_is_not_found(self):
        _,a=self.bootstrap();_,b=self.member()
        self.enable(a);self.enable(b)
        _,first=self.create(a,label='Same label');_,second=self.create(a,label='Same label');_,other=self.create(b,label='Same label')
        self.assertNotEqual(first['resource']['id'],second['resource']['id'])
        self.assertNotEqual(first['resource']['id'],other['resource']['id'])
        self.assertEqual(len(self.source_read(a,'sources_connections_v1')['items']),2)
        self.assertEqual(len(self.source_read(b,'sources_connections_v1')['items']),1)
        for missing in (first['resource']['id'],str(uuid.uuid4())):
            with self.assertRaisesRegex(IdentityError,'not_found'):
                self.sources.call('sources_connection_v1',b,{'connection_id':missing})
        body=self.common(a)|{'plugin_id':'bullbitcoin','capability':'FILE_IMPORT','installation_id':self.installation('bullbitcoin'),'display_label':'Orders','parser_source_alias':'synthetic-stream'}
        with self.assertRaisesRegex(SourceError,'source_context_incompatible'):
            self.sources.call('create_source_connection_v1',a,body)
        self.enable(a,plugin='bullbitcoin')
        value=self.sources.call('create_source_connection_v1',a,body)
        self.assertEqual(value['resource']['parser_source_alias'],'synthetic-stream')

    def test_stale_cas_and_idempotency_conflicts_leave_no_extra_rows(self):
        _,principal=self.bootstrap();body,enabled=self.enable(principal)
        wrong=dict(body,enabled=False,installation_id=None)
        with self.assertRaisesRegex(SourceError,'source_idempotency_conflict'):
            self.sources.call('set_source_enablement_v1',principal,wrong)
        with self.assertRaisesRegex(SourceError,'source_revision_conflict'):
            self.enable(principal,enabled=False,revision='0')
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_audit'),1)

    def test_page_tokens_pin_head_state_and_realm(self):
        _,principal=self.bootstrap();page=self.source_read(principal,payload={'after':None,'limit':1,'catalog_revision':None,'state_revision':None,'expected_realm':None})
        self.assertEqual((len(page['items']),page['next_after']),(1,'bullbitcoin'))
        payload={'after':page['next_after'],'limit':1,'catalog_revision':page['catalog_revision'],'state_revision':page['state_revision'],'expected_realm':page['realm']}
        self.assertEqual(self.source_read(principal,payload=payload)['items'][0]['plugin_id'],'wealthsimple')
        self.enable(principal)
        with self.assertRaisesRegex(SourceError,'source_repreview_required'):
            self.source_read(principal,payload=payload)


    def test_selected_withdrawal_max_and_historical_replay_keep_active_metadata_distinct(self):
        from dataclasses import replace
        from wealth_ledger.data_sources.contract_v1 import Availability,canonical,primitive,MAX_COUNTER
        from wealth_ledger.data_sources.catalog_v1 import verify_installation
        _,principal=self.bootstrap();self.enable(principal);body,created=self.create(principal)
        record=created['resource']['id'];old=next(x for x in self.catalog.installations if x.plugin_id=='wealthsimple');old_id=installation_id(old)
        # A new reviewed metadata descriptor is a distinct installation even when
        # the same immutable artifact/image supplies its synthetic code contents.
        new=replace(old,asset_categories=tuple(sorted(set(old.asset_categories)|{'UNSUPPORTED'})))
        artifact=Path(os.environ['WEALTH_LEDGER_SOURCE_ARTIFACT_FILE']).read_bytes()
        proof=verify_installation(new,artifact,image_root='/app/src');new_id=installation_id(new)
        entries={x.installation_id:x for x in self.catalog.availability};entries[old_id]=Availability(old_id,'RETIRED','2');entries[new_id]=Availability(new_id,'ACTIVE','1')
        catalog=replace(self.catalog,catalog_revision='2',installations=tuple(sorted(self.catalog.installations+(new,),key=installation_id)),availability=tuple(entries[key] for key in sorted(entries)))
        def selected_catalog(value,expected,proofs=()):
            apply_catalog(self.operator.database,self.config['runtime_role'],self.config['identity_role'],value,expected_revision=expected,proofs=proofs)
            use(value)
        def use(value):
            self.catalog=value;self.sources.close();self.sources=SourceStore(self.configs['identity'],value);self.addCleanup(self.sources.close)
        def assert_status(expected,selected_generation):
            connection=self.source_read(principal,'sources_connection_v1',{'connection_id':record})['resource']
            capability=next(x for x in self.source_read(principal)['items'] if x['plugin_id']=='wealthsimple')['capabilities'][0]
            self.assertEqual((connection['status'],connection['reason']),expected)
            self.assertEqual((capability['status'],capability['reason']),expected)
            self.assertEqual(connection['availability_generation'],selected_generation)
            self.assertEqual((capability['active_installation_id'],capability['availability_generation']),(new_id,'1'))
            self.assertEqual(capability['enablement']['installation_id'],old_id)
        selected_catalog(catalog,'1',(proof,));assert_status(('CONFIRMATION_REQUIRED',None),'2')
        catalog=replace(catalog,catalog_revision='3',availability=tuple(replace(x,status='REVOKED',availability_generation='3') if x.installation_id==old_id else x for x in catalog.availability))
        selected_catalog(catalog,'2');assert_status(('UNAVAILABLE','source_unavailable'),'3')
        replay=self.sources.call('create_source_connection_v1',principal,body)
        self.assertEqual((replay['replayed'],replay['representation'],replay['resource']['status']),(True,'historical','ENABLED'))
        # Boundary fixture only: reaching signed64MAX cannot be iterated in a
        # test. Seed a valid canonical head with operator rights in this marked
        # target; production catalog updates still enforce exactly+1 transitions.
        boundary=replace(catalog,catalog_revision='4',availability=tuple(replace(x,availability_generation=str(MAX_COUNTER)) if x.installation_id==old_id else x for x in catalog.availability))
        raw=canonical(primitive(boundary))
        with self.operator.database.engine.begin() as conn:
            execute(conn,'UPDATE wl_sources.catalog_state SET revision=4,digest=:digest,bundle_bytes=:body WHERE id=1',digest=hashlib.sha256(raw).hexdigest(),body=raw)
        use(boundary);assert_status(('UNAVAILABLE','source_counter_exhausted'),str(MAX_COUNTER))
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),2)
        self.assertEqual(self.scalar('SELECT sum(fact_generation) FROM wl_pg.portfolios'),0)


@unittest.skipUnless(CONTENT_ENABLED,'Explicit immutable source image and artifact required')
class SourceOperatorTests(SourceCase):
    installation=ConfiguredSourceCase.installation
    def test_explicit_host_cli_catalog_status_idempotence_and_missing_proof_refusal(self):
        import subprocess
        import sys
        import tempfile
        from wealth_ledger.data_sources.contract_v1 import canonical,primitive
        from wealth_ledger.web_v2.operator import new_private
        with tempfile.TemporaryDirectory(prefix='wealth-ledger-source-cli-') as temporary:
            folder=Path(temporary);secret=folder/'operator.conninfo';key=folder/'identity.key';empty=folder/'empty.json';full=folder/'full.json';proof=folder/'proof.json'
            new_private(secret,self.configs['migration'].conninfo.encode());new_private(key,self.key)
            new_private(empty,canonical(primitive(self.catalog)));catalog,_=installation_fixture();new_private(full,canonical(primitive(catalog)))
            new_private(proof,canonical({'format':'source-proof-input-v1','installations':[
                {'installation_id':installation_id(value),'artifact_file':str(Path(os.environ['WEALTH_LEDGER_SOURCE_ARTIFACT_FILE']).resolve()),'image_root':'/app/src'} for value in catalog.installations]}))
            base=[sys.executable,'-m','wealth_ledger.web_v2','sources']
            flags=['--secret-file',str(secret),'--key-file',str(key),'--runtime-role',self.config['runtime_role'],'--identity-role',self.config['identity_role']]
            def run(operation,path,extra=()):
                value=subprocess.run([*base,operation,*flags,'--source-catalog-file',str(path),*extra],capture_output=True,timeout=30)
                # Never assert with raw stderr/DSN text. The CLI contract is bounded JSON.
                self.assertLess(len(value.stdout)+len(value.stderr),8192)
                return value.returncode,json.loads(value.stdout if value.returncode==0 else value.stderr)
            status,value=run('status',empty);self.assertEqual(status,0);self.assertEqual(value['catalog_revision'],'0')
            serialized=json.dumps(value)
            for private in (self.configs['migration'].conninfo,self.key.hex(),self.config['runtime_role'],self.config['identity_role']):self.assertNotIn(private,serialized)
            status,value=run('catalog-apply',full,['--expected-catalog-revision','0']);self.assertEqual((status,value),(2,{'error':'invalid_config'}))
            extra=['--expected-catalog-revision','0','--source-proof-file',str(proof)]
            status,value=run('catalog-apply',full,extra);self.assertEqual(status,0);self.assertTrue(value['changed'])
            status,value=run('status',full);self.assertEqual(status,0);self.assertEqual(value['installations'],2)
            status,value=run('catalog-apply',full,extra);self.assertEqual((status,value),(2,{'error':'stale_generation'}))
            status,value=run('catalog-apply',full,['--expected-catalog-revision','1']);self.assertEqual(status,0);self.assertFalse(value['changed'])
            # The default identity profile never silently accepts source schema0003.
            result=subprocess.run([sys.executable,'-m','wealth_ledger.web_v2','identity','status','--secret-file',str(secret)],capture_output=True,timeout=10)
            self.assertEqual((result.returncode,json.loads(result.stderr)),(2,{'error':'instance_not_ready'}))


    def test_existing_canonical_connections_count_toward_capacity_without_adoption(self):
        from dataclasses import replace
        from wealth_ledger.domain import canonical_v1 as c
        from wealth_ledger.data_sources.contract_v1 import canonical
        catalog,proofs=installation_fixture()
        apply_catalog(self.operator.database,self.config['runtime_role'],self.config['identity_role'],catalog,expected_revision='0',proofs=proofs)
        self.catalog=catalog;self.sources.close();self.sources=SourceStore(self.configs['identity'],catalog);self.addCleanup(self.sources.close)
        _,principal=self.bootstrap();ConfiguredSourceCase.enable(self,principal)
        # Real restricted functions allocate the first connection. Owner-side
        # fixture writes then populate only pre-existing canonical identities;
        # no sidecars or adoption authorization is manufactured for them.
        body,created=ConfiguredSourceCase.create(self,principal);original=created['resource']['id']
        with self.operator.database.engine.begin() as conn:
            row=execute(conn,'SELECT * FROM wl_pg.connections WHERE tenant_id=:id',id=principal.user_id).mappings().one()
            for _ in range(255):
                rid=str(uuid.uuid4());value=dict(row['body']);value['id']=dict(value['id'])|{'value':rid}
                raw=canonical(value);version=hashlib.sha256(raw).hexdigest()
                execute(conn,"""INSERT INTO wl_pg.connections(tenant_id,portfolio_id,id,version,body,provider,provider_digest,kind,generation)
                    VALUES(:t,:p,:id,:v,CAST(:body AS jsonb),:provider,:digest,'FILE_IMPORT',0)""",
                    t=principal.user_id,p=principal.portfolio_id,id=rid,v=version,body=raw.decode(),provider=row['provider'],digest=row['provider_digest'])
        with self.assertRaisesRegex(SourceError,'source_capacity_reached'):ConfiguredSourceCase.create(self,principal)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.connection_lifecycle'),1)
        self.assertEqual(self.scalar('SELECT count(DISTINCT id) FROM wl_pg.connections'),256)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),2)
        self.assertEqual(self.source_read(principal,'sources_connection_v1',{'connection_id':original})['resource']['id'],original)

    def test_exhausted_source_root_refuses_change_without_financial_or_receipt_effects(self):
        catalog,proofs=installation_fixture()
        apply_catalog(self.operator.database,self.config['runtime_role'],self.config['identity_role'],catalog,expected_revision='0',proofs=proofs)
        self.catalog=catalog;self.sources.close();self.sources=SourceStore(self.configs['identity'],catalog);self.addCleanup(self.sources.close)
        _,principal=self.bootstrap();ConfiguredSourceCase.enable(self,principal)
        self.sql('UPDATE wl_sources.lifecycle_roots SET revision=9223372036854775807')
        before=self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts')
        with self.assertRaisesRegex(SourceError,'source_counter_exhausted'):ConfiguredSourceCase.create(self,principal)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),before)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.connections'),0)
        self.assertEqual(self.scalar('SELECT sum(fact_generation) FROM wl_pg.portfolios'),0)
