"""Lossless, scoped domain-v1 CANDIDATE repositories; never financial booking."""
from dataclasses import asdict
import hashlib
import json
import re
from wealth_ledger.domain import canonical_v1 as c
from wealth_ledger.domain.validation_v1 import encode_domain_v1, decode_domain_v1, DomainValidationError
from .context import execute, identifier
from .errors import PersistenceError
from .operations import atomic, canonical, digest, insert, parameters
from .precision import decimal_value, source_time


def selector_identity(selector):
    fields=[selector.connection.value,selector.provider,selector.source_account_key,
            selector.kind,selector.source_id,selector.observation_id,selector.record_kind]
    logical=canonical(fields);full=canonical(fields+[selector.revision])
    return hashlib.sha256(full.encode()).hexdigest(),hashlib.sha256(logical.encode()).hexdigest(),full,logical


def _money(name,value):
    token,amount=decimal_value(value.amount if value else None)
    return {name+'_token':token,name+'_value':amount,name+'_currency':value.currency if value else None}


class Candidates:
    def __init__(self,database):
        self.database=database

    def read(self,context,batch_id):
        identifier(batch_id)
        with self.database.transaction(context,readonly=True) as uow:
            row=execute(uow.connection,"SELECT canonical_bytes,digest FROM wl_pg.candidate_batches WHERE tenant_id=:t AND portfolio_id=:p AND id=:id",**parameters(uow),id=batch_id).mappings().one_or_none()
            if row is None:
                return None
            raw=bytes(row['canonical_bytes'])
            if hashlib.sha256(raw).hexdigest()!=row['digest']:
                raise PersistenceError('revision_conflict')
            try:
                value=decode_domain_v1(raw)
            except DomainValidationError:
                raise PersistenceError('invalid_candidate') from None
            if (value.tenant_id,value.portfolio_id)!=(context.tenant_id,context.portfolio_id):
                raise PersistenceError('reference_conflict')
            return value

    def put(self,context,batch_id,batch,*,expected_generation,idempotency_key,head_updates=(),fault=None):
        identifier(batch_id)
        try:
            raw=encode_domain_v1(batch)
        except (DomainValidationError,TypeError,AttributeError,UnicodeError):
            raise PersistenceError('invalid_candidate') from None
        # PostgreSQL text/JSONB cannot represent U+0000. Reject that shape before
        # any SQL rather than misreporting a database outage or altering evidence.
        pending=[json.loads(raw)]
        while pending:
            value=pending.pop()
            if isinstance(value,str) and '\x00' in value:
                raise PersistenceError('invalid_candidate')
            if isinstance(value,dict):
                pending.extend(value.keys());pending.extend(value.values())
            elif isinstance(value,list):
                pending.extend(value)
        if (batch.tenant_id,batch.portfolio_id)!=(context.tenant_id,context.portfolio_id):
            raise PersistenceError('invalid_context')
        if type(head_updates) is not tuple or len(head_updates)>c.MAX_COLLECTION:
            raise PersistenceError('invalid_candidate')
        for row in head_updates:
            if (type(row) is not tuple or len(row)!=3 or any(type(x) is not str or not re.fullmatch(r'[0-9a-f]{64}',x) for x in (row[0],row[2]))
                    or row[1] is not None and (type(row[1]) is not str or not re.fullmatch(r'[0-9a-f]{64}',row[1]))):
                raise PersistenceError('invalid_candidate')
        if len(canonical(head_updates).encode())>c.MAX_CANONICAL_BYTES:
            raise PersistenceError('resource_limit')
        if len({row[0] for row in head_updates})!=len(head_updates):
            raise PersistenceError('invalid_candidate')
        request={'batch_id':batch_id,'digest':hashlib.sha256(raw).hexdigest(),
                 'expected_generation':str(expected_generation),'head_updates':head_updates}
        def replay(uow):
            if head_updates:
                return None
            existing=execute(uow.connection,'SELECT canonical_bytes FROM wl_pg.candidate_batches WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',**parameters(uow),id=batch_id).scalar_one_or_none()
            if existing is None:
                return None
            if bytes(existing)!=raw:
                raise PersistenceError('revision_conflict')
            saved=execute(uow.connection,"SELECT result FROM wl_pg.operation_receipts WHERE tenant_id=:t AND portfolio_id=:p AND operation_kind='store_candidate' AND result->>'batch_id'=:id ORDER BY generation,id LIMIT 1",**parameters(uow),id=batch_id).scalar_one_or_none()
            if saved is None:
                raise PersistenceError('reference_conflict')
            return saved
        def apply(uow,operation_id):
            self._store(uow,batch_id,batch,raw,head_updates,fault)
            return {'batch_id':batch_id,'digest':request['digest'],'ingestible':False},'candidate_stored',batch_id
        return atomic(self.database,context,'store_candidate',idempotency_key,request,
                      expected_generation,apply,replay=replay,fault=fault)

    def _store(self,uow,batch_id,batch,raw,head_updates,fault):
        existing=execute(uow.connection,'SELECT canonical_bytes FROM wl_pg.candidate_batches WHERE tenant_id=:t AND portfolio_id=:p AND id=:id',**parameters(uow),id=batch_id).scalar_one_or_none()
        if existing is not None:
            if bytes(existing)!=raw:
                raise PersistenceError('revision_conflict')
            if head_updates:
                self._heads(uow,batch_id,head_updates)
            return
        versions={}
        def declaration(table,value,fields):
            version=digest(value);versions[(value.id.kind,value.id.value)]=version
            row=execute(uow.connection,f'SELECT body FROM wl_pg.{table} WHERE tenant_id=:t AND portfolio_id=:p AND id=:id AND version=:version',**parameters(uow),id=value.id.value,version=version).scalar_one_or_none()
            if row is not None:
                if canonical(row)!=canonical(value):raise PersistenceError('revision_conflict')
                return
            insert(uow,table,{'id':value.id.value,'version':version,'body':asdict(value),**fields})
        for value in batch.issuers:declaration('issuers',value,{'label':value.label})
        for value in sorted(batch.accounts,key=lambda v:v.id.value):declaration('accounts',value,{'category':value.category,'role':value.role,'label':value.label})
        for value in sorted(batch.connections,key=lambda v:v.id.value):declaration('connections',value,{'provider':value.provider,'provider_digest':hashlib.sha256(value.provider.encode()).hexdigest(),'kind':value.kind})
        for value in batch.instruments:
            declaration('instruments',value,{**{key:getattr(value,key) for key in ['kind','currency','ticker','mic','symbol','network','settlement_identity']},'identifiers':[asdict(x) for x in value.identifiers],
                'issuer_id':value.issuer.value if value.issuer else None,'issuer_version':versions[('issuer',value.issuer.value)] if value.issuer else None})
        if fault:fault('after_declarations')
        insert(uow,'candidate_batches',{'id':batch_id,'digest':hashlib.sha256(raw).hexdigest(),'canonical_bytes':raw,'contract_version':batch.contract_version,'profile':batch.profile,'mapping_revision':batch.mapping_revision})
        for ordinal,value in enumerate(batch.aliases):
            insert(uow,'account_aliases',{'batch_id':batch_id,'ordinal':ordinal,'connection_id':value.connection.value,'connection_version':versions[('connection',value.connection.value)],'account_id':value.account.value,'account_version':versions[('account',value.account.value)],'source_account_key':value.source_account_key,'mapping_revision':value.mapping_revision,'body':asdict(value)})
        connections={value.id.value:value for value in batch.connections}
        records=[]
        for value in batch.coverage:
            selector=c.SourceSelectorV1(value.connection,connections[value.connection.value].provider,value.source_account_key,'coverage',value.scope_id,value.observation_id,value.revision,value.kind)
            records.append((selector,'coverage',None,value.parent,value))
        for value in batch.snapshots:
            selector=c.SourceSelectorV1(value.connection,connections[value.connection.value].provider,None,'snapshot',value.source_id,'',value.revision)
            records.append((selector,'snapshot',value.id.value,value.parent,value))
            for item in value.items:records.append((item.identity.source,'item',item.identity.id.value,item.identity.parent,item))
        for value in batch.activities:records.append((value.identity.source,'activity',value.identity.id.value,value.identity.parent,value))
        keys={selector_identity(item[0])[0] for item in records}
        for selector,kind,fact_id,parent,value in records:
            key,logical_key,full,logical=selector_identity(selector)
            parent_key=selector_identity(parent.selector)[0] if parent else None
            if parent_key and parent_key not in keys:
                row=execute(uow.connection,'SELECT selector_text FROM wl_pg.candidate_revisions WHERE tenant_id=:t AND portfolio_id=:p AND key=:key',**parameters(uow),key=parent_key).scalar_one_or_none()
                if row is None:raise PersistenceError('parent_missing')
                if row!=selector_identity(parent.selector)[2]:raise PersistenceError('revision_conflict')
            row=execute(uow.connection,'SELECT selector_text,body_digest,body FROM wl_pg.candidate_revisions WHERE tenant_id=:t AND portfolio_id=:p AND key=:key',**parameters(uow),key=key).mappings().one_or_none()
            if row:
                if row['selector_text']!=full or row['body_digest']!=digest(value) or canonical(row['body'])!=canonical(value):
                    raise PersistenceError('revision_conflict')
            else:
                insert(uow,'candidate_revisions',{'key':key,'logical_key':logical_key,'selector_text':full,'logical_selector_text':logical,'connection_id':selector.connection.value,'connection_version':versions[('connection',selector.connection.value)],'provider_digest':hashlib.sha256(selector.provider.encode()).hexdigest(),'source_revision':selector.revision,'fact_id':fact_id,'kind':kind,'body':asdict(value),'body_digest':digest(value),'parent_key':parent_key})
        if fault:fault('after_revisions')
        evidence=[]
        for selector,kind,fact_id,parent,value in records:
            evidence.append({'revision_key':selector_identity(selector)[0],'evidence_kind':kind,'body':{'source':asdict(selector)},**source_time(None)})
        evidence.append({'revision_key':None,'evidence_kind':'provenance','body':asdict(batch.provenance),**source_time(None)})
        for field in ['source_effective_at','evidence_at','imported_at','accepted_at']:
            evidence.append({'revision_key':None,'evidence_kind':field,'body':{},**source_time(getattr(batch.provenance,field))})
        for ordinal,value in enumerate(evidence):insert(uow,'candidate_evidence',{'batch_id':batch_id,'ordinal':ordinal,**value})
        instrument_map={value.id.value:value for value in batch.instruments}
        def qty(value):
            token,number=decimal_value(value.quantity)
            instrument=instrument_map[value.instrument.value]
            return {'account_id':value.account.value,'account_version':versions[('account',value.account.value)],'instrument_id':value.instrument.value,'instrument_version':versions[('instrument',value.instrument.value)],
                'requires_satoshi':instrument.kind in {'CRYPTO','UNSUPPORTED'} and instrument.symbol is not None and instrument.symbol.upper() in {'BTC','LBTC'},'quantity_token':token,'quantity_value':number}
        for value in batch.coverage:
            selector=c.SourceSelectorV1(value.connection,connections[value.connection.value].provider,value.source_account_key,'coverage',value.scope_id,value.observation_id,value.revision,value.kind)
            start=value.time.at if isinstance(value.time,c.PointV1) else value.time.start
            end=None if isinstance(value.time,c.PointV1) else value.time.end
            insert(uow,'candidate_coverage',{'batch_id':batch_id,'key':selector_identity(selector)[0],'account_id':value.account.value,'account_version':versions[('account',value.account.value)],'status':value.status,'body':asdict(value),
                **{'start_'+k:v for k,v in source_time(start).items()},**{'end_'+k:v for k,v in source_time(end).items()}})
        for value in batch.snapshots:
            selector=c.SourceSelectorV1(value.connection,connections[value.connection.value].provider,None,'snapshot',value.source_id,'',value.revision)
            key=selector_identity(selector)[0]
            insert(uow,'candidate_snapshots',{'batch_id':batch_id,'key':key,'snapshot_id':value.id.value,'body':asdict(value),**source_time(value.as_of)})
            for ordinal,item in enumerate(value.items):
                fields={'batch_id':batch_id,'snapshot_key':key,'ordinal':ordinal,'key':selector_identity(item.identity.source)[0],**qty(item),**source_time(item.as_of),'support':asdict(item.support)}
                for name in ['market_value','unit_price','cost_native','cost_cad','unrealized']:fields.update(_money(name,getattr(item,name)))
                insert(uow,'candidate_items',fields)
        for value in batch.activities:
            key=selector_identity(value.identity.source)[0]
            fields={'batch_id':batch_id,'key':key,'kind':value.kind,'status':value.status,'fees_known':value.fees is not None,'source_kind':value.source_kind,'source_status':value.source_status,'body':asdict(value),**source_time(value.event_time)}
            for name in ['acquisition_cost','acquisition_cost_cad']:fields.update(_money(name,getattr(value,name)))
            fields.update(_money('cash_flow',value.cash_flow.cash_amount if value.cash_flow else None))
            insert(uow,'candidate_activities',fields)
            for ordinal,leg in enumerate(value.legs):insert(uow,'candidate_legs',{'batch_id':batch_id,'event_key':key,'ordinal':ordinal,**qty(leg),'role':leg.role})
            for ordinal,fee in enumerate(value.fees or ()):
                insert(uow,'candidate_fees',{'batch_id':batch_id,'event_key':key,'ordinal':ordinal,**qty(fee),'included_in_leg':fee.included_in_leg,'included_in_cost':fee.included_in_cost})
        if fault:fault('after_typed_rows')
        self._heads(uow,batch_id,head_updates)
        if fault:fault('after_heads')

    def _heads(self,uow,batch_id,updates):
        for logical,expected,new in sorted(updates):
            current=execute(uow.connection,'SELECT revision_key FROM wl_pg.repository_heads WHERE tenant_id=:t AND portfolio_id=:p AND logical_key=:logical FOR UPDATE',**parameters(uow),logical=logical).scalar_one_or_none()
            if current!=expected:raise PersistenceError('stale_generation')
            member=execute(uow.connection,'SELECT 1 FROM wl_pg.candidate_evidence e JOIN wl_pg.candidate_revisions r ON (r.tenant_id,r.portfolio_id,r.key)=(e.tenant_id,e.portfolio_id,e.revision_key) WHERE e.tenant_id=:t AND e.portfolio_id=:p AND e.batch_id=:batch AND r.key=:key AND r.logical_key=:logical',**parameters(uow),batch=batch_id,key=new,logical=logical).scalar_one_or_none()
            if not member:raise PersistenceError('reference_conflict')
            execute(uow.connection,'INSERT INTO wl_pg.repository_heads(tenant_id,portfolio_id,batch_id,logical_key,revision_key) VALUES(:t,:p,:batch,:logical,:key) ON CONFLICT(tenant_id,portfolio_id,logical_key) DO UPDATE SET batch_id=EXCLUDED.batch_id,revision_key=EXCLUDED.revision_key',**parameters(uow),batch=batch_id,logical=logical,key=new)
