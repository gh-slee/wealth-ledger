"""One scoped transaction for candidate effects, receipts, generation and outbox."""
from dataclasses import asdict, is_dataclass
import hashlib
import json
import re
import time
import uuid
from .context import COUNTER_MAX, execute
from .errors import PersistenceError


def canonical(value):
    return json.dumps(asdict(value) if is_dataclass(value) else value,
                      ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def parameters(uow):
    return {"t":uow.context.tenant_id,"p":uow.context.portfolio_id}


def insert(uow, table, values, *, conflict=False):
    # Names are internal schema constants, never caller-controlled SQL fragments.
    if not re.fullmatch(r"[a-z_]+",table) or any(not re.fullmatch(r"[a-z_]+",n) for n in values):
        raise PersistenceError("invalid_candidate")
    scoped={"tenant_id":uow.context.tenant_id,"portfolio_id":uow.context.portfolio_id,**values}
    names=list(scoped);bindings=[]
    for name in names:
        if isinstance(scoped[name],(dict,list)):
            scoped[name]=canonical(scoped[name]);bindings.append(f"CAST(:{name} AS jsonb)")
        else:
            bindings.append(':'+name)
    return execute(uow.connection,f"INSERT INTO wl_pg.{table}({','.join(names)}) VALUES({','.join(bindings)})"+
                   (" ON CONFLICT DO NOTHING" if conflict else ""),**scoped)


def lock_root(uow):
    row=execute(uow.connection,"SELECT fact_generation FROM wl_pg.portfolios WHERE tenant_id=:t AND portfolio_id=:p FOR UPDATE",**parameters(uow)).mappings().one_or_none()
    if row is None:
        raise PersistenceError("invalid_context")
    return row['fact_generation']


def validate_key(key):
    if type(key) is not str or not re.fullmatch(r"[ -~]{8,128}",key):
        raise PersistenceError("invalid_candidate")


def atomic(database,context,kind,key,request,expected_generation,apply,*,preflight=None,replay=None,fault=None):
    """Trusted service primitive; callbacks are application code, never plugin paths."""
    validate_key(key)
    if kind not in {'store_candidate','job_effect'} or type(expected_generation) is not int or not 0<=expected_generation<=COUNTER_MAX:
        raise PersistenceError("invalid_candidate")
    request_digest=digest(request)
    for attempt in range(3):
        try:
            with database.transaction(context) as uow:
                generation=lock_root(uow)
                if preflight:
                    preflight(uow)
                row=execute(uow.connection,"""SELECT request_digest,result FROM wl_pg.operation_receipts
                    WHERE tenant_id=:t AND portfolio_id=:p AND operation_kind=:kind AND idempotency_key=:key""",
                    **parameters(uow),kind=kind,key=key).mappings().one_or_none()
                if row:
                    if row['request_digest']!=request_digest:
                        raise PersistenceError("request_conflict")
                    return row['result']
                if generation!=expected_generation:
                    raise PersistenceError("stale_generation")
                if replay:
                    saved=replay(uow)
                    if saved is not None:
                        # Bind a new key without inventing a candidate mutation.
                        # Result identity/generation still refer to the original effect.
                        insert(uow,'operation_receipts',{'id':str(uuid.uuid4()),'operation_kind':kind,'idempotency_key':key,
                            'request_digest':request_digest,'generation':generation,'result':saved})
                        if fault: fault('after_receipt')
                        if fault: fault('before_commit')
                        return saved
                if generation>=COUNTER_MAX:
                    raise PersistenceError("counter_exhausted")
                operation_id=str(uuid.uuid4())
                result,event_kind,resource_id=apply(uow,operation_id)
                result={**result,"operation_id":operation_id,"generation":str(generation+1)}
                if fault: fault('after_effect')
                insert(uow,'operation_receipts',{'id':operation_id,'operation_kind':kind,'idempotency_key':key,
                    'request_digest':request_digest,'generation':generation+1,'result':result})
                if fault: fault('after_receipt')
                insert(uow,'audit_actions',{'id':str(uuid.uuid4()),'operation_id':operation_id,'action':kind})
                execute(uow.connection,"UPDATE wl_pg.portfolios SET fact_generation=fact_generation+1 WHERE tenant_id=:t AND portfolio_id=:p",**parameters(uow))
                if fault: fault('after_generation')
                insert(uow,'outbox',{'id':str(uuid.uuid4()),'operation_id':operation_id,'generation':generation+1,
                    'event_kind':event_kind,'resource_id':resource_id})
                if fault: fault('before_commit')
            return result
        except PersistenceError as error:
            if getattr(error,'sqlstate',None) not in {'40001','40P01'}:
                raise
            if attempt==2:
                raise PersistenceError('retry_exhausted') from None
            time.sleep(.01*(attempt+1))
    raise PersistenceError('retry_exhausted')
