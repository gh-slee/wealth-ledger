"""Tenant-bound PostgreSQL job leases; no broker/import/export handler is enabled."""
from dataclasses import dataclass
import uuid
import re
from .context import COUNTER_MAX, TenantContext, execute, identifier
from .errors import CODES, PersistenceError
from .operations import atomic, canonical, digest, insert, lock_root, parameters, validate_key


@dataclass(frozen=True, slots=True)
class Lease:
    context: object
    job_id: str
    worker_id: str
    token: int
    attempt: int
    incarnation: str
    epoch: int
    lease_seconds: int
    request_digest: str
    expected_generation: int
    connection_id: str | None
    connection_version: str | None
    connection_generation: int | None

    def __post_init__(self):
        if type(self.context) is not TenantContext:
            raise PersistenceError('lease_lost')
        identifier(self.job_id);identifier(self.worker_id);identifier(self.incarnation)
        if (type(self.token) is not int or not 1<=self.token<=COUNTER_MAX
                or type(self.attempt) is not int or not 1<=self.attempt<=3
                or type(self.epoch) is not int or not 0<=self.epoch<=COUNTER_MAX
                or type(self.expected_generation) is not int or not 0<=self.expected_generation<=COUNTER_MAX
                or type(self.lease_seconds) is not int or not 15<=self.lease_seconds<=3600
                or type(self.request_digest) is not str or not re.fullmatch(r'[0-9a-f]{64}',self.request_digest)):
            raise PersistenceError('lease_lost')
        if self.connection_id is None:
            if self.connection_version is not None or self.connection_generation is not None:
                raise PersistenceError('lease_lost')
        else:
            identifier(self.connection_id)
            if (type(self.connection_version) is not str or not re.fullmatch(r'[0-9a-f]{64}',self.connection_version)
                    or type(self.connection_generation) is not int or not 0<=self.connection_generation<=COUNTER_MAX):
                raise PersistenceError('lease_lost')


def _request(value):
    if type(value) is not dict or set(value)!={'resource_id','version'} or value['version']!='1':
        raise PersistenceError('invalid_candidate')
    identifier(value['resource_id'])
    return value


def enqueue_in_transaction(uow,key,request,expected_generation,*,connection=None,max_attempts=3):
    validate_key(key);request=dict(_request(request))
    if type(max_attempts) is not int or not 1<=max_attempts<=3 or type(expected_generation) is not int or not 0<=expected_generation<=COUNTER_MAX:
        raise PersistenceError('invalid_candidate')
    if connection is not None:
        if type(connection) is not tuple or len(connection)!=3:
            raise PersistenceError('invalid_candidate')
        identifier(connection[0])
        if type(connection[1]) is not str or len(connection[1])!=64 or type(connection[2]) is not int or not 0<=connection[2]<=COUNTER_MAX:
            raise PersistenceError('invalid_candidate')
    fingerprint=digest({'request':request,'generation':str(expected_generation),'connection':connection,'max_attempts':max_attempts})
    row=execute(uow.connection,"SELECT id,request_digest FROM wl_pg.jobs WHERE tenant_id=:t AND portfolio_id=:p AND kind='foundation' AND idempotency_key=:key",**parameters(uow),key=key).mappings().one_or_none()
    if row:
        if row['request_digest']!=fingerprint:raise PersistenceError('request_conflict')
        return str(row['id'])
    job_id=str(uuid.uuid4())
    insert(uow,'jobs',{'id':job_id,'kind':'foundation','request':request,'request_digest':fingerprint,'idempotency_key':key,'status':'queued','max_attempts':max_attempts,'expected_generation':expected_generation,
        'connection_id':connection[0] if connection else None,'connection_version':connection[1] if connection else None,'connection_generation':connection[2] if connection else None})
    return job_id


