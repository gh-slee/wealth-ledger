"""Scoped, bounded SQLAlchemy Core transactions for the optional PG foundation."""
from contextlib import contextmanager
from dataclasses import dataclass
import uuid
from .errors import PersistenceError

SCHEMA = "wl_pg"
REVISION = "0001_foundation"
COUNTER_MAX = 9223372036854775807


def identifier(value):
    try:
        parsed = uuid.UUID(value)
        if type(value) is not str or not parsed.int or str(parsed) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise PersistenceError("invalid_context") from None
    return value


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str
    portfolio_id: str

    def __post_init__(self):
        identifier(self.tenant_id)
        identifier(self.portfolio_id)


@dataclass(frozen=True, slots=True)
class UnitOfWork:
    connection: object
    context: TenantContext
    incarnation: str
    epoch: int


def execute(connection, sql, **parameters):
    from sqlalchemy import text
    return connection.execute(text(sql), parameters)


class Database:
    def __init__(self, config):
        from sqlalchemy import create_engine, event
        from psycopg.conninfo import conninfo_to_dict
        self.engine = create_engine("postgresql+psycopg://", connect_args=conninfo_to_dict(config.conninfo),
            pool_size=config.pool_size, max_overflow=0, pool_timeout=5,
            pool_pre_ping=True, hide_parameters=True, echo=False)

        @event.listens_for(self.engine, "reset")
        def reset(connection, record, state):
            if state.terminate_only:
                return
            connection.rollback()
            previous = connection.autocommit
            try:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute("RESET ROLE; RESET ledger.tenant_id; RESET ledger.portfolio_id")
            finally:
                connection.autocommit = previous

    def close(self):
        self.engine.dispose()

    def status(self):
        try:
            with self.engine.connect() as conn:
                if not 180000<=execute(conn,"SELECT current_setting('server_version_num')::integer").scalar_one()<190000:
                    raise PersistenceError("schema_unsupported")
                version = execute(conn, "SELECT version_num FROM wl_pg.alembic_version").scalar_one()
                state = execute(conn, "SELECT incarnation,restore_epoch,ready FROM wl_pg.instance_state WHERE id=1").mappings().one()
                if version != REVISION:
                    raise PersistenceError("schema_unsupported")
                if not state["ready"]:
                    raise PersistenceError("restore_required")
                return {"schema_revision": version, "incarnation": str(state["incarnation"]),
                        "restore_epoch": state["restore_epoch"], "ready": True}
        except PersistenceError:
            raise
        except Exception:
            raise PersistenceError("schema_unsupported") from None

    @contextmanager
    def transaction(self, context, *, readonly=False):
        if type(context) is not TenantContext or type(readonly) is not bool:
            raise PersistenceError("invalid_context")
        from sqlalchemy.exc import DBAPIError
        try:
            with self.engine.connect().execution_options(
                    isolation_level="REPEATABLE READ" if readonly else "READ COMMITTED") as conn:
                with conn.begin():
                    if readonly:
                        execute(conn, "SET TRANSACTION READ ONLY")
                    if not 180000<=execute(conn,"SELECT current_setting('server_version_num')::integer").scalar_one()<190000:
                        raise PersistenceError("schema_unsupported")
                    execute(conn, "SELECT set_config('ledger.tenant_id',:tenant,true),set_config('ledger.portfolio_id',:portfolio,true)",
                            tenant=context.tenant_id, portfolio=context.portfolio_id)
                    version = execute(conn, "SELECT version_num FROM wl_pg.alembic_version").scalar_one()
                    if version != REVISION:
                        raise PersistenceError("schema_unsupported")
                    state = execute(conn, "SELECT incarnation,restore_epoch,ready FROM wl_pg.instance_state WHERE id=1").mappings().one()
                    if not state["ready"]:
                        raise PersistenceError("restore_required")
                    yield UnitOfWork(conn, context, str(state["incarnation"]), state["restore_epoch"])
        except DBAPIError as error:
            # The retry coordinator needs only the SQLSTATE, never SQL/parameters.
            code = getattr(error.orig, "sqlstate", None)
            if code in {"40001", "40P01"}:
                failure = PersistenceError("retry_exhausted")
                failure.sqlstate = code
                raise failure from None
            raise PersistenceError("database_unavailable") from None
