"""Real PG job leases, cancellation, lost notifications and receipt effects."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import uuid
from wealth_ledger.persistence.context import execute,Database,COUNTER_MAX,TenantContext
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.persistence.errors import PersistenceError
from wealth_ledger.persistence.jobs import Jobs
from wealth_ledger.persistence.outbox import relay
from wealth_ledger.persistence.repositories import Candidates
from test_postgres_config import PostgresCase


class JobTests(PostgresCase):
    def job(self,key='foundation-job',generation=0):
        return Jobs(self.runtime).enqueue(self.context,key,{'resource_id':self.batch_id,'version':'1'},expected_generation=generation)

    def expire(self,job):
        with self.operator.engine.begin() as conn:
            execute(conn,"UPDATE wl_pg.jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE tenant_id=:t AND portfolio_id=:p AND id=:id",t=self.context.tenant_id,p=self.context.portfolio_id,id=job)

    def test_duplicate_claim_and_lost_lease_cannot_commit(self):
        job=self.job();service=Jobs(self.runtime);old=service.claim(self.context,str(uuid.uuid4()))
        self.assertIsNone(service.claim(self.context,str(uuid.uuid4())))
        self.expire(job);new=service.claim(self.context,str(uuid.uuid4()));self.assertGreater(new.token,old.token)
        for action in [lambda:service.heartbeat(old),lambda:service.complete(old),lambda:service.fail(old)]:
            with self.assertRaisesRegex(PersistenceError,'lease_lost'):action()
        service.heartbeat(new);result=service.complete(new);self.assertEqual(service.complete(new),result)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p'),1)

    def test_cancelled_worker_and_terminal_effect_cannot_be_overwritten(self):
        job=self.job();service=Jobs(self.runtime);lease=service.claim(self.context,str(uuid.uuid4()));service.cancel(self.context,job)
        with self.assertRaisesRegex(PersistenceError,'lease_lost'):service.complete(lease)
        self.assertEqual(self.scalar('SELECT status FROM wl_pg.jobs WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',id=job),'cancelled')
        self.job('another-foundation-job');lease=service.claim(self.context,str(uuid.uuid4()));service.complete(lease)
        with self.assertRaisesRegex(PersistenceError,'job_state'):service.cancel(self.context,lease.job_id)

    def test_expired_final_attempt_becomes_visible_failed_job(self):
        job=self.job();service=Jobs(self.runtime)
        for expected in [1,2,3]:
            lease=service.claim(self.context,str(uuid.uuid4()));self.assertEqual(lease.attempt,expected);self.expire(job)
        self.assertIsNone(service.claim(self.context,str(uuid.uuid4())))
        self.assertEqual(self.scalar('SELECT status FROM wl_pg.jobs WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',id=job),'failed')

    def test_stale_generation_and_failure_before_commit_leave_no_effect(self):
        self.job();service=Jobs(self.runtime);lease=service.claim(self.context,str(uuid.uuid4()))
        def fault(stage):
            if stage=='before_commit':raise RuntimeError('Synthetic transaction failure')
        with self.assertRaises(RuntimeError):service.complete(lease,fault=fault)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p'),0)
        Candidates(self.runtime).put(self.context,self.batch_id,self.batch,expected_generation=0,idempotency_key='advance-generation')
        with self.assertRaisesRegex(PersistenceError,'stale_generation'):service.complete(lease)

    def test_outbox_relay_rollback_recovery_and_repeat_are_one_job(self):
        Candidates(self.runtime).put(self.context,self.batch_id,self.batch,expected_generation=0,idempotency_key='outbox-producer')
        def fault(stage):raise RuntimeError('Synthetic relay crash')
        with self.assertRaises(RuntimeError):relay(self.runtime,self.context,fault=fault)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.jobs WHERE tenant_id=:t AND portfolio_id=:p'),0)
        self.assertEqual(len(relay(self.runtime,self.context)),1);self.assertEqual(relay(self.runtime,self.context),[])

    def test_two_actual_workers_claim_different_jobs(self):
        self.job('worker-one-job');self.job('worker-two-job')
        database=Database(PostgresConfig.from_secret_file(self.settings['runtime_secret_file'],pool_size=2));self.addCleanup(database.close)
        barrier=threading.Barrier(2)
        def worker(_):barrier.wait(timeout=5);return Jobs(database).claim(self.context,str(uuid.uuid4()))
        with ThreadPoolExecutor(max_workers=2) as pool:leases=list(pool.map(worker,[1,2]))
        self.assertNotEqual(leases[0].job_id,leases[1].job_id)

    def test_fencing_counter_overflow_refuses_without_wrapping(self):
        job=self.job()
        with self.operator.engine.begin() as conn:execute(conn,'UPDATE wl_pg.jobs SET fencing_token=:value WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',t=self.context.tenant_id,p=self.context.portfolio_id,id=job,value=COUNTER_MAX)
        with self.assertRaisesRegex(PersistenceError,'counter_exhausted'):Jobs(self.runtime).claim(self.context,str(uuid.uuid4()))

    def test_lease_expiry_is_checked_after_waiting_for_root_lock(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        self.job();service=Jobs(self.runtime);lease=service.claim(self.context,str(uuid.uuid4()))
        started=threading.Event();original=self.runtime.transaction
        @contextmanager
        def marked(context,**options):
            with original(context,**options) as uow:
                started.set();yield uow
        def worker():
            try:service.complete(lease);return 'unexpected_commit'
            except PersistenceError as error:return error.code
        with ThreadPoolExecutor(max_workers=1) as pool,patch.object(self.runtime,'transaction',marked):
            with self.operator.engine.begin() as conn:
                execute(conn,'SELECT fact_generation FROM wl_pg.portfolios WHERE tenant_id=:t AND portfolio_id=:p FOR UPDATE',t=self.context.tenant_id,p=self.context.portfolio_id)
                future=pool.submit(worker);self.assertTrue(started.wait(5))
                execute(conn,"UPDATE wl_pg.jobs SET lease_expires_at=clock_timestamp()+interval '0.15 second' WHERE tenant_id=:t AND portfolio_id=:p AND id=:id",t=self.context.tenant_id,p=self.context.portfolio_id,id=lease.job_id)
                execute(conn,'SELECT pg_sleep(0.25)')
            self.assertEqual(future.result(timeout=5),'lease_lost')
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p'),0)

    def test_lease_handles_cannot_bypass_duration_or_counter_bounds(self):
        self.job();lease=Jobs(self.runtime).claim(self.context,str(uuid.uuid4()))
        for changes in [{'lease_seconds':3601},{'token':True},{'attempt':0},{'epoch':-1},{'expected_generation':False}]:
            with self.subTest(changes=changes),self.assertRaises(PersistenceError):replace(lease,**changes)

    def test_persisted_job_fields_cannot_be_rebased_or_erased_by_lease_copy(self):
        from wealth_ledger.persistence.operations import digest
        Candidates(self.runtime).put(self.context,self.batch_id,self.batch,expected_generation=0,idempotency_key='lease-binding-candidate')
        connection=self.batch.connections[0]
        service=Jobs(self.runtime)
        service.enqueue(self.context,'bound-request-job',{'resource_id':self.batch_id,'version':'1'},expected_generation=1,
                        connection=(connection.id.value,digest(connection),0))
        lease=service.claim(self.context,str(uuid.uuid4()))
        with self.operator.engine.begin() as conn:
            execute(conn,'UPDATE wl_pg.connections SET generation=1 WHERE tenant_id=:t AND portfolio_id=:p AND id=:id AND version=:version',t=self.context.tenant_id,p=self.context.portfolio_id,id=connection.id.value,version=digest(connection))
        changes=[{}, {'connection_id':None,'connection_version':None,'connection_generation':None},
                 {'connection_generation':1},{'connection_id':str(uuid.uuid4())},{'connection_version':'f'*64},
                 {'expected_generation':2},{'attempt':2},{'lease_seconds':120}]
        for change in changes:
            forged=replace(lease,**change)
            with self.subTest(change=change),self.assertRaisesRegex(PersistenceError,'lease_lost'):
                service.complete(forged)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p'),0)
        self.assertEqual(self.scalar('SELECT fact_generation FROM wl_pg.portfolios WHERE tenant_id=:t AND portfolio_id=:p'),1)
        for change in [{'attempt':2},{'lease_seconds':120},{'expected_generation':2}]:
            with self.subTest(heartbeat=change),self.assertRaisesRegex(PersistenceError,'lease_lost'):
                service.heartbeat(replace(lease,**change))

    def test_stale_generation_lease_cannot_be_rebased_to_current(self):
        self.job();service=Jobs(self.runtime);lease=service.claim(self.context,str(uuid.uuid4()))
        Candidates(self.runtime).put(self.context,self.batch_id,self.batch,expected_generation=0,idempotency_key='rebase-prohibited')
        with self.assertRaisesRegex(PersistenceError,'stale_generation'):service.complete(lease)
        with self.assertRaisesRegex(PersistenceError,'lease_lost'):service.complete(replace(lease,expected_generation=1))
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p'),0)

    def test_actual_worker_process_kills_before_and_after_commit_recover_once(self):
        import json
        import os
        import subprocess
        import sys
        from dataclasses import asdict
        from wealth_ledger.persistence.jobs import Lease
        service=Jobs(self.runtime)
        program="""import json,os,signal,sys