class Jobs:
    def __init__(self,database):self.database=database

    def enqueue(self,context,key,request,*,expected_generation,connection=None,max_attempts=3):
        with self.database.transaction(context) as uow:
            lock_root(uow)
            return enqueue_in_transaction(uow,key,request,expected_generation,connection=connection,max_attempts=max_attempts)

    def claim(self,context,worker_id,*,lease_seconds=60):
        identifier(worker_id)
        if type(lease_seconds) is not int or not 15<=lease_seconds<=3600:raise PersistenceError('invalid_config')
        result=None
        with self.database.transaction(context) as uow:
            for _ in range(20):
                row=execute(uow.connection,"""SELECT * FROM wl_pg.jobs WHERE tenant_id=:t AND portfolio_id=:p AND
                    ((status IN ('queued','retryable_error') AND available_at<=clock_timestamp()) OR
                     (status='running' AND lease_expires_at<=clock_timestamp()))
                    ORDER BY available_at,created_at,id FOR UPDATE SKIP LOCKED LIMIT 1""",**parameters(uow)).mappings().one_or_none()
                if row is None:break
                if row['attempt']>=row['max_attempts']:
                    execute(uow.connection,"UPDATE wl_pg.jobs SET status='failed',error_code='attempts_exhausted',worker_id=NULL,lease_expires_at=NULL WHERE tenant_id=:t AND portfolio_id=:p AND id=:id",**parameters(uow),id=row['id'])
                    continue
                if row['fencing_token']>=COUNTER_MAX:raise PersistenceError('counter_exhausted')
                execute(uow.connection,"""UPDATE wl_pg.jobs SET status='running',attempt=attempt+1,fencing_token=fencing_token+1,
                    worker_id=:worker,lease_seconds=:seconds,lease_expires_at=clock_timestamp()+make_interval(secs=>:seconds),error_code=NULL
                    WHERE tenant_id=:t AND portfolio_id=:p AND id=:id""",**parameters(uow),id=row['id'],worker=worker_id,seconds=lease_seconds)
                result=Lease(context,str(row['id']),worker_id,row['fencing_token']+1,row['attempt']+1,
                    uow.incarnation,uow.epoch,lease_seconds,row['request_digest'],row['expected_generation'],
                    str(row['connection_id']) if row['connection_id'] else None,row['connection_version'],row['connection_generation'])
                break
        return result

    def _leased(self,uow,lease,*,terminal=False,connection_lock=False):
        if type(lease) is not Lease or lease.context!=uow.context:
            raise PersistenceError('lease_lost')
        connection_generation=None
        if connection_lock:
            # The root lock is already held. Request fields are immutable: read them
            # without a job lock so the order stays root -> actual source -> job.
            intent=execute(uow.connection,'SELECT connection_id,connection_version FROM wl_pg.jobs WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',**parameters(uow),id=lease.job_id).mappings().one_or_none()
            if intent is None:
                raise PersistenceError('lease_lost')
            if intent['connection_id'] is not None:
                connection_generation=execute(uow.connection,'SELECT generation FROM wl_pg.connections WHERE tenant_id=:t AND portfolio_id=:p AND id=:id AND version=:version FOR UPDATE',**parameters(uow),id=intent['connection_id'],version=intent['connection_version']).scalar_one_or_none()
        row=execute(uow.connection,'SELECT * FROM wl_pg.jobs WHERE tenant_id=:t AND portfolio_id=:p AND id=:id FOR UPDATE',**parameters(uow),id=lease.job_id).mappings().one_or_none()
        state=execute(uow.connection,'SELECT incarnation,restore_epoch,ready FROM wl_pg.instance_state WHERE id=1').mappings().one()
        if (row is None or str(state['incarnation'])!=lease.incarnation or state['restore_epoch']!=lease.epoch or not state['ready']
                or str(row['worker_id'])!=lease.worker_id or row['fencing_token']!=lease.token or row['request_digest']!=lease.request_digest
                or row['expected_generation']!=lease.expected_generation or row['attempt']!=lease.attempt
                or row['lease_seconds']!=lease.lease_seconds
                or (str(row['connection_id']) if row['connection_id'] is not None else None)!=lease.connection_id
                or row['connection_version']!=lease.connection_version or row['connection_generation']!=lease.connection_generation):
            raise PersistenceError('lease_lost')
        if terminal and row['status']=='succeeded' and execute(uow.connection,'SELECT 1 FROM wl_pg.job_effect_receipts WHERE tenant_id=:t AND portfolio_id=:p AND job_id=:id',**parameters(uow),id=lease.job_id).scalar():
            return row
        if connection_lock and row['connection_id'] is not None and connection_generation!=row['connection_generation']:
            raise PersistenceError('lease_lost')
        # clock_timestamp is sampled AFTER the locking SELECT, never transaction-start now().
        now=execute(uow.connection,'SELECT clock_timestamp()').scalar_one()
        if row['status']!='running' or row['lease_expires_at'] is None or row['lease_expires_at']<=now:
            raise PersistenceError('lease_lost')
        return row

    def heartbeat(self,lease):
        if type(lease) is not Lease:raise PersistenceError('lease_lost')
        with self.database.transaction(lease.context) as uow:
            self._leased(uow,lease)
            execute(uow.connection,'UPDATE wl_pg.jobs SET lease_expires_at=clock_timestamp()+make_interval(secs=>:seconds) WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',**parameters(uow),id=lease.job_id,seconds=lease.lease_seconds)

    def complete(self,lease,*,fault=None):
        """Commit the foundation's internal DB-only effect; no dynamic handler loading."""
        if type(lease) is not Lease:raise PersistenceError('lease_lost')
        request={'job_id':lease.job_id,'request_digest':lease.request_digest,'expected_generation':str(lease.expected_generation)}
        def preflight(uow):self._leased(uow,lease,terminal=True,connection_lock=True)
        def effect(uow,operation_id):
            result={'job_id':lease.job_id,'result':'foundation_complete'}
            insert(uow,'job_effect_receipts',{'job_id':lease.job_id,'operation_id':operation_id,'result':result})
            execute(uow.connection,"UPDATE wl_pg.jobs SET status='succeeded',lease_expires_at=NULL WHERE tenant_id=:t AND portfolio_id=:p AND id=:id",**parameters(uow),id=lease.job_id)
            return result,'effect_committed',lease.job_id
        return atomic(self.database,lease.context,'job_effect',lease.job_id,request,lease.expected_generation,effect,preflight=preflight,fault=fault)

    def fail(self,lease,*,retryable=False,code='invalid_candidate'):
        if type(lease) is not Lease:raise PersistenceError('lease_lost')
        if type(retryable) is not bool or code not in CODES:raise PersistenceError('invalid_candidate')
        with self.database.transaction(lease.context) as uow:
            row=self._leased(uow,lease)
            status='retryable_error' if retryable and row['attempt']<row['max_attempts'] else 'failed'
            execute(uow.connection,'UPDATE wl_pg.jobs SET status=:status,error_code=:code,lease_expires_at=NULL,worker_id=NULL,available_at=clock_timestamp() WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',**parameters(uow),id=lease.job_id,status=status,code=code)

    def cancel(self,context,job_id):
        identifier(job_id)
        with self.database.transaction(context) as uow:
            lock_root(uow)
            row=execute(uow.connection,'SELECT status,fencing_token FROM wl_pg.jobs WHERE tenant_id=:t AND portfolio_id=:p AND id=:id FOR UPDATE',**parameters(uow),id=job_id).mappings().one_or_none()
            if row is None or row['status'] in {'succeeded','failed'}:raise PersistenceError('job_state')
            if row['status']=='cancelled':return
            if row['fencing_token']>=COUNTER_MAX:raise PersistenceError('counter_exhausted')
            execute(uow.connection,"UPDATE wl_pg.jobs SET status='cancelled',cancel_requested=true,fencing_token=fencing_token+1,worker_id=NULL,lease_expires_at=NULL WHERE tenant_id=:t AND portfolio_id=:p AND id=:id",**parameters(uow),id=job_id)
