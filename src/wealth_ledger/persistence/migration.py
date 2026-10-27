"""Explicit operator migrations, anchor seeding and empty-target restore finalization."""
from pathlib import Path
import re
import uuid
from .context import COUNTER_MAX, REVISION, execute
from .errors import PersistenceError
from .schema import ddl


def _role(value):
    if type(value) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise PersistenceError("invalid_config")
    return '"' + value + '"'


def _operator(conn):
    if not 180000<=execute(conn,"SELECT current_setting('server_version_num')::integer").scalar_one()<190000:
        raise PersistenceError("schema_unsupported")
    row=execute(conn,"SELECT current_user,has_database_privilege(current_database(),'CREATE') AS allowed").mappings().one()
    if not row["allowed"]:
        raise PersistenceError("migration_role_required")
    return row["current_user"]


def _grants(conn, runtime_role):
    runtime=_role(runtime_role)
    owner=_operator(conn)
    role=execute(conn,"SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=:role",role=runtime_role).mappings().one_or_none()
    if (not role or any(role.values()) or runtime_role==owner or
            execute(conn,"SELECT pg_has_role(:role,current_user,'MEMBER')",role=runtime_role).scalar()):
        raise PersistenceError("migration_role_required")
    execute(conn,"REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    execute(conn,"REVOKE ALL ON SCHEMA wl_pg FROM PUBLIC")
    execute(conn,"REVOKE ALL ON ALL TABLES IN SCHEMA wl_pg FROM PUBLIC")
    execute(conn,"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA wl_pg FROM PUBLIC")
    execute(conn,"ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")
    execute(conn,f"GRANT USAGE ON SCHEMA wl_pg TO {runtime}")
    execute(conn,f"GRANT SELECT ON ALL TABLES IN SCHEMA wl_pg TO {runtime}")
    for signature in ["decimal_token_v1(text)","decimal_pair_v1(text,numeric)","quantity_pair_v1(text,numeric,boolean)"]:
        execute(conn,f"GRANT EXECUTE ON FUNCTION wl_pg.{signature} TO {runtime}")
    _,tables,immutable=ddl()
    for name in tables:
        execute(conn,f"DROP POLICY IF EXISTS operator_scope ON wl_pg.{name}")
        execute(conn,f"CREATE POLICY operator_scope ON wl_pg.{name} TO {_role(owner)} USING(true) WITH CHECK(true)")
        if name not in {'tenant_roots','portfolios'}:
            execute(conn,f"GRANT INSERT ON wl_pg.{name} TO {runtime}")
    for table,columns in [('portfolios','fact_generation'),('connections','generation'),
            ('repository_heads','batch_id,revision_key'),('outbox','dispatched_at'),
            ('jobs','status,attempt,fencing_token,worker_id,lease_expires_at,available_at,error_code,cancel_requested,lease_seconds')]:
        execute(conn,f"GRANT UPDATE({columns}) ON wl_pg.{table} TO {runtime}")


def migrate(database, runtime_role, *, fault=None):
    """Upgrade one recognized target atomically; never stamp/drop/repair a target."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import SQLAlchemyError
    try:
        with database.engine.begin() as conn:
            _operator(conn)
            execute(conn,"SELECT pg_advisory_xact_lock(1950174004)")
            tables=execute(conn,"SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')").all()
            if tables:
                if any(row[0]!='wl_pg' for row in tables) or not any(row[1]=='alembic_version' for row in tables):
                    raise PersistenceError("migration_target_invalid")
                if execute(conn,"SELECT version_num FROM wl_pg.alembic_version").scalars().all()!=[REVISION]:
                    raise PersistenceError("schema_unsupported")
            else:
                execute(conn,"CREATE SCHEMA IF NOT EXISTS wl_pg")
            configuration=Config()
            configuration.set_main_option("script_location",str(Path(__file__).parent/'migrations'))
            configuration.attributes['connection']=conn
            command.upgrade(configuration,REVISION)
            if fault:
                fault('after_schema')
            _grants(conn,runtime_role)
        return database.status()
    except PersistenceError:
        raise
    except SQLAlchemyError:
        raise PersistenceError("migration_target_invalid") from None


def seed_tenant(database, context):
    """Explicit operator bootstrap only; no HTTP account creation/authentication."""
    with database.engine.begin() as conn:
        _operator(conn)
        execute(conn,"INSERT INTO wl_pg.tenant_roots(tenant_id,portfolio_id) VALUES(:t,:p) ON CONFLICT DO NOTHING",t=context.tenant_id,p=context.portfolio_id)
        execute(conn,"INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES(:t,:p) ON CONFLICT DO NOTHING",t=context.tenant_id,p=context.portfolio_id)
        if not execute(conn,"SELECT 1 FROM wl_pg.portfolios WHERE tenant_id=:t AND portfolio_id=:p",t=context.tenant_id,p=context.portfolio_id).scalar():
            raise PersistenceError("reference_conflict")


def finalize_restore(database, runtime_role):
    """Finalize an isolated restored target before any runtime grants/worker start."""
    with database.engine.begin() as conn:
        _operator(conn)
        execute(conn,"SELECT pg_advisory_xact_lock(1950174004)")
        if execute(conn,"SELECT version_num FROM wl_pg.alembic_version").scalars().all()!=[REVISION]:
            raise PersistenceError("schema_unsupported")
        row=execute(conn,"SELECT restore_epoch FROM wl_pg.instance_state WHERE id=1 FOR UPDATE").mappings().one()
        if row['restore_epoch']>=COUNTER_MAX:
            raise PersistenceError("counter_exhausted")
        execute(conn,"UPDATE wl_pg.instance_state SET ready=false WHERE id=1")
        _grants(conn,runtime_role)
        if execute(conn,"SELECT 1 FROM wl_pg.jobs WHERE status='running' AND fencing_token=:maximum LIMIT 1",maximum=COUNTER_MAX).scalar():
            raise PersistenceError("counter_exhausted")
        execute(conn,"""UPDATE wl_pg.jobs j SET fencing_token=fencing_token+1,worker_id=NULL,lease_expires_at=NULL,
            status=CASE WHEN EXISTS(SELECT 1 FROM wl_pg.job_effect_receipts r WHERE r.tenant_id=j.tenant_id AND r.portfolio_id=j.portfolio_id AND r.job_id=j.id)
              THEN 'succeeded' WHEN attempt>=max_attempts THEN 'failed' ELSE 'queued' END
            WHERE status='running'""")
        execute(conn,"UPDATE wl_pg.instance_state SET incarnation=:incarnation,restore_epoch=restore_epoch+1,ready=true WHERE id=1",incarnation=uuid.uuid4())
    return database.status()


def _identity_grants(conn, runtime_role, gateway_role):
    """Grant only the closed0002 inventory; operator rights never enter the API."""
    from .identity_schema import GATEWAY, SIGNATURES, signature
    owner = _operator(conn)
    if len({owner, runtime_role, gateway_role}) != 3:
        raise PersistenceError('migration_role_required')
    for role in [runtime_role, gateway_role]:
        _role(role)
        row = execute(conn, '''SELECT r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole,
          EXISTS(SELECT 1 FROM pg_namespace WHERE nspname IN ('wl_identity','wl_pg') AND nspowner=r.oid)
            OR r.oid=(SELECT datdba FROM pg_database WHERE datname=current_database()) AS owns
          FROM pg_roles r WHERE r.rolname=:role''', role=role).mappings().one_or_none()
        if (row is None or any(row.values()) or execute(conn,
                'SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=:role)', role=role).first()):
            raise PersistenceError('migration_role_required')
    _grants(conn, runtime_role)
    gateway, runtime = _role(gateway_role), _role(runtime_role)
    for role in [gateway, runtime]:
        execute(conn, f'REVOKE ALL ON SCHEMA wl_identity FROM {role}')
        execute(conn, f'REVOKE ALL ON ALL TABLES IN SCHEMA wl_identity FROM {role}')
        execute(conn, f'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA wl_identity FROM {role}')
    execute(conn, f'REVOKE ALL ON SCHEMA wl_pg FROM {gateway}')
    execute(conn, f'REVOKE ALL ON ALL TABLES IN SCHEMA wl_pg FROM {gateway}')
    execute(conn, f'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA wl_pg FROM {gateway}')
    execute(conn, 'REVOKE ALL ON SCHEMA wl_identity FROM PUBLIC')
    execute(conn, 'REVOKE ALL ON ALL TABLES IN SCHEMA wl_identity FROM PUBLIC')
    execute(conn, 'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA wl_identity FROM PUBLIC')
    execute(conn, f'GRANT USAGE ON SCHEMA wl_identity TO {gateway}')
    for name in GATEWAY:
        assert name in SIGNATURES
        execute(conn, f'GRANT EXECUTE ON FUNCTION {signature(name)} TO {gateway}')


def _identity_target_inventory(conn, version):
    """Recognize only the immutable PG18 catalog identities for0001/0002."""
    import hashlib
    import json
    from .identity_schema import SIGNATURES, TABLES, REVISION as identity_revision
    _,finance,immutable=ddl()
    tables={('wl_pg',name) for name in [*finance,'instance_state','alembic_version']} if version else set()
    if version==identity_revision:tables.update(('wl_identity',name) for name in TABLES)
    relations=execute(conn,"""SELECT n.nspname,c.relname,c.oid,c.relkind,c.relrowsecurity,c.relforcerowsecurity,
      EXISTS(SELECT 1 FROM pg_constraint k WHERE k.conindid=c.oid) AS constraint_index
      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname IN ('public','wl_pg','wl_identity')""").mappings().all()
    explicit={('wl_pg','jobs_ready'),('wl_pg','outbox_pending')} if version else set()
    if version==identity_revision:explicit.add(('wl_identity','one_armed_setup'))
    for row in relations:
        identity=(row['nspname'],row['relname'])
        if row['relkind']=='r':
            private=row['nspname']=='wl_pg' and row['relname'] in finance
            if identity not in tables or row['relrowsecurity']!=private or row['relforcerowsecurity']!=private:
                raise PersistenceError('migration_target_invalid')
        elif row['relkind']=='i':
            if identity not in explicit and not row['constraint_index']:
                raise PersistenceError('migration_target_invalid')
        else:
            raise PersistenceError('migration_target_invalid')
    if {(r['nspname'],r['relname']) for r in relations if r['relkind']=='r'}!=tables:
        raise PersistenceError('migration_target_invalid')
    expected_functions={('wl_pg','decimal_token_v1',('text',)),('wl_pg','decimal_pair_v1',('text','numeric')),
      ('wl_pg','quantity_pair_v1',('text','numeric','boolean')),('wl_pg','reject_mutation',()),
      ('wl_pg','connection_generation_only',()),('wl_pg','job_request_immutable',())} if version else set()
    if version==identity_revision:
        expected_functions.update(('wl_identity',name,tuple(types)) for name,types in SIGNATURES.items())
    rows=execute(conn,"""SELECT n.nspname,p.proname,pg_catalog.oidvectortypes(p.proargtypes) AS args,p.prokind
      FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname IN ('public','wl_pg','wl_identity')""").all()
    found={(ns,name,tuple(args.split(', ')) if args else ()) for ns,name,args,kind in rows}
    if found!=expected_functions or len(rows)!=len(found) or any(row[3]!='f' for row in rows):
        raise PersistenceError('migration_target_invalid')
    # Only table composite types and their automatic arrays are part of these DDLs.
    types=execute(conn,"""SELECT t.oid,t.typrelid,t.typelem,t.typcategory FROM pg_type t
      JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname IN ('public','wl_pg','wl_identity')""").all()
    relation_ids={r['oid'] for r in relations if r['relkind']=='r'}
    allowed={oid for oid,relation,element,category in types if relation in relation_ids}
    allowed.update(oid for oid,relation,element,category in types if element in allowed and category=='A')
    if any(row[0] not in allowed for row in types):raise PersistenceError('migration_target_invalid')
    for catalog in ['pg_operator','pg_collation','pg_conversion','pg_ts_config','pg_ts_dict','pg_ts_parser','pg_ts_template']:
        column={'pg_operator':'oprnamespace','pg_collation':'collnamespace','pg_conversion':'connamespace',
                'pg_ts_config':'cfgnamespace','pg_ts_dict':'dictnamespace','pg_ts_parser':'prsnamespace',
                'pg_ts_template':'tmplnamespace'}[catalog]
        if execute(conn,f"SELECT 1 FROM pg_catalog.{catalog} o JOIN pg_namespace n ON n.oid=o.{column} WHERE n.nspname IN ('public','wl_pg','wl_identity') LIMIT 1").first():
            raise PersistenceError('migration_target_invalid')
    if execute(conn,"""SELECT 1 FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class
      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wl_pg','wl_identity') LIMIT 1""").first():
        raise PersistenceError('migration_target_invalid')
    policies=execute(conn,"""SELECT n.nspname,c.relname,p.polname FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wl_pg','wl_identity')""").all()
    expected_policies={('wl_pg',name,policy) for name in finance for policy in ['scope','operator_scope']} if version else set()
    if set(map(tuple,policies))!=expected_policies:raise PersistenceError('migration_target_invalid')
    triggers=execute(conn,"""SELECT n.nspname,c.relname,t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE NOT t.tgisinternal AND n.nspname IN ('public','wl_pg','wl_identity')""").all()
    expected_triggers={('wl_pg',name,'immutable') for name in [*immutable,'connections']} if version else set()
    if version:expected_triggers.add(('wl_pg','jobs','immutable_request'))
    if set(map(tuple,triggers))!=expected_triggers:raise PersistenceError('migration_target_invalid')
    # Fixed identities, not row data or OIDs: includes PG18 NOT NULL constraints.
    # Changing either DDL requires an ordered reviewed revision, never a live stamp.
    constraints=execute(conn,"""SELECT n.nspname,t.relname,c.conname,c.contype FROM pg_constraint c
      JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
      WHERE n.nspname IN ('wl_pg','wl_identity','public')""").all()
    columns=execute(conn,"""SELECT n.nspname,c.relname,a.attnum,a.attname,tn.nspname,t.typname,a.atttypmod,
      a.attnotnull,a.attgenerated,a.attidentity,cn.nspname,co.collname FROM pg_attribute a
      JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace tn ON tn.oid=t.typnamespace
      LEFT JOIN pg_collation co ON co.oid=a.attcollation LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace
      WHERE n.nspname IN ('wl_pg','wl_identity','public') AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped""").all()
    known={'0001_foundation':('f524e1650e34a39676e919a1f85fb5c2e8a7ce3ea78b7467f76acd7cde3e62a2',
                              'b8a008cb1cabd9d9b992f03257ed5967bacd921f51c85559bce92320823309f5'),
           '0002_identity':('ad3b2348396b364708f413872e76981fd5b31a50a6d9afd97fa8175b26504d33',
                            'efaf8c384e319a44df4c1b278d0e73d54aaa480cdb449b170f07ef4804e92d90')}
    hashes=tuple(hashlib.sha256(json.dumps(sorted(map(list,rows)),separators=(',',':')).encode()).hexdigest() for rows in [constraints,columns])
    if version:
        if hashes!=known[version]:raise PersistenceError('migration_target_invalid')
    elif constraints or columns:raise PersistenceError('migration_target_invalid')


def migrate_identity(database, runtime_role, gateway_role, key_digest, *, fault=None):
    """Atomic explicit0002 upgrade, never auto-migrate a running legacy instance."""
    from .identity_schema import REVISION as identity_revision, TABLES
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import SQLAlchemyError
    if database.schema_mode != 'identity' or not re.fullmatch(r'[0-9a-f]{64}', key_digest or ''):
        raise PersistenceError('invalid_config')
    try:
        with database.engine.begin() as conn:
            _operator(conn)
            execute(conn, 'SELECT pg_advisory_xact_lock(1950174004)')
            schemas=execute(conn,"SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname NOT IN ('information_schema','public','wl_pg','wl_identity')").all()
            extras=execute(conn,"SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','wl_pg','wl_identity') AND c.relkind IN ('v','m','S','f') LIMIT 1").first()
            if schemas or extras:
                raise PersistenceError('migration_target_invalid')
            tables = execute(conn, "SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')").all()
            if tables:
                if any(row[0] not in {'wl_pg', 'wl_identity'} for row in tables):
                    raise PersistenceError('migration_target_invalid')
                version = execute(conn, 'SELECT version_num FROM wl_pg.alembic_version').scalars().all()
                if version not in [[REVISION], [identity_revision]]:
                    raise PersistenceError('schema_unsupported')
                _, finance, _ = ddl()
                expected = {('wl_pg', name) for name in [*finance, 'instance_state', 'alembic_version']}
                if version == [identity_revision]:
                    expected.update(('wl_identity', name) for name in TABLES)
                if set(map(tuple, tables)) != expected:
                    raise PersistenceError('migration_target_invalid')
                # Same lock order as restore/auth, before any upgrade or grant work.
                execute(conn,'SELECT id FROM wl_pg.instance_state WHERE id=1 FOR UPDATE').one()
                if version==[identity_revision]:
                    execute(conn,'SELECT id FROM wl_identity.instance_auth_state WHERE id=1 FOR UPDATE').one()
                _identity_target_inventory(conn,version[0])
            else:
                _identity_target_inventory(conn,None)
                execute(conn, 'CREATE SCHEMA IF NOT EXISTS wl_pg')
            configuration = Config()
            configuration.set_main_option('script_location', str(Path(__file__).parent/'migrations'))
            configuration.attributes.update(connection=conn, identity_key_digest=key_digest)
            command.upgrade(configuration, identity_revision)
            if fault:
                fault('after_identity_schema')
            if execute(conn, 'SELECT key_digest FROM wl_identity.instance_auth_state WHERE id=1').scalar_one() != key_digest:
                raise PersistenceError('invalid_config')
            _identity_grants(conn, runtime_role, gateway_role)
            _identity_target_inventory(conn,identity_revision)
            if fault:
                fault('after_identity_grants')
        return database.status()
    except PersistenceError:
        raise
    except SQLAlchemyError:
        raise PersistenceError('migration_target_invalid') from None


def finalize_identity_restore(database, runtime_role, gateway_role, key_digest, *, replace_missing_key=False, fault=None):
    """One restore transaction: epoch/job fences, revoked invites and true audit."""
    from .identity_schema import REVISION as identity_revision
    if (database.schema_mode != 'identity' or type(replace_missing_key) is not bool
            or type(key_digest) is not str or not re.fullmatch(r'[0-9a-f]{64}',key_digest)):
        raise PersistenceError('invalid_config')
    with database.engine.begin() as conn:
        _operator(conn)
        execute(conn, 'SELECT pg_advisory_xact_lock(1950174004)')
        if execute(conn, 'SELECT version_num FROM wl_pg.alembic_version').scalar_one() != identity_revision:
            raise PersistenceError('schema_unsupported')
        state = execute(conn, 'SELECT incarnation,restore_epoch FROM wl_pg.instance_state WHERE id=1 FOR UPDATE').mappings().one()
        auth = execute(conn, 'SELECT * FROM wl_identity.instance_auth_state WHERE id=1 FOR UPDATE').mappings().one()
        if (not auth['bootstrap_closed'] or auth['admin_user_id'] is None or (not replace_missing_key and auth['key_digest'] != key_digest)
                or not execute(conn, 'SELECT 1 FROM wl_identity.users WHERE id=:id', id=auth['admin_user_id']).scalar()):
            raise PersistenceError('restore_required')
        if replace_missing_key and auth['key_digest']==key_digest:
            raise PersistenceError('invalid_config')
        if state['restore_epoch'] >= COUNTER_MAX:
            raise PersistenceError('counter_exhausted')
        # Lock every affected row in the common identity order before sampling time.
        execute(conn, 'SELECT id FROM wl_identity.invites ORDER BY id FOR UPDATE').all()
        now = execute(conn, 'SELECT wl_identity._clock_timestamp_v1()').scalar_one()
        if now < auth['last_observed_at']:
            raise PersistenceError('restore_required')
        execute(conn, 'UPDATE wl_pg.instance_state SET ready=false WHERE id=1')
        execute(conn, "UPDATE wl_identity.invites SET status='revoked',revocation_reason='restore' WHERE status='issued'")
        if fault:
            fault('after_restore_invites')
        if execute(conn, "SELECT 1 FROM wl_pg.jobs WHERE status='running' AND fencing_token=:maximum LIMIT 1", maximum=COUNTER_MAX).scalar():
            raise PersistenceError('counter_exhausted')
        execute(conn, """UPDATE wl_pg.jobs j SET fencing_token=fencing_token+1,worker_id=NULL,lease_expires_at=NULL,
          status=CASE WHEN EXISTS(SELECT 1 FROM wl_pg.job_effect_receipts r WHERE r.tenant_id=j.tenant_id AND r.portfolio_id=j.portfolio_id AND r.job_id=j.id)
          THEN 'succeeded' WHEN attempt>=max_attempts THEN 'failed' ELSE 'queued' END WHERE status='running'""")
        incarnation = uuid.uuid4()
        execute(conn, 'UPDATE wl_pg.instance_state SET incarnation=:id,restore_epoch=restore_epoch+1 WHERE id=1', id=incarnation)
        execute(conn, 'UPDATE wl_identity.instance_auth_state SET last_observed_at=:now,key_digest=:key WHERE id=1', now=now,key=key_digest)
        if fault:
            fault('after_restore_epoch')
        execute(conn, "INSERT INTO wl_identity.auth_audit VALUES(:id,:now,'restore_finalized',:subject,NULL)", id=uuid.uuid4(), now=now, subject=incarnation)
        if fault:
            fault('after_restore_audit')
        _identity_grants(conn, runtime_role, gateway_role)
        execute(conn, 'UPDATE wl_pg.instance_state SET ready=true WHERE id=1')
        if fault:
            fault('before_restore_commit')
    return database.status()