from dataclasses import asdict
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.persistence.context import Database,TenantContext
from wealth_ledger.persistence.jobs import Jobs,Lease
payload=json.loads(sys.stdin.readline());database=Database(PostgresConfig.from_secret_file(payload['secret_file']));jobs=Jobs(database)
if payload['mode']=='claim':
 context=TenantContext(**payload['context']);lease=jobs.claim(context,payload['worker_id'],lease_seconds=15)
 print(json.dumps(asdict(lease)),flush=True);sys.stdin.readline()
else:
 fields=payload['lease'];fields['context']=TenantContext(**fields['context']);lease=Lease(**fields)
 if payload['mode']=='before_commit':
  def fault(stage):
   if stage=='before_commit':print('uncommitted',flush=True);sys.stdin.readline()
  jobs.complete(lease,fault=fault)
 else:
  jobs.complete(lease);os.kill(os.getpid(),signal.SIGKILL)
"""
        def child(payload):
            payload['secret_file']=self.settings['runtime_secret_file']
            process=subprocess.Popen([sys.executable,'-c',program],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            self.addCleanup(lambda:process.kill() if process.poll() is None else None)
            process.stdin.write(json.dumps(payload)+'\n');process.stdin.flush()
            return process
        self.job('process-after-claim');process=child({'mode':'claim','context':asdict(self.context),'worker_id':str(uuid.uuid4())})
        fields=json.loads(process.stdout.readline());fields['context']=TenantContext(**fields['context']);old=Lease(**fields)
        process.kill();process.communicate(timeout=5);self.assertLess(process.returncode,0)
        self.expire(old.job_id);new=service.claim(self.context,str(uuid.uuid4()));self.assertGreater(new.token,old.token)
        with self.assertRaisesRegex(PersistenceError,'lease_lost'):service.complete(old)
        result=service.complete(new)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p'),1)
        self.job('process-before-commit',generation=1);lease=service.claim(self.context,str(uuid.uuid4()))
        process=child({'mode':'before_commit','lease':asdict(lease)})
        self.assertEqual(process.stdout.readline().strip(),'uncommitted')
        process.kill();process.communicate(timeout=5);self.assertLess(process.returncode,0)
        # PostgreSQL observes the dead client's disconnect and rolls back all writes.
        result=service.complete(lease)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p'),2)
        self.job('process-after-commit',generation=2);lease=service.claim(self.context,str(uuid.uuid4()))
        process=child({'mode':'after_commit','lease':asdict(lease)});output,error=process.communicate(timeout=10)
        self.assertLess(process.returncode,0);self.assertEqual(output,'');self.assertEqual(error,'')
        result=service.complete(lease);self.assertEqual(result['generation'],'3')
        self.assertEqual(service.complete(lease),result)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p'),3)
