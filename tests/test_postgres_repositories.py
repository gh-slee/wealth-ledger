"""Actual PostgreSQL candidate storage/revision/receipt/CAS fault acceptance."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import threading
import uuid
from wealth_ledger.domain.canonical_v1 import ExternalSourceRefV1
from wealth_ledger.domain.validation_v1 import encode_domain_v1
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.persistence.context import Database
from wealth_ledger.persistence.errors import PersistenceError
from wealth_ledger.persistence.repositories import Candidates,selector_identity
from test_postgres_config import PostgresCase,FIXTURES


class RepositoryTests(PostgresCase):
    def put(self,**options):
        return Candidates(self.runtime).put(self.context,self.batch_id,self.batch,expected_generation=0,idempotency_key='candidate-first',**options)

    def test_complete_canonical_bytes_and_typed_counts_roundtrip(self):
        result=self.put();self.assertIs(result['ingestible'],False)
        self.assertEqual(encode_domain_v1(Candidates(self.runtime).read(self.context,self.batch_id)),self.raw)
        expected=json.loads((FIXTURES/'oracles.json').read_text())['golden_complete']['expected_counts']
        tables={'accounts':'accounts','connections':'connections','aliases':'account_aliases','instruments':'instruments','issuers':'issuers','coverage':'candidate_coverage','snapshots':'candidate_snapshots','items':'candidate_items','activities':'candidate_activities','legs':'candidate_legs','fees':'candidate_fees'}
        for key,table in tables.items():
            self.assertEqual(self.scalar(f'SELECT count(*) FROM wl_pg.{table} WHERE tenant_id=:t AND portfolio_id=:p'),expected[key],table)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.candidate_items WHERE tenant_id=:t AND portfolio_id=:p AND cost_native_token IS NULL AND cost_native_value IS NULL'),4)

    def test_replay_before_generation_and_changed_request_conflict(self):
        result=self.put();self.assertEqual(self.put(),result)
        with self.assertRaisesRegex(PersistenceError,'request_conflict'):
            Candidates(self.runtime).put(self.context,str(uuid.uuid4()),self.batch,expected_generation=0,idempotency_key='candidate-first')
        self.assertEqual(self.scalar('SELECT fact_generation FROM wl_pg.portfolios WHERE tenant_id=:t AND portfolio_id=:p'),1)

    def corrected(self):
        old=self.batch.activities[0];identity=replace(old.identity,source=replace(old.identity.source,revision='r2'),change='correction',parent=ExternalSourceRefV1(self.context.tenant_id,self.context.portfolio_id,old.identity.source),reason='Synthetic correction')
        return replace(self.batch,activities=(replace(old,identity=identity),)+self.batch.activities[1:])

    def test_same_fact_UUID_new_revision_and_missing_parent_are_distinct(self):
        changed=self.corrected()
        with self.assertRaisesRegex(PersistenceError,'parent_missing'):
            Candidates(self.runtime).put(self.context,str(uuid.uuid4()),changed,expected_generation=0,idempotency_key='missing-parent')
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.candidate_batches WHERE tenant_id=:t AND portfolio_id=:p'),0)
        self.put();second=str(uuid.uuid4())
        Candidates(self.runtime).put(self.context,second,changed,expected_generation=1,idempotency_key='correction-next')
        self.assertEqual(self.scalar("SELECT count(*) FROM wl_pg.candidate_revisions WHERE tenant_id=:t AND portfolio_id=:p AND kind='activity'"),3)
        self.assertEqual(encode_domain_v1(Candidates(self.runtime).read(self.context,self.batch_id)),self.raw)

    def test_historical_declaration_versions_do_not_rewrite_old_candidate(self):
        self.put();changed=replace(self.batch,instruments=(replace(self.batch.instruments[0],source_descriptor='Changed synthetic descriptor'),)+self.batch.instruments[1:])
        second=str(uuid.uuid4());Candidates(self.runtime).put(self.context,second,changed,expected_generation=1,idempotency_key='declaration-next')
        self.assertEqual(encode_domain_v1(Candidates(self.runtime).read(self.context,self.batch_id)),self.raw)
        self.assertEqual(Candidates(self.runtime).read(self.context,second),changed)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.instruments WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',id=self.batch.instruments[0].id.value),2)

    def test_rollback_after_every_phase_retains_no_partial_effect(self):
        stages=['after_declarations','after_revisions','after_typed_rows','after_heads','after_effect','after_receipt','after_generation','before_commit']
        for stage in stages:
            def fault(current):
                if current==stage:raise RuntimeError('Synthetic injected fault')
            with self.subTest(stage=stage),self.assertRaises(RuntimeError):self.put(fault=fault)
            for table in ['candidate_batches','accounts','candidate_revisions','operation_receipts','outbox']:
                self.assertEqual(self.scalar(f'SELECT count(*) FROM wl_pg.{table} WHERE tenant_id=:t AND portfolio_id=:p'),0)
            self.assertEqual(self.scalar('SELECT fact_generation FROM wl_pg.portfolios WHERE tenant_id=:t AND portfolio_id=:p'),0)
        self.put()

    def test_explicit_candidate_head_CAS_is_atomic(self):
        key,logical,_,_=selector_identity(self.batch.activities[0].identity.source)
        self.put(head_updates=((logical,None,key),))
        changed=self.corrected();new,_,_,_=selector_identity(changed.activities[0].identity.source)
        with self.assertRaisesRegex(PersistenceError,'stale_generation'):
            Candidates(self.runtime).put(self.context,str(uuid.uuid4()),changed,expected_generation=1,idempotency_key='head-wrong-value',head_updates=((logical,None,new),))
        Candidates(self.runtime).put(self.context,str(uuid.uuid4()),changed,expected_generation=1,idempotency_key='head-correct-value',head_updates=((logical,key,new),))
        self.assertEqual(self.scalar('SELECT revision_key FROM wl_pg.repository_heads WHERE tenant_id=:t AND portfolio_id=:p AND logical_key=:logical',logical=logical),new)

    def test_actual_concurrent_generation_CAS_has_one_winner(self):
        database=Database(PostgresConfig.from_secret_file(self.settings['runtime_secret_file'],pool_size=2));self.addCleanup(database.close)
        barrier=threading.Barrier(2)
        def writer(number):
            barrier.wait(timeout=5)
            try:
                return Candidates(database).put(self.context,str(uuid.uuid4()),self.batch,expected_generation=0,idempotency_key='parallel-'+str(number))['generation']
            except PersistenceError as error:return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(writer,[1,2]))
        self.assertCountEqual(results,['1','stale_generation'])
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.operation_receipts WHERE tenant_id=:t AND portfolio_id=:p'),1)

    def test_database_generated_retry_failures_are_bounded_and_atomic(self):
        from unittest.mock import patch
        from wealth_ledger.persistence import repositories
        from wealth_ledger.persistence.context import execute
        original=repositories.insert;attempts=[]
        def fail_in_postgres(uow,table,values,**options):
            result=original(uow,table,values,**options)
            if table=='issuers':
                attempts.append(1)
                execute(uow.connection,"DO $$ BEGIN RAISE EXCEPTION 'synthetic serialization fault' USING ERRCODE='40001'; END $$")
            return result
        with patch.object(repositories,'insert',side_effect=fail_in_postgres):
            with self.assertRaisesRegex(PersistenceError,'retry_exhausted'):self.put()
        self.assertEqual(len(attempts),3)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.candidate_batches WHERE tenant_id=:t AND portfolio_id=:p'),0)
        self.assertEqual(self.scalar('SELECT fact_generation FROM wl_pg.portfolios WHERE tenant_id=:t AND portfolio_id=:p'),0)

    def test_actual_PostgreSQL_deadlock_restarts_one_whole_transaction(self):
        from unittest.mock import patch
        from wealth_ledger.persistence import repositories
        from wealth_ledger.persistence.context import execute,TenantContext
        from wealth_ledger.persistence.migration import seed_tenant
        from wealth_ledger.domain.validation_v1 import decode_domain_v1
        database=Database(PostgresConfig.from_secret_file(self.settings['runtime_secret_file'],pool_size=2));self.addCleanup(database.close)
        other=TenantContext(str(uuid.uuid4()),str(uuid.uuid4()));seed_tenant(self.operator,other)
        raw=self.raw.replace(self.context.tenant_id.encode(),other.tenant_id.encode()).replace(self.context.portfolio_id.encode(),other.portfolio_id.encode());second=decode_domain_v1(raw)
        keys=[uuid.uuid4().int%(2**62),uuid.uuid4().int%(2**62)];barrier=threading.Barrier(2);attempts={self.context.tenant_id:0,other.tenant_id:0};original=repositories.insert
        def race(uow,table,values,**options):
            result=original(uow,table,values,**options)
            if table=='issuers':
                index=0 if uow.context==self.context else 1;attempts[uow.context.tenant_id]+=1
                execute(uow.connection,'SELECT pg_advisory_xact_lock(:key)',key=keys[index])
                if attempts[uow.context.tenant_id]==1:barrier.wait(timeout=5)
                execute(uow.connection,'SELECT pg_advisory_xact_lock(:key)',key=keys[1-index])
            return result
        def writer(pair):
            context,batch=pair
            return Candidates(database).put(context,str(uuid.uuid4()),batch,expected_generation=0,idempotency_key='real-deadlock')
        with patch.object(repositories,'insert',side_effect=race),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(writer,[(self.context,self.batch),(other,second)]))
        self.assertEqual([r['generation'] for r in results],['1','1'])
        self.assertCountEqual(list(attempts.values()),[1,2])

    def test_maximal_multibyte_and_escaped_selectors_preserve_domain_bytes(self):
        import test_domain_v1 as fixture
        base=fixture.with_events(fixture.event())
        from wealth_ledger.domain.validation_v1 import decode_domain_v1
        base=decode_domain_v1(encode_domain_v1(base).replace(base.tenant_id.encode(),self.context.tenant_id.encode()).replace(base.portfolio_id.encode(),self.context.portfolio_id.encode()))
        for index,text in enumerate(['🌞'*4096, '\"'*4096]):
            provider='p'*4096;first=base.connections[0]
            batch=replace(base,connections=(replace(first,provider=provider),)+base.connections[1:],
                aliases=tuple(replace(a,provider=provider,source_account_key=text if a.source_account_key=='tf' else a.source_account_key) if a.connection==first.id else a for a in base.aliases),
                coverage=(replace(base.coverage[0],source_account_key=text,observation_id=text),),
                activities=(replace(base.activities[0],identity=replace(base.activities[0].identity,source=replace(base.activities[0].identity.source,provider=provider,source_account_key=text,source_id=text,observation_id=text,revision=text))),))
            raw=encode_domain_v1(batch);batch_id=str(uuid.uuid4())
            repository=Candidates(self.runtime)
            repository.put(self.context,batch_id,batch,expected_generation=index,idempotency_key='maximal-selector-'+str(index))
            self.assertEqual(encode_domain_v1(repository.read(self.context,batch_id)),raw)

    def test_unrepresentable_NUL_is_bounded_before_any_SQL(self):
        from unittest.mock import patch
        candidates=[replace(self.batch,provenance=replace(self.batch.provenance,adapter='synthetic\x00adapter')),
                    replace(self.batch,provenance=replace(self.batch.provenance,adapter_version='synthetic\x00version'))]
        for batch in candidates:
            encode_domain_v1(batch)
            with self.subTest(batch=batch.provenance.adapter),patch.object(self.runtime,'transaction',side_effect=AssertionError('No SQL for unrepresentable candidate')):
                with self.assertRaisesRegex(PersistenceError,'invalid_candidate'):
                    Candidates(self.runtime).put(self.context,self.batch_id,batch,expected_generation=0,idempotency_key='unrepresentable-candidate')
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.candidate_batches WHERE tenant_id=:t AND portfolio_id=:p'),0)

    def test_same_candidate_new_key_only_binds_receipt_without_duplicate_effect(self):
        original=self.put();repository=Candidates(self.runtime)
        result=repository.put(self.context,self.batch_id,self.batch,expected_generation=1,idempotency_key='fresh-replay-key')
        self.assertEqual(result,original)
        for table in ['candidate_batches','audit_actions','outbox']:
            self.assertEqual(self.scalar(f'SELECT count(*) FROM wl_pg.{table} WHERE tenant_id=:t AND portfolio_id=:p'),1)
        self.assertEqual(self.scalar('SELECT fact_generation FROM wl_pg.portfolios WHERE tenant_id=:t AND portfolio_id=:p'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.operation_receipts WHERE tenant_id=:t AND portfolio_id=:p'),2)
        self.assertEqual(repository.put(self.context,self.batch_id,self.batch,expected_generation=1,idempotency_key='fresh-replay-key'),original)
        with self.assertRaisesRegex(PersistenceError,'request_conflict'):
            repository.put(self.context,str(uuid.uuid4()),self.batch,expected_generation=1,idempotency_key='fresh-replay-key')
        # Explicit head changes remain real CAS operations even on existing bytes.
        key,logical,_,_=selector_identity(self.batch.activities[0].identity.source)
        result=repository.put(self.context,self.batch_id,self.batch,expected_generation=1,idempotency_key='existing-batch-head',head_updates=((logical,None,key),))
        self.assertEqual(result['generation'],'2')
        # Saved no-op key replays before generation checks too.
        self.assertEqual(repository.put(self.context,self.batch_id,self.batch,expected_generation=1,idempotency_key='fresh-replay-key'),original)
