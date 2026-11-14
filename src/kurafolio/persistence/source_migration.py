"""Explicit operator migration/catalog/restore; no startup migration or live import."""
from pathlib import Path
import hashlib
import json
import re
import uuid

from .context import COUNTER_MAX, execute
from .errors import PersistenceError
from . import source_schema as source
from . import identity_schema
from .schema import HELPERS
from .migration import _operator, _role, _identity_grants, _identity_target_inventory
from ..data_sources.contract_v1 import canonical, primitive, installation_id, counter
from ..data_sources.catalog_v1 import (validate_catalog,validate_transition,catalog_digest,decode_catalog)

# Developer freeze from the synthetic definition probe; independent inspection
# is required before acceptance. Never regenerate expected values at startup.
# An unfrozen provider fails closed instead of accepting live output.
EXPECTED_STRUCTURE_SHA256 = "3c6e0ef232013edd8480a1c481c5126b386674353d3dd08ad771ed1cb2ae65ac"


def source_grants(conn, runtime_role, gateway_role):
    _identity_grants(conn,runtime_role,gateway_role)
    owner=_operator(conn)
    for role in (runtime_role,gateway_role):
        quoted=_role(role)
        execute(conn,f"REVOKE ALL ON SCHEMA wl_sources FROM {quoted}")
        execute(conn,f"REVOKE ALL ON ALL TABLES IN SCHEMA wl_sources FROM {quoted}")
        execute(conn,f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA wl_sources FROM {quoted}")
        for table in source.TABLES:
            execute(conn,f"REVOKE ALL({','.join(row[0] for row in execute(conn, 'SELECT attname FROM pg_catalog.pg_attribute WHERE attrelid=CAST(:table AS regclass) AND attnum>0 AND NOT attisdropped',table='wl_sources.'+table).all())}) ON wl_sources.{table} FROM {quoted}")
    execute(conn,"REVOKE ALL ON SCHEMA wl_sources FROM PUBLIC")
    execute(conn,"REVOKE ALL ON ALL TABLES IN SCHEMA wl_sources FROM PUBLIC")
    execute(conn,"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA wl_sources FROM PUBLIC")
    for name in source.TENANT_TABLES:
        execute(conn,f"DROP POLICY IF EXISTS operator_scope ON wl_sources.{name}")
        execute(conn,f"CREATE POLICY operator_scope ON wl_sources.{name} TO {_role(owner)} USING(true) WITH CHECK(true)")
    for role in (runtime_role,gateway_role):
        execute(conn,f"GRANT USAGE ON SCHEMA wl_sources TO {_role(role)}")
    execute(conn,f"GRANT SELECT ON ALL TABLES IN SCHEMA wl_sources TO {_role(runtime_role)}")
    for name in source.GATEWAY:
        execute(conn,f"GRANT EXECUTE ON FUNCTION {source.signature(name)} TO {_role(gateway_role)}")


def structure_snapshot(conn):
    """Read definitions only; never use financial/source rows as a schema oracle."""
    queries={
      'relations':"""SELECT c.relname,c.relkind,c.relpersistence,c.relispartition,c.relrowsecurity,c.relforcerowsecurity,c.relowner=n.nspowner FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wl_sources' ORDER BY c.relname""",
      'columns':"""SELECT c.relname,a.attnum,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attgenerated,a.attidentity,cn.nspname,co.collname,pg_catalog.pg_get_expr(d.adbin,d.adrelid) FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum LEFT JOIN pg_catalog.pg_collation co ON co.oid=a.attcollation LEFT JOIN pg_catalog.pg_namespace cn ON cn.oid=co.collnamespace WHERE n.nspname='wl_sources' AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum""",
      'constraints':"""SELECT c.relname,k.conname,k.contype,k.condeferrable,k.condeferred,pg_catalog.pg_get_constraintdef(k.oid) FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wl_sources' ORDER BY c.relname,k.conname""",
      'indexes':"""SELECT c.relname,i.indisvalid,i.indisready,i.indislive,pg_catalog.pg_get_indexdef(c.oid) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace JOIN pg_catalog.pg_index i ON i.indexrelid=c.oid WHERE n.nspname='wl_sources' AND c.relkind='i' ORDER BY c.relname""",
      'policies':"""SELECT c.relname,p.polname,p.polcmd,p.polpermissive,ARRAY(SELECT CASE WHEN r=0 THEN 'PUBLIC' WHEN r=n.nspowner THEN 'OWNER' ELSE 'UNKNOWN' END FROM unnest(p.polroles) r ORDER BY1),pg_catalog.pg_get_expr(p.polqual,p.polrelid),pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid) FROM pg_catalog.pg_policy p JOIN pg_catalog.pg_class c ON c.oid=p.polrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wl_sources' ORDER BY c.relname,p.polname""",
      'triggers':"""SELECT c.relname,t.tgname,t.tgenabled,pg_catalog.pg_get_triggerdef(t.oid) FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wl_sources' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname""",
    }
    return {key:[list(row) for row in execute(conn,sql.replace('ORDER BY1','ORDER BY 1')).all()] for key,sql in queries.items()}


def structure_digest(conn):
    return hashlib.sha256(canonical(structure_snapshot(conn))).hexdigest()


def _expected_functions(*, source_profile=True):
    # Read only code-owned immutable providers. There is no runtime type/function
    # name from an HTTP payload or arbitrary target database in this preimage.
    sql=HELPERS+(source.identity_replacements()+source.GUARD_DDL+source.gateway_ddl() if source_profile else identity_schema.ddl())
    pattern=r"CREATE(?: OR REPLACE)? FUNCTION (wl_pg|wl_identity|wl_sources)\.([a-z_0-9]+)\(([^;]*?)\) RETURNS ([^;]*?) AS (\$[a-z_]*\$)(.*?)\5"
    result={}
    for match in re.finditer(pattern,sql,re.S):
        namespace,name,parameters,header,tag,body=match.groups()
        result[(namespace,name)]={'body':body,'arguments':tuple(part.strip().split()[0] for part in parameters.split(',') if part.strip()),
            'definer':'SECURITY DEFINER' in header,'strict':'STRICT' in header, 'volatility':'i' if 'IMMUTABLE' in header else ('s' if 'STABLE' in header else 'v'), 'parallel':'s' if 'PARALLEL SAFE' in header else ('r' if 'PARALLEL RESTRICTED' in header else 'u'),'config':'search_path=pg_catalog,pg_temp' if namespace!='wl_pg' else 'search_path=pg_catalog'}
    result[('wl_identity','_clock_timestamp_v1')]={'body':'SELECT pg_catalog.clock_timestamp()','arguments':(), 'definer':True,'strict':False,'volatility':'v','parallel':'u','config':'search_path=pg_catalog,pg_temp'}
    if len(result)!=(36 if source_profile else 28):
        raise PersistenceError('migration_target_invalid')
    return result


def _verify_functions(conn,*,source_profile):
    expected=_expected_functions(source_profile=source_profile)
    rows=execute(conn,"""SELECT n.nspname,p.proname,pg_catalog.oidvectortypes(p.proargtypes),p.proargnames,
      p.prosrc,p.prosecdef,p.proconfig,p.proowner=n.nspowner,p.prokind,pg_catalog.format_type(p.prorettype,NULL),p.proisstrict,p.provolatile,p.proparallel,p.proleakproof,p.proargmodes,p.provariadic
      FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname IN ('wl_pg','wl_identity') OR (:sources AND n.nspname='wl_sources')""",sources=source_profile).all()
    if len(rows)!=len(expected):raise PersistenceError('migration_target_invalid')
    for namespace,name,arguments,names,body,definer,config,owned,kind,returns,strict,volatility,parallel,leakproof,argmodes,variadic in rows:
        item=expected.get((namespace,name))
        if item is None:raise PersistenceError('migration_target_invalid')
        signature=identity_schema.SIGNATURES[name] if namespace=='wl_identity' else (source.ARGUMENTS if namespace=='wl_sources' and name in source.GATEWAY else ())
        if namespace=='wl_pg':
            signature={'decimal_token_v1':('text',),'decimal_pair_v1':('text','numeric'),'quantity_pair_v1':('text','numeric','boolean'),'reject_mutation':(),'connection_generation_only':(),'job_request_immutable':()}[name]
        expected_return='jsonb' if namespace=='wl_identity' and name!='_clock_timestamp_v1' or namespace=='wl_sources' and name in source.GATEWAY else ('timestamp with time zone' if name=='_clock_timestamp_v1' else ('boolean' if name in {'decimal_token_v1','decimal_pair_v1','quantity_pair_v1'} else 'trigger'))
        if (arguments!=', '.join(signature) or tuple(names or ())!=item['arguments'] or body!=item['body'] or definer!=item['definer'] or not owned or kind!='f' or returns!=expected_return
                or strict!=item['strict'] or volatility!=item['volatility'] or parallel!=item['parallel'] or leakproof or argmodes is not None or variadic!=0
                or tuple(value.replace(' ','') for value in config or ())!=(item['config'],)):
            raise PersistenceError('migration_target_invalid')
    return rows


def _verify_roles(conn,runtime_role,gateway_role,*,source_profile):
    from .identity import role_inventory,IdentityError
    from types import SimpleNamespace
    profile=SimpleNamespace(schema_mode='sources' if source_profile else 'identity')
    try:
        role_inventory(profile,gateway=False,connection=conn,role=runtime_role)
        role_inventory(profile,gateway=True,connection=conn,role=gateway_role)
    except IdentityError:
        raise PersistenceError('migration_target_invalid') from None


def verify_inventory(conn, *, runtime_role, gateway_role, ungranted_restore=False):
    _role(runtime_role);_role(gateway_role)
    if execute(conn,'SELECT version_num FROM wl_pg.alembic_version').scalars().all()!=[source.REVISION]:
        raise PersistenceError('schema_unsupported')
    #0003 preserves these two schemas' declared object/column/constraint inventory.
    # This checks old definitions, not a fallback schema/head acceptance.
    _identity_target_inventory(conn,'0002_identity')
    if execute(conn,"SELECT1 FROM pg_catalog.pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname NOT IN ('information_schema','public','wl_pg','wl_identity','wl_sources') LIMIT1".replace('SELECT1','SELECT 1').replace('LIMIT1','LIMIT 1')).first():
        raise PersistenceError('migration_target_invalid')
    if (not re.fullmatch(r'[0-9a-f]{64}',EXPECTED_STRUCTURE_SHA256)
            or structure_digest(conn)!=EXPECTED_STRUCTURE_SHA256):
        raise PersistenceError('migration_target_invalid')
    relations=set(execute(conn,"SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wl_sources' AND c.relkind='r'").scalars())
    types=execute(conn,"SELECT t.oid,t.typrelid,t.typelem,t.typcategory FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='wl_sources'").all()
    allowed_types={oid for oid,relation,element,category in types if relation in relations}
    allowed_types.update(oid for oid,relation,element,category in types if element in allowed_types and category=='A')
    if len(relations)!=7 or any(oid not in allowed_types for oid,relation,element,category in types):
        raise PersistenceError('migration_target_invalid')
    for catalog,column in [('pg_operator','oprnamespace'),('pg_collation','collnamespace'),('pg_conversion','connamespace'),
                           ('pg_ts_config','cfgnamespace'),('pg_ts_dict','dictnamespace'),('pg_ts_parser','prsnamespace'),('pg_ts_template','tmplnamespace')]:
        if execute(conn,f"SELECT1 FROM pg_catalog.{catalog} o JOIN pg_catalog.pg_namespace n ON n.oid=o.{column} WHERE n.nspname='wl_sources' LIMIT1".replace('SELECT1','SELECT 1').replace('LIMIT1','LIMIT 1')).first():
            raise PersistenceError('migration_target_invalid')
    if execute(conn,"SELECT1 FROM pg_catalog.pg_rewrite r JOIN pg_catalog.pg_class c ON c.oid=r.ev_class JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wl_sources' LIMIT1".replace('SELECT1','SELECT 1').replace('LIMIT1','LIMIT 1')).first():
        raise PersistenceError('migration_target_invalid')
    if execute(conn,"SELECT1 FROM pg_catalog.pg_inherits i JOIN pg_catalog.pg_class c ON c.oid IN (i.inhrelid,i.inhparent) JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='wl_sources' LIMIT1".replace('SELECT1','SELECT 1').replace('LIMIT1','LIMIT 1')).first():
        raise PersistenceError('migration_target_invalid')
    rows=_verify_functions(conn,source_profile=True)
    # pg_restore --no-acl leaves every application-object ACL NULL. Accept that
    # exact offline restore shape only in the explicit finalizer; mixed/extra
    # grants never become a license to repair an unknown target. Normal startup,
    # migration and catalog writes still require exact positive runtime rights.
    acl_rows=execute(conn,"""SELECT nspacl IS NOT NULL FROM pg_catalog.pg_namespace WHERE nspname IN ('wl_pg','wl_identity','wl_sources')
      UNION ALL SELECT c.relacl IS NOT NULL FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources')
      UNION ALL SELECT a.attacl IS NOT NULL FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources')
      UNION ALL SELECT p.proacl IS NOT NULL FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources')""").scalars().all()
    no_acl_restore=ungranted_restore and not any(acl_rows)
    if not no_acl_restore:
        _verify_roles(conn,runtime_role,gateway_role,source_profile=True)
    owner=execute(conn,"SELECT pg_catalog.pg_get_userbyid(nspowner) FROM pg_catalog.pg_namespace WHERE nspname='wl_pg'").scalar_one()
    if execute(conn,"SELECT count(DISTINCT nspowner) FROM pg_catalog.pg_namespace WHERE nspname IN ('wl_pg','wl_identity','wl_sources')").scalar_one()!=1:
        raise PersistenceError('migration_target_invalid')
    # Reject additional effective explicit grants, including PUBLIC/column grants
    # to an undeclared role; per-role inventory checks the exact positive rights.
    grants=execute(conn,"""SELECT x.grantee,x.is_grantable FROM pg_catalog.pg_namespace n,LATERAL pg_catalog.aclexplode(n.nspacl) x WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources')
      UNION ALL SELECT x.grantee,x.is_grantable FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace,LATERAL pg_catalog.aclexplode(c.relacl) x WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources')
      UNION ALL SELECT x.grantee,x.is_grantable FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace,LATERAL pg_catalog.aclexplode(a.attacl) x WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources')
      UNION ALL SELECT x.grantee,x.is_grantable FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace,LATERAL pg_catalog.aclexplode(p.proacl) x WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources')""").all()
    allowed=set(execute(conn,'SELECT oid FROM pg_catalog.pg_roles WHERE rolname IN (:owner,:runtime,:gateway)',owner=owner,runtime=runtime_role,gateway=gateway_role).scalars())
    owner_oid=execute(conn,'SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:owner',owner=owner).scalar_one()
    if len(allowed)!=3 or any(grantee not in allowed or grantable and grantee!=owner_oid for grantee,grantable in grants):
        raise PersistenceError('migration_target_invalid')
    return {'schema_revision':source.REVISION,'structure_sha256':EXPECTED_STRUCTURE_SHA256,'functions':len(rows)}


def _catalog_apply(conn, catalog, proofs, *, expected_revision):
    from ..data_sources.catalog_v1 import proof_matches
    from ..data_sources.contract_v1 import CatalogSnapshot
    validate_catalog(catalog)
    counter(expected_revision)
    row=execute(conn,'SELECT * FROM wl_sources.catalog_state WHERE id=1 FOR UPDATE').mappings().one_or_none()
    previous=decode_catalog(bytes(row['bundle_bytes'])) if row else CatalogSnapshot(1,'0',(),(),())
    if int(expected_revision)!=int(previous.catalog_revision):
        raise PersistenceError('stale_generation')
    if row and catalog==previous:
        return False
    if catalog!=previous:
        validate_transition(previous,catalog)
    proof_map={proof.installation_id:proof for proof in proofs}
    if len(proof_map)!=len(proofs):raise PersistenceError('invalid_config')
    old={installation_id(value):value for value in previous.installations}
    prior_status={value.installation_id:value.status for value in previous.availability}
    proposed_status={value.installation_id:value.status for value in catalog.availability}
    known={installation_id(value):value for value in catalog.installations}
    if set(proof_map)-set(known):raise PersistenceError('invalid_config')
    for key,descriptor in known.items():
        required=key not in old or proposed_status[key]=='ACTIVE' and prior_status.get(key)!='ACTIVE'
        if required and not proof_matches(descriptor,proof_map.get(key)):
            raise PersistenceError('invalid_config')
    now=execute(conn,'SELECT wl_identity._clock_timestamp_v1()').scalar_one()
    if not execute(conn,"SELECT pg_catalog.isfinite(:n) AND :n>=last_observed_at FROM wl_identity.instance_auth_state WHERE id=1",n=now).scalar_one():
        raise PersistenceError('restore_required')
    for key,descriptor in known.items():
        if key not in old:
            execute(conn,"""INSERT INTO wl_sources.installations(id,plugin_id,provider_id,adapter_id,descriptor_bytes,created_at)
                VALUES(:id,:plugin,:provider,:adapter,:body,:n)""",id=key,plugin=descriptor.plugin_id,provider=descriptor.provider_id,
                adapter=descriptor.adapter_id,body=canonical(primitive(descriptor)),n=now)
    body=canonical(primitive(catalog));digest=catalog_digest(catalog)
    if row:
        execute(conn,'UPDATE wl_sources.catalog_state SET revision=:revision,digest=:digest,bundle_bytes=:body,updated_at=:n WHERE id=1',revision=int(catalog.catalog_revision),digest=digest,body=body,n=now)
    else:
        execute(conn,'INSERT INTO wl_sources.catalog_state VALUES(1,:revision,:digest,:body,:n)',revision=int(catalog.catalog_revision),digest=digest,body=body,n=now)
    execute(conn,'UPDATE wl_identity.instance_auth_state SET last_observed_at=:n WHERE id=1',n=now)
    return True


def _source_operator_lock(conn):
    _operator(conn)
    execute(conn,'SELECT pg_catalog.pg_advisory_xact_lock(1950174004)')
    execute(conn,'SELECT id FROM wl_pg.instance_state WHERE id=1 FOR UPDATE').one()
    execute(conn,'SELECT id FROM wl_identity.instance_auth_state WHERE id=1 FOR UPDATE').one()


def migrate_sources(database, runtime_role, gateway_role, key_digest, catalog, *, proofs=(), fault=None):
    """Only empty target, exact0002 or idempotent matching0003; one transaction."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import SQLAlchemyError
    if database.schema_mode!='sources' or type(key_digest) is not str or not re.fullmatch(r'[0-9a-f]{64}',key_digest):
        raise PersistenceError('invalid_config')
    validate_catalog(catalog)
    try:
        with database.engine.begin() as conn:
            _operator(conn);execute(conn,'SELECT pg_catalog.pg_advisory_xact_lock(1950174004)')
            schemas=set(execute(conn,"SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname<>'information_schema'").scalars())
            if schemas-{'public','wl_pg','wl_identity','wl_sources'}:raise PersistenceError('migration_target_invalid')
            tables=execute(conn,"SELECT schemaname,tablename FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')").all()
            version=None
            if tables:
                version=execute(conn,'SELECT version_num FROM wl_pg.alembic_version').scalar_one()
                if version not in {'0002_identity',source.REVISION}:raise PersistenceError('schema_unsupported')
                _source_operator_lock(conn)
                if version==source.REVISION:
                    verify_inventory(conn,runtime_role=runtime_role,gateway_role=gateway_role)
                    saved=execute(conn,'SELECT digest FROM wl_sources.catalog_state WHERE id=1').scalar_one()
                    if saved!=catalog_digest(catalog):raise PersistenceError('migration_target_invalid')
                else:
                    if 'wl_sources' in schemas:raise PersistenceError('migration_target_invalid')
                    _identity_target_inventory(conn,'0002_identity')
                    _verify_functions(conn,source_profile=False)
                    _verify_roles(conn,runtime_role,gateway_role,source_profile=False)
            else:
                _identity_target_inventory(conn,None)
                if schemas-{'public','wl_pg'}:raise PersistenceError('migration_target_invalid')
                execute(conn,'CREATE SCHEMA IF NOT EXISTS wl_pg')
            if version!=source.REVISION:
                config=Config();config.set_main_option('script_location',str(Path(__file__).parent/'migrations'))
                config.attributes.update(connection=conn,identity_key_digest=key_digest,source_fault=fault)
                command.upgrade(config,source.REVISION)
                if execute(conn,'SELECT key_digest FROM wl_identity.instance_auth_state WHERE id=1').scalar_one()!=key_digest:
                    raise PersistenceError('invalid_config')
                source_grants(conn,runtime_role,gateway_role)
                if fault:fault('after_grants')
                _catalog_apply(conn,catalog,proofs,expected_revision='0')
                if fault:fault('after_catalog')
                verify_inventory(conn,runtime_role=runtime_role,gateway_role=gateway_role)
                if fault:fault('after_inventory')
            elif execute(conn,'SELECT key_digest FROM wl_identity.instance_auth_state WHERE id=1').scalar_one()!=key_digest:
                raise PersistenceError('invalid_config')
            if fault:fault('before_commit')
        return database.status()
    except PersistenceError:
        raise
    except SQLAlchemyError:
        raise PersistenceError('migration_target_invalid') from None


def apply_catalog(database,runtime_role,gateway_role,catalog,*,expected_revision,proofs=()):
    if database.schema_mode!='sources':raise PersistenceError('invalid_config')
    with database.engine.begin() as conn:
        _source_operator_lock(conn)
        verify_inventory(conn,runtime_role=runtime_role,gateway_role=gateway_role)
        changed=_catalog_apply(conn,catalog,proofs,expected_revision=expected_revision)
    return {'changed':changed,'catalog_revision':catalog.catalog_revision,'catalog_digest':catalog_digest(catalog)}


def finalize_sources_restore(database,runtime_role,gateway_role,key_digest,catalog,*,proofs=(),replace_missing_key=False,fault=None):
    from ..data_sources.catalog_v1 import proof_matches
    if database.schema_mode!='sources' or type(replace_missing_key) is not bool or not re.fullmatch(r'[0-9a-f]{64}',key_digest or ''):
        raise PersistenceError('invalid_config')
    validate_catalog(catalog)
    by_id={proof.installation_id:proof for proof in proofs}
    for entry in catalog.availability:
        if entry.status=='ACTIVE':
            descriptor=next(value for value in catalog.installations if installation_id(value)==entry.installation_id)
            if not proof_matches(descriptor,by_id.get(entry.installation_id)):raise PersistenceError('restore_required')
    with database.engine.begin() as conn:
        _source_operator_lock(conn)
        verify_inventory(conn,runtime_role=runtime_role,gateway_role=gateway_role,ungranted_restore=True)
        if execute(conn,'SELECT digest FROM wl_sources.catalog_state WHERE id=1').scalar_one()!=catalog_digest(catalog):
            raise PersistenceError('restore_required')
        if fault:fault('after_catalog_verification')
        state=execute(conn,'SELECT incarnation,restore_epoch FROM wl_pg.instance_state WHERE id=1').mappings().one()
        auth=execute(conn,'SELECT * FROM wl_identity.instance_auth_state WHERE id=1').mappings().one()
        if (not auth['bootstrap_closed'] or auth['admin_user_id'] is None or (not replace_missing_key and auth['key_digest']!=key_digest)
                or not execute(conn,'SELECT1 FROM wl_identity.users WHERE id=:id'.replace('SELECT1','SELECT 1'),id=auth['admin_user_id']).scalar()):
            raise PersistenceError('restore_required')
        if replace_missing_key and auth['key_digest']==key_digest:raise PersistenceError('invalid_config')
        if state['restore_epoch']>=COUNTER_MAX:raise PersistenceError('counter_exhausted')
        execute(conn,'SELECT id FROM wl_identity.invites ORDER BY id FOR UPDATE').all()
        now=execute(conn,'SELECT wl_identity._clock_timestamp_v1()').scalar_one()
        if not execute(conn,'SELECT pg_catalog.isfinite(:n)',n=now).scalar_one() or now<auth['last_observed_at']:
            raise PersistenceError('restore_required')
        execute(conn,'UPDATE wl_pg.instance_state SET ready=false WHERE id=1')
        execute(conn,"UPDATE wl_identity.invites SET status='revoked',revocation_reason='restore' WHERE status='issued'")
        if fault:fault('after_restore_invites')
        if execute(conn,"SELECT1 FROM wl_pg.jobs WHERE status='running' AND fencing_token=:maximum LIMIT1".replace('SELECT1','SELECT 1').replace('LIMIT1','LIMIT 1'),maximum=COUNTER_MAX).scalar():raise PersistenceError('counter_exhausted')
        execute(conn,"""UPDATE wl_pg.jobs j SET fencing_token=fencing_token+1,worker_id=NULL,lease_expires_at=NULL,
          status=CASE WHEN EXISTS(SELECT1 FROM wl_pg.job_effect_receipts r WHERE r.tenant_id=j.tenant_id AND r.portfolio_id=j.portfolio_id AND r.job_id=j.id)
          THEN 'succeeded' WHEN attempt>=max_attempts THEN 'failed' ELSE 'queued' END WHERE status='running'""".replace('SELECT1','SELECT 1'))
        incarnation=uuid.uuid4()
        execute(conn,'UPDATE wl_pg.instance_state SET incarnation=:id,restore_epoch=restore_epoch+1 WHERE id=1',id=incarnation)
        execute(conn,'UPDATE wl_identity.instance_auth_state SET last_observed_at=:n,key_digest=:key WHERE id=1',n=now,key=key_digest)
        if fault:fault('after_restore_epoch')
        execute(conn,"INSERT INTO wl_identity.auth_audit VALUES(:id,:n,'restore_finalized',:subject,NULL)",id=uuid.uuid4(),n=now,subject=incarnation)
        if fault:fault('after_restore_audit')
        source_grants(conn,runtime_role,gateway_role)
        verify_inventory(conn,runtime_role=runtime_role,gateway_role=gateway_role)
        if fault:fault('before_source_ready')
        execute(conn,'UPDATE wl_pg.instance_state SET ready=true WHERE id=1')
        if fault:fault('before_restore_commit')
    return database.status()
