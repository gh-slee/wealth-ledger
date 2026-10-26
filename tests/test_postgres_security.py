"""Actual nonowner RLS, scoped FKs, privilege and connection reuse acceptance."""
from dataclasses import replace
import uuid
from wealth_ledger.domain.validation_v1 import decode_domain_v1
from wealth_ledger.persistence.context import TenantContext,execute
from wealth_ledger.persistence.errors import PersistenceError
from wealth_ledger.persistence.migration import seed_tenant,migrate
from wealth_ledger.persistence.operations import insert
from wealth_ledger.persistence.repositories import Candidates
from test_postgres_config import PostgresCase

PRIVATE=['tenant_roots','portfolios','issuers','accounts','connections','instruments',
 'candidate_batches','account_aliases','candidate_revisions','candidate_evidence',
 'candidate_snapshots','candidate_items','candidate_activities','candidate_legs',
 'candidate_fees','candidate_coverage','repository_heads','operation_receipts',
 'audit_actions','jobs','job_effect_receipts','outbox']


class SecurityTests(PostgresCase):
    def put(self):Candidates(self.runtime).put(self.context,self.batch_id,self.batch,expected_generation=0,idempotency_key='security-candidate')

    def test_every_private_table_has_enabled_forced_scope_policies(self):
        with self.runtime.engine.connect() as conn:
            rows=execute(conn,"SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wl_pg' AND c.relkind='r'").all()
            matrix={name:(enabled,forced) for name,enabled,forced in rows}
            for name in PRIVATE:self.assertEqual(matrix[name],(True,True),name)
            self.assertEqual(set(matrix)-set(PRIVATE),{'instance_state','alembic_version'})

    def test_runtime_not_owner_or_migrator_and_DDL_TRUNCATE_denied(self):
        from sqlalchemy.exc import DBAPIError
        with self.runtime.engine.connect() as conn:
            row=execute(conn,'SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user').one()
            self.assertEqual(tuple(row),(False,False,False,False))
        for sql in ['CREATE TABLE wl_pg.forbidden(id integer)','ALTER TABLE wl_pg.jobs DISABLE ROW LEVEL SECURITY','TRUNCATE wl_pg.jobs','UPDATE wl_pg.instance_state SET restore_epoch=0','INSERT INTO wl_pg.tenant_roots VALUES(gen_random_uuid(),gen_random_uuid())']:
            with self.subTest(sql=sql),self.assertRaises(DBAPIError):
                with self.runtime.engine.begin() as conn:execute(conn,sql)
        with self.assertRaisesRegex(PersistenceError,'migration_role_required'):migrate(self.runtime,self.settings['runtime_role'])

    def test_missing_wrong_context_and_pooled_rollback_do_not_leak(self):
        self.put()
        with self.runtime.transaction(self.context) as uow:
            self.assertEqual(execute(uow.connection,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),1)
            pid=execute(uow.connection,'SELECT pg_backend_pid()').scalar_one()
        for failure in [False,True]:
            try:
                with self.runtime.transaction(self.context) as uow:
                    if failure:raise RuntimeError('Synthetic failed request')
            except RuntimeError:pass
            with self.runtime.engine.begin() as conn:
                self.assertEqual(execute(conn,'SELECT pg_backend_pid()').scalar_one(),pid)
                self.assertEqual(execute(conn,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),0)
                execute(conn,"SELECT set_config('ledger.tenant_id','malformed',true)")
                self.assertEqual(execute(conn,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),0)
        other=TenantContext(str(uuid.uuid4()),str(uuid.uuid4()));seed_tenant(self.operator,other)
        with self.runtime.transaction(other) as uow:self.assertEqual(execute(uow.connection,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),0)

    def test_swapped_scope_and_forged_satoshi_classification_fail_in_actual_SQL(self):
        self.put()
        with self.operator.engine.begin() as conn:
            row=dict(execute(conn,"SELECT * FROM wl_pg.candidate_legs WHERE tenant_id=:t AND portfolio_id=:p AND requires_satoshi LIMIT 1",t=self.context.tenant_id,p=self.context.portfolio_id).mappings().one())
        row['ordinal']=999;row['requires_satoshi']=False
        from decimal import Decimal
        row['quantity_token']='0.000000001';row['quantity_value']=Decimal('0.000000001')
        with self.assertRaises(PersistenceError):
            with self.runtime.transaction(self.context) as uow:insert(uow,'candidate_legs',{k:v for k,v in row.items() if k not in {'tenant_id','portfolio_id'}})
        other=TenantContext(str(uuid.uuid4()),str(uuid.uuid4()));seed_tenant(self.operator,other)
        raw=self.raw.replace(self.context.tenant_id.encode(),other.tenant_id.encode()).replace(self.context.portfolio_id.encode(),other.portfolio_id.encode());batch=decode_domain_v1(raw);batch_id=str(uuid.uuid4())
        Candidates(self.runtime).put(other,batch_id,batch,expected_generation=0,idempotency_key='other-security-candidate')
        row['batch_id']=batch_id;row['requires_satoshi']=True;row['quantity_token']='0.00000001';row['quantity_value']=Decimal('0.00000001')
        with self.assertRaises(PersistenceError):
            with self.runtime.transaction(other) as uow:insert(uow,'candidate_legs',{k:v for k,v in row.items() if k not in {'tenant_id','portfolio_id'}})

    def test_source_connection_reference_cannot_cross_scope_or_disagree_with_selector(self):
        from wealth_ledger.domain.validation_v1 import encode_domain_v1
        self.put()
        other=TenantContext(str(uuid.uuid4()),str(uuid.uuid4()));seed_tenant(self.operator,other)
        original=self.batch.connections[0].id.value
        raw=self.raw.replace(self.context.tenant_id.encode(),other.tenant_id.encode()).replace(self.context.portfolio_id.encode(),other.portfolio_id.encode()).replace(original.encode(),str(uuid.uuid4()).encode())
        batch=decode_domain_v1(raw)
        Candidates(self.runtime).put(other,str(uuid.uuid4()),batch,expected_generation=0,idempotency_key='foreign-source-candidate')
        with self.operator.engine.begin() as conn:
            row=dict(execute(conn,"SELECT * FROM wl_pg.candidate_revisions WHERE tenant_id=:t AND portfolio_id=:p AND connection_id=:id AND kind='activity' LIMIT 1",t=other.tenant_id,p=other.portfolio_id,id=batch.connections[0].id.value).mappings().one())
        # Correct typed reference, wrong scope: the scoped composite FK must fail.
        with self.assertRaises(PersistenceError):
            with self.runtime.transaction(self.context) as uow:insert(uow,'candidate_revisions',{k:v for k,v in row.items() if k not in {'tenant_id','portfolio_id'}})
        # A locally valid typed reference cannot disguise a different selector source.
        from wealth_ledger.persistence.operations import digest
        row['connection_id']=self.batch.connections[0].id.value;row['connection_version']=digest(self.batch.connections[0])
        with self.assertRaises(PersistenceError):
            with self.runtime.transaction(self.context) as uow:insert(uow,'candidate_revisions',{k:v for k,v in row.items() if k not in {'tenant_id','portfolio_id'}})

    def test_pooled_savepoint_rollback_and_query_cancellation_clear_scope(self):
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy.exc import DBAPIError
        import threading
        import time
        self.put()
        with self.runtime.transaction(self.context) as uow:
            pid=execute(uow.connection,'SELECT pg_backend_pid()').scalar_one()
            nested=uow.connection.begin_nested()
            execute(uow.connection,"SELECT set_config('ledger.tenant_id',:value,true)",value=str(uuid.uuid4()))
            self.assertEqual(execute(uow.connection,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),0)
            nested.rollback()
            self.assertEqual(execute(uow.connection,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),1)
        with self.runtime.transaction(self.context) as uow:
            uow.connection.rollback()
        with self.runtime.engine.begin() as conn:
            self.assertEqual(execute(conn,'SELECT pg_backend_pid()').scalar_one(),pid)
            self.assertEqual(execute(conn,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),0)
        with self.assertRaises(PersistenceError):
            with self.runtime.transaction(self.context) as uow,ThreadPoolExecutor(max_workers=1) as pool:
                driver=uow.connection.connection.driver_connection
                def cancel():
                    time.sleep(.1);driver.cancel()
                future=pool.submit(cancel)
                try:execute(uow.connection,'SELECT pg_sleep(2)')
                finally:future.result(timeout=5)
        with self.runtime.engine.begin() as conn:
            self.assertEqual(execute(conn,'SELECT pg_backend_pid()').scalar_one(),pid)
            self.assertEqual(execute(conn,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),0)
        with self.runtime.transaction(self.context) as uow:
            self.assertEqual(execute(uow.connection,'SELECT count(*) FROM wl_pg.candidate_batches').scalar_one(),1)

    def test_missing_scope_write_and_role_escalation_are_denied(self):
        from sqlalchemy.exc import DBAPIError
        self.put()
        with self.assertRaises(DBAPIError):
            with self.runtime.engine.begin() as conn:
                execute(conn,"INSERT INTO wl_pg.candidate_batches(tenant_id,portfolio_id,id,digest,canonical_bytes,contract_version,profile,mapping_revision) VALUES(:t,:p,:id,encode(sha256(:raw),'hex'),:raw,1,'decimal-38s-24f-38i-v1','synthetic')",t=self.context.tenant_id,p=self.context.portfolio_id,id=str(uuid.uuid4()),raw=self.raw)
        with self.assertRaises(DBAPIError):
            with self.runtime.engine.begin() as conn:
                execute(conn,'SET ROLE '+self.settings['migration_role'])

    def test_selector_provider_must_match_referenced_connection_version(self):
        import hashlib
        import json
        from wealth_ledger.persistence.operations import canonical
        self.put()
        with self.operator.engine.begin() as conn:
            row=dict(execute(conn,"SELECT * FROM wl_pg.candidate_revisions WHERE tenant_id=:t AND portfolio_id=:p AND kind='activity' LIMIT 1",t=self.context.tenant_id,p=self.context.portfolio_id).mappings().one())
        selector=json.loads(row['selector_text']);selector[1]='different.synthetic.provider'
        row.update(selector_text=canonical(selector),logical_selector_text=canonical(selector[:-1]),provider_digest=hashlib.sha256(selector[1].encode()).hexdigest())
        row.update(key=hashlib.sha256(row['selector_text'].encode()).hexdigest(),logical_key=hashlib.sha256(row['logical_selector_text'].encode()).hexdigest())
        with self.assertRaises(PersistenceError):
            with self.runtime.transaction(self.context) as uow:insert(uow,'candidate_revisions',{k:v for k,v in row.items() if k not in {'tenant_id','portfolio_id'}})
