"""Six EXECUTE-only source calls, distinct from finance transactions and receipts."""
import json
import time

from .context import Database, execute
from .identity import IdentityError, Principal, REALM_KEYS, STATUS as IDENTITY_STATUS
from .source_schema import ARGUMENTS, GATEWAY, TABLES, TENANT_TABLES, TRIGGERS
from ..data_sources.catalog_v1 import catalog_digest
from ..data_sources.lifecycle_v1 import SourceError, STATUS


class SourceStore:
    def __init__(self, config, catalog):
        self.database = Database(config, schema_mode="sources")
        self.catalog_digest = catalog_digest(catalog)

    def close(self):
        self.database.close()

    def call(self, name, principal, payload, *, deadline=None, before_commit=None):
        if name not in GATEWAY or type(principal) is not Principal or type(payload) is not dict:
            raise IdentityError()
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        deadline = time.monotonic() + 20 if deadline is None else deadline
        arguments = (principal.session_digest, principal.user_id, principal.credential_version,
                     dict(zip(REALM_KEYS, principal.realm)), self.catalog_digest, payload)
        slots = []
        parameters = {}
        for index, (kind, value) in enumerate(zip(ARGUMENTS, arguments)):
            parameters["p"+str(index)] = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if kind == "jsonb" else value
            slots.append("CAST(:p"+str(index)+" AS pg_catalog."+{"bigint":"int8"}.get(kind,kind)+")")
        statement = text("SELECT wl_sources."+name+"("+",".join(slots)+")")
        result = None
        for attempt in range(3):
            if time.monotonic() >= deadline:
                raise IdentityError()
            try:
                with self.database.engine.connect() as conn:
                    transaction = conn.begin()
                    try:
                        remaining = max(1,min(5000,int((deadline-time.monotonic())*1000)))
                        conn.execute(text("SELECT pg_catalog.set_config('statement_timeout',:timeout,true),pg_catalog.set_config('lock_timeout',:lock,true)"),
                                     {"timeout":str(remaining),"lock":str(min(2000,remaining))})
                        result = conn.execute(statement, parameters).scalar_one()
                        if type(result) is not dict or type(result.get("ok")) is not bool:
                            raise IdentityError()
                        if before_commit is not None and result.get("ok") is True:
                            before_commit(result["value"])
                        if time.monotonic() >= deadline:
                            raise IdentityError()
                    except BaseException:
                        transaction.rollback()
                        raise
                    try:
                        transaction.commit()
                    except DBAPIError as error:
                        if getattr(error.orig,"sqlstate",None) in {"40001","40P01"}:
                            raise
                        raise SourceError("source_commit_uncertain") from None
                    except Exception:
                        raise SourceError("source_commit_uncertain") from None
                break
            except (IdentityError,SourceError):
                raise
            except DBAPIError as error:
                if getattr(error.orig,"sqlstate",None) in {"40001","40P01"} and attempt<2 and time.monotonic()<deadline:
                    continue
                raise IdentityError() from None
            except Exception:
                raise IdentityError() from None
        if result.get("ok") is True and set(result)=={"ok","value"} and type(result["value"]) is dict:
            return result["value"]
        if set(result)=={"ok","code"}:
            if result["code"] in STATUS:
                raise SourceError(result["code"])
            if result["code"] in IDENTITY_STATUS:
                raise IdentityError(result["code"])
        raise IdentityError()


def source_role_inventory(conn, *, gateway):
    """Check effective EXECUTE/raw/column rights of the closed sources profile."""
    owner=execute(conn,"SELECT nspowner FROM pg_catalog.pg_namespace WHERE nspname='wl_sources'").scalar_one()
    if execute(conn,"SELECT has_schema_privilege(current_user,'wl_sources','CREATE')").scalar_one():
        raise IdentityError()
    functions=execute(conn,"""SELECT p.proname,pg_catalog.oidvectortypes(p.proargtypes) AS args,p.prorettype::regtype::text AS result,
        p.prosecdef,p.proowner,p.proconfig,has_function_privilege(current_user,p.oid,'EXECUTE') AS executable
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='wl_sources'""").mappings().all()
    if len(functions)!=8 or {x['proname'] for x in functions}!=set((*GATEWAY,*TRIGGERS)):
        raise IdentityError()
    for item in functions:
        expected_args=", ".join(ARGUMENTS) if item['proname'] in GATEWAY else ""
        if (item['args']!=expected_args or item['proowner']!=owner or not item['prosecdef']
                or item['result']!=('jsonb' if item['proname'] in GATEWAY else 'trigger')
                or item['executable']!=(gateway and item['proname'] in GATEWAY)
                or 'search_path=pg_catalog,pg_temp' not in [x.replace(' ','') for x in item['proconfig'] or []]):
            raise IdentityError()
    tables=execute(conn,"""SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,c.relowner,
        has_table_privilege(current_user,c.oid,'SELECT') AS readable,
        has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') AS writable,
        has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES') AS column_write,
        has_any_column_privilege(current_user,c.oid,'SELECT') AS column_read
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='wl_sources' AND c.relkind='r'""").mappings().all()
    if len(tables)!=7 or {x['relname'] for x in tables}!=set(TABLES):
        raise IdentityError()
    for item in tables:
        if (item['relowner']!=owner or item['relrowsecurity']!=(item['relname'] in TENANT_TABLES)
                or item['relforcerowsecurity']!=(item['relname'] in TENANT_TABLES)
                or item['writable'] or item['column_write'] or item['readable']==gateway or item['column_read']==gateway):
            raise IdentityError()
