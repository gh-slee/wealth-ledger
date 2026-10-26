"""Actual PG migration failure, serialized owners and two fresh-target restores."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import threading
import uuid
from wealth_ledger.domain.validation_v1 import encode_domain_v1
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.persistence.context import Database,execute
from wealth_ledger.persistence.errors import PersistenceError
from wealth_ledger.persistence.jobs import Jobs
from wealth_ledger.persistence.migration import migrate,finalize_restore
from wealth_ledger.persistence.repositories import Candidates
from test_postgres_config import PostgresCase


class MigrationTests(PostgresCase):
    def target(self):
        from psycopg.conninfo import make_conninfo
        label=subprocess.check_output(['docker','inspect','--format','{{index .Config.Labels "wealth-ledger.test"}}',self.settings['container']],text=True).strip()
        self.assertEqual(label,'pg-foundation')
        name='wl_test_restore_'+uuid.uuid4().hex[:16]
        statement='CREATE DATABASE "'+name+'" OWNER "'+self.settings['migration_role']+'"'
        subprocess.run(['docker','exec',self.settings['container'],'psql','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-c',statement],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        from pathlib import Path
        op=Database(PostgresConfig(make_conninfo(Path(self.settings['migration_secret_file']).read_text(),dbname=name)))
        rt=Database(PostgresConfig(make_conninfo(Path(self.settings['runtime_secret_file']).read_text(),dbname=name),pool_size=1))
        self.addCleanup(op.close);self.addCleanup(rt.close)
        return name,op,rt

    def test_migration_failure_rolls_back_and_unknown_nonempty_target_refuses(self):
        _,operator,_=self.target()
        def fail(stage):raise RuntimeError('Synthetic DDL interruption')
        with self.assertRaises(RuntimeError):migrate(operator,self.settings['runtime_role'],fault=fail)
        with operator.engine.connect() as conn:self.assertEqual(execute(conn,"SELECT count(*) FROM pg_tables WHERE schemaname='wl_pg'").scalar_one(),0)
        with operator.engine.begin() as conn:execute(conn,'CREATE TABLE public.synthetic_unknown(id integer)')
        with self.assertRaisesRegex(PersistenceError,'migration_target_invalid'):migrate(operator,self.settings['runtime_role'])

    def test_concurrent_migration_owners_serialize_and_newer_schema_refuses(self):
        name,operator,_=self.target()
        from pathlib import Path
        from psycopg.conninfo import make_conninfo
        concurrent=Database(PostgresConfig(make_conninfo(Path(self.settings['migration_secret_file']).read_text(),dbname=name),pool_size=2));self.addCleanup(concurrent.close)
        barrier=threading.Barrier(2)
        def migrate_once(_):barrier.wait(timeout=5);return migrate(concurrent,self.settings['runtime_role'])['schema_revision']
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(migrate_once,[1,2]))
        self.assertEqual(result,['0001_foundation','0001_foundation'])
        with operator.engine.begin() as conn:execute(conn,"UPDATE wl_pg.alembic_version SET version_num='future_unknown'")
        with self.assertRaisesRegex(PersistenceError,'schema_unsupported'):migrate(operator,self.settings['runtime_role'])

    def test_matching_dump_restores_twice_and_never_revalidates_old_lease(self):
        Candidates(self.runtime).put(self.context,self.batch_id,self.batch,expected_generation=0,idempotency_key='restore-source-candidate')
        jobs=Jobs(self.runtime);jobs.enqueue(self.context,'restore-completed-job',{'resource_id':self.batch_id,'version':'1'},expected_generation=1)
        finished=jobs.claim(self.context,str(uuid.uuid4()));jobs.complete(finished)
        jobs.enqueue(self.context,'restore-running-job',{'resource_id':self.batch_id,'version':'1'},expected_generation=2)
        old=jobs.claim(self.context,str(uuid.uuid4()))
        dump=subprocess.run(['docker','exec',self.settings['container'],'pg_dump','-U','postgres','--format=custom','--no-owner','--no-acl','--dbname='+self.settings['database']],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
        restored=[]
        for _ in range(2):
            name,operator,runtime=self.target()
            subprocess.run(['docker','exec','-i',self.settings['container'],'pg_restore','-U','postgres','--exit-on-error','--no-owner','--no-acl','--role='+self.settings['migration_role'],'--dbname='+name],input=dump,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            state=finalize_restore(operator,self.settings['runtime_role']);restored.append((operator,runtime,state))
            self.assertEqual(encode_domain_v1(Candidates(runtime).read(self.context,self.batch_id)),self.raw)
            with self.assertRaisesRegex(PersistenceError,'lease_lost'):Jobs(runtime).complete(old)
            with runtime.transaction(self.context,readonly=True) as uow:self.assertEqual(execute(uow.connection,'SELECT count(*) FROM wl_pg.job_effect_receipts').scalar_one(),1)
        self.assertEqual(restored[0][2]['restore_epoch'],restored[1][2]['restore_epoch'])
        self.assertNotEqual(restored[0][2]['incarnation'],restored[1][2]['incarnation'])
        handle=Jobs(restored[0][1]).claim(self.context,str(uuid.uuid4()))
        operator,runtime,_=restored[1]
        # Match every restored job field; only the fresh incarnation should fence it.
        with operator.engine.begin() as conn:
            execute(conn,"UPDATE wl_pg.jobs SET status='running',worker_id=:worker,fencing_token=:token,attempt=:attempt,lease_expires_at=clock_timestamp()+interval '60 seconds' WHERE tenant_id=:t AND portfolio_id=:p AND id=:id",t=self.context.tenant_id,p=self.context.portfolio_id,id=handle.job_id,worker=handle.worker_id,token=handle.token,attempt=handle.attempt)
        with self.assertRaisesRegex(PersistenceError,'lease_lost'):Jobs(runtime).complete(handle)

    def test_operator_status_and_saved_candidate_survive_real_test_container_restart(self):
        import time
        label=subprocess.check_output(['docker','inspect','--format','{{index .Config.Labels "wealth-ledger.test"}}',self.settings['container']],text=True).strip()
        self.assertEqual(label,'pg-foundation')
        Candidates(self.runtime).put(self.context,self.batch_id,self.batch,expected_generation=0,idempotency_key='restart-source-candidate')
        before=self.runtime.status()
        subprocess.run(['docker','restart',self.settings['container']],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=30)
        deadline=time.monotonic()+30
        while True:
            try:
                after=self.runtime.status();break
            except PersistenceError:
                if time.monotonic()>=deadline:raise
                time.sleep(.1)
        self.assertEqual(before,after)
        self.assertEqual(encode_domain_v1(Candidates(self.runtime).read(self.context,self.batch_id)),self.raw)
        self.assertEqual(migrate(self.operator,self.settings['runtime_role']),before)
