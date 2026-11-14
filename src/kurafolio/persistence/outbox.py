"""At-least-once polling with transactional follow-up-job linkage."""
from .context import execute
from .errors import PersistenceError
from .jobs import enqueue_in_transaction
from .operations import lock_root, parameters


def relay(database,context,*,limit=20,fault=None):
    if type(limit) is not int or not 1<=limit<=100:raise PersistenceError('invalid_config')
    jobs=[]
    with database.transaction(context) as uow:
        lock_root(uow)
        rows=execute(uow.connection,"SELECT id,resource_id,generation FROM wl_pg.outbox WHERE tenant_id=:t AND portfolio_id=:p AND dispatched_at IS NULL ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT :limit",**parameters(uow),limit=limit).mappings().all()
        for row in rows:
            job=enqueue_in_transaction(uow,str(row['id']),{'resource_id':str(row['resource_id']),'version':'1'},row['generation'])
            if fault:fault('after_job')
            execute(uow.connection,'UPDATE wl_pg.outbox SET dispatched_at=clock_timestamp() WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',**parameters(uow),id=row['id'])
            jobs.append(job)
    return jobs
