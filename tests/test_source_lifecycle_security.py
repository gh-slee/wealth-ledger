"""Effective privilege/body drift must refuse; no operator repair-by-migration."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
import unittest
from test_source_lifecycle import SourceCase,CONTENT_ENABLED
from wealth_ledger.persistence.context import Database,execute
from wealth_ledger.persistence.migration import _role
from wealth_ledger.persistence.source_migration import migrate_sources,verify_inventory
from wealth_ledger.persistence.errors import PersistenceError


class SourceSecurityTests(SourceCase):
    def test_source_ready_inventory_rejects_gateway_raw_column_and_public_function_rights(self):
        statements=[f"GRANT SELECT ON wl_pg.portfolios TO {_role(self.config['identity_role'])}",
                    'GRANT SELECT(id) ON wl_sources.connection_lifecycle TO PUBLIC',
                    'GRANT EXECUTE ON FUNCTION wl_sources.guard_connection_update_v1() TO PUBLIC']
        for sql in statements:
            with self.subTest(sql=sql),self.assertRaisesRegex(PersistenceError,'migration_target_invalid'):
                with self.operator.database.engine.begin() as conn:
                    execute(conn,sql)
                    verify_inventory(conn,runtime_role=self.config['runtime_role'],gateway_role=self.config['identity_role'])
        with self.operator.database.engine.begin() as conn:
            verify_inventory(conn,runtime_role=self.config['runtime_role'],gateway_role=self.config['identity_role'])

    def test_tampered_predecessor_body_refuses_before_any_new_schema_or_replacement(self):
        name,configs,operator,gateway,financial=self.target()
        with operator.database.engine.begin() as conn:
            execute(conn,"""CREATE OR REPLACE FUNCTION wl_identity.identity_status_v1() RETURNS jsonb
                LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS 'SELECT jsonb_build_object(''ok'',false,''code'',''instance_not_ready'')'""")
        source_operator=Database(configs['migration'],schema_mode='sources');self.addCleanup(source_operator.close)
        with self.assertRaisesRegex(PersistenceError,'migration_target_invalid'):
            migrate_sources(source_operator,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),self.catalog)
        with operator.database.engine.begin() as conn:
            self.assertEqual(execute(conn,'SELECT version_num FROM wl_pg.alembic_version').scalar_one(),'0002_identity')
            self.assertIsNone(execute(conn,"SELECT1 FROM pg_catalog.pg_namespace WHERE nspname='wl_sources'".replace('SELECT1','SELECT 1')).scalar())
            self.assertIn('false',execute(conn,"SELECT prosrc FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='wl_identity' AND proname='identity_status_v1'").scalar_one())

    def test_tampered_predecessor_gateway_permissions_refuse_without_silent_repair(self):
        name,configs,operator,gateway,financial=self.target()
        with operator.database.engine.begin() as conn:
            execute(conn,f"GRANT SELECT ON wl_pg.portfolios TO {_role(self.config['identity_role'])}")
        source_operator=Database(configs['migration'],schema_mode='sources');self.addCleanup(source_operator.close)
        with self.assertRaisesRegex(PersistenceError,'migration_target_invalid'):
            migrate_sources(source_operator,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest(),self.catalog)
        with operator.database.engine.begin() as conn:
            self.assertEqual(execute(conn,'SELECT version_num FROM wl_pg.alembic_version').scalar_one(),'0002_identity')
            self.assertTrue(execute(conn,"SELECT has_table_privilege(:role,'wl_pg.portfolios','SELECT')",role=self.config['identity_role']).scalar_one())


    def test_definer_payloads_do_not_coerce_boolean_counter_or_unknown_fields(self):
        _,principal=self.bootstrap()
        base=self.common(principal)|{'plugin_id':'unknown','capability':'PULL_API','enabled':True,'installation_id':'a'*64}
        variants=[base|{'enabled':'true'},base|{'expected_revision':0},base|{'installation_id':True},base|{'unknown':'synthetic-sensitive-text'}]
        for value in variants:
            with self.assertRaisesRegex(Exception,'instance_not_ready'):
                self.sources.call('set_source_enablement_v1',principal,value)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.enablements'),0)


    @unittest.skipUnless(CONTENT_ENABLED,'Explicit immutable source image and artifact required')
    def test_same_version_manifest_or_actual_image_byte_change_cannot_supply_proof(self):
        from dataclasses import replace
        from wealth_ledger.data_sources.contract_v1 import canonical,ContractError
        from wealth_ledger.data_sources.compatibility_v1 import builtin_descriptors
        from wealth_ledger.data_sources.catalog_v1 import verify_installation
        image=os.environ['WEALTH_LEDGER_SOURCE_RUNTIME_IMAGE'];artifact=Path(os.environ['WEALTH_LEDGER_SOURCE_ARTIFACT_FILE']).read_bytes();metadata=json.loads(artifact)
        descriptor=builtin_descriptors(package_distribution=metadata['package_distribution'],package_version=metadata['package_version'],artifact_sha256=hashlib.sha256(artifact).hexdigest(),execution_image_digest=image[7:],entry_point_target='wealth_ledger.source_builtin:registrations')[0]
        bad=json.loads(artifact);bad['files'][0]['sha256']='0'*64;changed=canonical(bad)
        with self.assertRaises(ContractError):verify_installation(replace(descriptor,artifact_sha256=hashlib.sha256(changed).hexdigest()),changed,image_root='/app/src')
        folder=Path('work')/('source-content-negative-'+uuid.uuid4().hex);folder.mkdir(parents=True,mode=0o700)
        suffix=uuid.uuid4().hex;tag='wealth-ledger-proof-base-'+suffix+':test';retained='wealth-ledger-proof-retained-'+suffix+':test'
        def docker(*args):
            value=subprocess.run(['docker',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
            self.assertEqual(value.returncode,0,'Synthetic stopped-image proof setup failed; inspect private Docker diagnostics')
            return value.stdout
        docker('tag',image,retained);docker('tag',image,tag)
        try:
            self.assertEqual(json.loads(docker('image','inspect',tag))[0]['Id'],image)
            (folder/'Dockerfile').write_text('ARG SOURCE_BASE\nFROM ${SOURCE_BASE}\nCOPY synthetic-source.txt /app/src/wealth_ledger/source_builtin.py\n')
            (folder/'synthetic-source.txt').write_bytes(b'invented changed source bytes; never executed\n')
            docker('build','--network','none','--build-arg','SOURCE_BASE='+tag,'--iidfile',str(folder/'image-id'),str(folder))
            altered=(folder/'image-id').read_text().strip();self.assertNotEqual(altered,image)
            base=json.loads(docker('image','inspect',image))[0];child=json.loads(docker('image','inspect',altered))[0]
            self.assertEqual(child['RootFS']['Layers'][:len(base['RootFS']['Layers'])],base['RootFS']['Layers'])
            with self.assertRaises(ContractError):verify_installation(replace(descriptor,execution_image_digest=altered[7:]),artifact,image_root='/app/src')
            self.assertEqual(json.loads(docker('image','inspect',tag))[0]['Id'],image)
            (folder/'receipt.json').write_text(json.dumps({'scope':'STOPPED_CONTENT_NEGATIVE_ONLY','base_image':image,'changed_image':altered,'package_version':descriptor.package_version,'retained_base_tag':retained,'manifest_change':'REJECTED','actual_image_change':'REJECTED','child_started':False},indent=2)+'\n')
        finally:docker('image','rm',tag)
        self.assertEqual(self.scalar('SELECT revision FROM wl_sources.catalog_state'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.installations'),0)
