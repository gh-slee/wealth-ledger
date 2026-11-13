"""Code-owned PostgreSQL definitions for the explicit ingestion profile."""
from . import ingestion_schema as ingestion
from . import source_schema as source


def inherited_guard_replacements():
    """Advance only predecessor functions that check the profile revision."""
    import re

    predecessor = "'" + ingestion.PREDECESSOR + "'"
    successor = "'" + ingestion.REVISION + "'"
    definitions = source.identity_replacements() + "\n" + source.gateway_ddl()
    pattern = re.compile(
        r"CREATE (?:OR REPLACE )?FUNCTION (wl_identity|wl_sources)\.([a-z_0-9]+)\("
        r"[^;]*? AS (\$[a-z_]*\$).*?\3;", re.S,
    )
    matches = list(pattern.finditer(definitions))
    expected = 21 + len(source.GATEWAY)
    if len(matches) != expected or len({m.group(1, 2) for m in matches}) != expected:
        raise ValueError("Unexpected inherited function definitions")
    replacements = []
    for definition in matches:
        sql = definition.group()
        if predecessor not in sql:
            continue
        sql = sql.replace("CREATE FUNCTION ", "CREATE OR REPLACE FUNCTION ", 1)
        replacements.append(sql.replace(predecessor, successor))
    return "\n".join(replacements)


def function_ddl():
    """Render the new functions in installation order after table creation."""
    return "\n".join((
        ingestion.IMMUTABLE_DDL,
        ingestion.OUTBOX_GUARD_DDL,
        ingestion.TRANSITION_DDL,
        ingestion.HEAD_DDL,
        ingestion.user_guard_ddl(),
        ingestion.worker_guard_ddl(),
        ingestion.minimal_validator_ddl(),
        ingestion.plan_validator_ddl(),
        ingestion.reference_validator_ddl(),
        ingestion.REPLAY_DDL,
        ingestion.effects_ddl(),
        ingestion.ACCEPT_DDL,
        ingestion.QUOTA_DDL,
        ingestion.ADMIT_RATE_DDL,
        ingestion.PURGE_DDL,
        ingestion.CANCEL_DDL,
        ingestion.DECIDE_DDL,
        ingestion.READ_SET_DDL,
        ingestion.READ_RECEIPT_DDL,
        ingestion.READ_SETS_DDL,
        ingestion.READ_PREVIEW_DDL,
        ingestion.CREATE_DDL,
        ingestion.RESERVE_DDL,
        ingestion.CLAIM_DDL,
        ingestion.RENEW_DDL,
        ingestion.ADMIT_DDL,
        ingestion.FINISH_DDL,
        ingestion.CLAIM_PLAN_DDL,
        ingestion.CLEANUP_SET_DDL,
        ingestion.read_plan_basis_ddl(),
        ingestion.prepare_preview_ddl(),
    ))


def grants(conn, runtime_role, gateway_role, worker_role):
    """Apply the ingestion privilege matrix inside the operator transaction."""
    from . import identity_schema
    from .context import execute
    from .errors import PersistenceError
    from .migration import _operator, _role

    owner = _operator(conn)
    roles = (runtime_role, gateway_role, worker_role)
    if len({owner, *roles}) != 4:
        raise PersistenceError("migration_role_required")
    quoted_roles = {role: _role(role) for role in roles}
    for role in roles:
        safe = execute(conn, """
            SELECT r.rolcanlogin AND NOT (r.rolsuper OR r.rolbypassrls OR r.rolcreatedb
              OR r.rolcreaterole OR r.rolreplication) AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid)
              AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_shdepend d
                WHERE d.refclassid='pg_catalog.pg_authid'::regclass AND d.refobjid=r.oid
                AND d.deptype='o' AND d.dbid IN (0,(
                  SELECT oid FROM pg_catalog.pg_database WHERE datname=pg_catalog.current_database())))
            FROM pg_catalog.pg_roles r WHERE r.rolname=:role
        """, role=role).scalar_one_or_none()
        if not safe:
            raise PersistenceError("migration_role_required")

    runtime, gateway, worker = (quoted_roles[role] for role in roles)
    schemas = "wl_pg, wl_identity, wl_sources, wl_ingestion"
    grantees = ", ".join(("PUBLIC", runtime, gateway, worker))
    execute(conn, f"REVOKE ALL ON SCHEMA {schemas} FROM {grantees}")
    execute(conn, f"REVOKE ALL ON ALL TABLES IN SCHEMA {schemas} FROM {grantees}")
    execute(conn, f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {schemas} FROM {grantees}")
    columns = execute(conn, """
        SELECT pg_catalog.quote_ident(n.nspname)||'.'||pg_catalog.quote_ident(c.relname),
               pg_catalog.string_agg(pg_catalog.quote_ident(a.attname),',' ORDER BY a.attnum)
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion')
          AND a.attnum>0 AND NOT a.attisdropped AND a.attacl IS NOT NULL
        GROUP BY n.nspname,c.relname
    """).all()
    for table, names in columns:
        execute(conn, f"REVOKE ALL ({names}) ON TABLE {table} FROM {grantees}")
    database = execute(conn, "SELECT pg_catalog.quote_ident(pg_catalog.current_database())").scalar_one()
    execute(conn, f"REVOKE CREATE, TEMPORARY ON DATABASE {database} FROM {grantees}")
    execute(conn, f"REVOKE CREATE ON SCHEMA public FROM {grantees}")

    execute(conn, f"GRANT USAGE ON SCHEMA wl_pg, wl_sources, wl_ingestion TO {runtime}")
    execute(conn, f"GRANT USAGE ON SCHEMA wl_identity, wl_sources, wl_ingestion TO {gateway}")
    execute(conn, f"GRANT USAGE ON SCHEMA wl_ingestion TO {worker}")
    execute(conn, f"GRANT SELECT ON ALL TABLES IN SCHEMA wl_pg, wl_sources TO {runtime}")
    accepted = ", ".join("wl_ingestion." + table for table in ingestion.READ_TABLES)
    execute(conn, f"GRANT SELECT ON TABLE {accepted} TO {runtime}")
    for signature in (
        *(identity_schema.signature(name) for name in identity_schema.GATEWAY),
        *(source.signature(name) for name in source.GATEWAY),
        *(ingestion.signature(name) for name in ingestion.GATEWAY),
    ):
        execute(conn, f"GRANT EXECUTE ON FUNCTION {signature} TO {gateway}")
    for name in ingestion.WORKER:
        execute(conn, f"GRANT EXECUTE ON FUNCTION {ingestion.signature(name)} TO {worker}")
