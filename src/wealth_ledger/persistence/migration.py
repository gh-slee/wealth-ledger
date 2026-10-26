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
