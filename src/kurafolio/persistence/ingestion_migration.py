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


def _checked_roles(conn, roles):
    from .context import execute
    from .errors import PersistenceError
    from .migration import _operator, _role

    owner = _operator(conn)
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

    return owner, quoted_roles


def grants(conn, runtime_role, gateway_role, worker_role):
    """Apply the ingestion privilege matrix inside the operator transaction."""
    from . import identity_schema
    from .context import execute

    roles = (runtime_role, gateway_role, worker_role)
    _, quoted_roles = _checked_roles(conn, roles)
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


def verify_functions(conn):
    """Check inherited and ingestion function definitions against the source."""
    import re

    from . import identity_schema
    from .context import execute
    from .errors import PersistenceError
    from .source_migration import _expected_functions

    inherited = _expected_functions()
    for item in inherited.values():
        item["body"] = item["body"].replace(
            "'" + ingestion.PREDECESSOR + "'", "'" + ingestion.REVISION + "'",
        )
    ddl = ingestion.tables_ddl() + "\n" + function_ddl()
    pattern = r"CREATE FUNCTION wl_ingestion\.([a-z_0-9]+)\(([^)]*)\)\s+([^;]*?) AS (\$[a-z_]*\$)(.*?)\4;"
    new = {name: (tuple(arg.strip().split()[0] for arg in args.split(",") if arg.strip()), header, body)
           for name, args, header, _, body in re.findall(pattern, ddl, re.S)}
    declarations = {item["name"]: item for item in ingestion.inventory()["functions"]}
    if new.keys() != declarations.keys():
        raise PersistenceError("migration_target_invalid")
    rows = execute(conn, """
        SELECT n.nspname AS schema_name,p.proname AS name,p.proargnames AS names,
               pg_catalog.oidvectortypes(p.proargtypes) AS arguments,
               pg_catalog.format_type(p.prorettype,NULL) AS returns,p.prosrc AS body,
               p.prosecdef AS definer,p.proconfig AS config,p.proowner=n.nspowner AS owned,
               p.prokind AS kind,l.lanname AS language,p.proisstrict AS strict,
               p.provolatile AS volatility,p.proparallel AS parallel,p.proleakproof AS leakproof,
               p.proargmodes AS argmodes,p.provariadic<>0 AS variadic,p.pronargdefaults AS defaults
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion')
    """).mappings().all()
    if len(rows) != len(inherited) + len(new):
        raise PersistenceError("migration_target_invalid")
    seen = set()
    for row in rows:
        schema, name = row["schema_name"], row["name"]
        key = (schema, name)
        if (key in seen or not row["owned"] or row["kind"] != "f" or row["leakproof"]
                or row["argmodes"] is not None or row["variadic"] or row["defaults"]):
            raise PersistenceError("migration_target_invalid")
        seen.add(key)
        config = tuple(value.replace(" ", "") for value in row["config"] or ())
        if schema == ingestion.SCHEMA:
            declaration = declarations.get(name)
            if declaration is None:
                raise PersistenceError("migration_target_invalid")
            names, header, body = new[name]
            expected = (names, ", ".join(declaration["arguments"]), declaration["returns"], body,
                        declaration["security_definer"], ("search_path=" + declaration["search_path"],),
                        "sql" if "LANGUAGE sql" in header else "plpgsql", "STRICT" in header,
                        "i" if "IMMUTABLE" in header else "s" if "STABLE" in header else "v",
                        "s" if "PARALLEL SAFE" in header else "r" if "PARALLEL RESTRICTED" in header else "u")
        else:
            item = inherited.get(key)
            if item is None:
                raise PersistenceError("migration_target_invalid")
            if schema == "wl_identity":
                arguments = identity_schema.SIGNATURES[name]
            elif schema == "wl_sources":
                arguments = source.ARGUMENTS if name in source.GATEWAY else ()
            else:
                arguments = {"decimal_token_v1": ("text",), "decimal_pair_v1": ("text", "numeric"),
                             "quantity_pair_v1": ("text", "numeric", "boolean")}.get(name, ())
            if name == "_clock_timestamp_v1":
                returns, language = "timestamp with time zone", "sql"
            elif schema == "wl_identity" or schema == "wl_sources" and name in source.GATEWAY:
                returns, language = "jsonb", "plpgsql"
            elif arguments:
                returns, language = "boolean", "plpgsql"
            else:
                returns, language = "trigger", "plpgsql"
            expected = (item["arguments"], ", ".join(arguments), returns, item["body"], item["definer"],
                        (item["config"],), language, item["strict"], item["volatility"], item["parallel"])
        actual = (tuple(row["names"] or ()), row["arguments"], row["returns"], row["body"], row["definer"],
                  config, row["language"], row["strict"], row["volatility"], row["parallel"])
        if actual != expected:
            raise PersistenceError("migration_target_invalid")
    return len(seen)


def _structure_digest(conn, runtime_role, *, predecessor=False):
    """Fingerprint the installed ingestion objects using stable catalog names."""
    import hashlib

    from .context import execute
    from ..data_sources.contract_v1 import canonical

    # Role names and object OIDs differ across independent installation targets.
    queries = {
        "relations": """
            SELECT n.nspname,c.relname,c.relkind,c.relpersistence,c.relispartition,c.relrowsecurity,
                   c.relforcerowsecurity,c.relowner=n.nspowner
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion') ORDER BY n.nspname,c.relname
        """,
        "columns": """
            SELECT n.nspname,c.relname,a.attnum,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),
                   a.attnotnull,a.attgenerated,a.attidentity,a.attisdropped,cn.nspname,co.collname,
                   pg_catalog.pg_get_expr(d.adbin,d.adrelid)
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            LEFT JOIN pg_catalog.pg_collation co ON co.oid=a.attcollation
            LEFT JOIN pg_catalog.pg_namespace cn ON cn.oid=co.collnamespace
            WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion') AND c.relkind='r' AND a.attnum>0
            ORDER BY n.nspname,c.relname,a.attnum
        """,
        "constraints": """
            SELECT n.nspname,c.relname,k.conname,k.contype,k.condeferrable,k.condeferred,k.convalidated,
                   k.conenforced,pg_catalog.pg_get_constraintdef(k.oid)
            FROM pg_catalog.pg_constraint k
            JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion') ORDER BY n.nspname,c.relname,k.conname
        """,
        "indexes": """
            SELECT n.nspname,c.relname,i.indisvalid,i.indisready,i.indislive,pg_catalog.pg_get_indexdef(c.oid)
            FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion') ORDER BY n.nspname,c.relname
        """,
        "policies": """
            SELECT n.nspname,c.relname,p.polname,p.polcmd,p.polpermissive,
                   ARRAY(SELECT CASE WHEN r=0 THEN 'PUBLIC' WHEN r=n.nspowner THEN 'OWNER'
                       WHEN r=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:runtime) THEN 'READER'
                       ELSE 'UNEXPECTED' END FROM pg_catalog.unnest(p.polroles) r ORDER BY 1),
                   pg_catalog.pg_get_expr(p.polqual,p.polrelid),pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid)
            FROM pg_catalog.pg_policy p
            JOIN pg_catalog.pg_class c ON c.oid=p.polrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion') ORDER BY n.nspname,c.relname,p.polname
        """,
        "types": """
            SELECT n.nspname,t.typname,t.typtype,t.typcategory,c.relname,e.typname
            FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
            LEFT JOIN pg_catalog.pg_class c ON c.oid=t.typrelid
            LEFT JOIN pg_catalog.pg_type e ON e.oid=t.typelem
            WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion')
            ORDER BY n.nspname,t.typname
        """,
        "triggers": """
            SELECT n.nspname,c.relname,t.tgname,t.tgenabled,pg_catalog.pg_get_triggerdef(t.oid)
            FROM pg_catalog.pg_trigger t
            JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion') AND NOT t.tgisinternal ORDER BY n.nspname,c.relname,t.tgname
        """,
    }
    snapshot = {}
    for key, query in queries.items():
        if predecessor:
            query = query.replace(",'wl_ingestion'", "")
        parameters = {"runtime": runtime_role} if key == "policies" else {}
        snapshot[key] = [list(row) for row in execute(conn, query, **parameters).all()]
    return hashlib.sha256(canonical(snapshot)).hexdigest()


# Frozen from the PG18 synthetic installation, never regenerated at startup.
EXPECTED_PREDECESSOR_SHA256 = "e000ca387b3e063fbfa5e27f1d7992d1a1bfbed0ea5ad9fcf08bb5290dd460ac"
EXPECTED_STRUCTURE_SHA256 = "bfa65a6614b9c31be0acbaf2ee4ead29cfc814f18eae2b89267c6a2e5e67a9f3"


def verify_grants(conn, runtime_role, gateway_role, worker_role):
    """Reject extra ACLs, grant options, role powers, or missing grants."""
    from . import identity_schema
    from .context import execute
    from .errors import PersistenceError
    from .schema import ddl

    roles = (runtime_role, gateway_role, worker_role)
    owner, _ = _checked_roles(conn, roles)
    expected = set()
    for role, namespaces in (
        (runtime_role, ("wl_pg", "wl_sources", "wl_ingestion")),
        (gateway_role, ("wl_identity", "wl_sources", "wl_ingestion")),
        (worker_role, ("wl_ingestion",)),
    ):
        expected.update((namespace, "schema", namespace, role, "USAGE") for namespace in namespaces)
    for namespace, tables in (
        ("wl_pg", (*ddl()[1], "alembic_version", "instance_state")),
        ("wl_sources", source.TABLES),
        ("wl_ingestion", ingestion.READ_TABLES),
    ):
        expected.update((namespace, "table", table, runtime_role, "SELECT") for table in tables)
    for namespace, names, role in (
        ("wl_identity", identity_schema.GATEWAY, gateway_role),
        ("wl_sources", source.GATEWAY, gateway_role),
        ("wl_ingestion", ingestion.GATEWAY, gateway_role),
        ("wl_ingestion", ingestion.WORKER, worker_role),
    ):
        expected.update((namespace, "function", name, role, "EXECUTE") for name in names)
    rows = execute(conn, """
        WITH namespaces AS (
            SELECT * FROM pg_catalog.pg_namespace
            WHERE nspname IN ('wl_pg','wl_identity','wl_sources','wl_ingestion')
        ), rights AS (
            SELECT n.nspname,'schema' AS kind,n.nspname AS object_name,a.*
            FROM namespaces n CROSS JOIN LATERAL pg_catalog.aclexplode(
                coalesce(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) a
            UNION ALL
            SELECT n.nspname,'table',c.relname,a.*
            FROM namespaces n JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
            WHERE c.relkind='r'
            UNION ALL
            SELECT n.nspname,'column',c.relname,a.*
            FROM namespaces n JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
            JOIN pg_catalog.pg_attribute b ON b.attrelid=c.oid AND b.attnum>0
            CROSS JOIN LATERAL pg_catalog.aclexplode(b.attacl) a
            UNION ALL
            SELECT n.nspname,'function',p.proname,a.*
            FROM namespaces n JOIN pg_catalog.pg_proc p ON p.pronamespace=n.oid
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
        )
        SELECT nspname,kind,object_name,pg_catalog.pg_get_userbyid(grantee),
               privilege_type,is_grantable,pg_catalog.pg_get_userbyid(grantor)
        FROM rights WHERE grantee<>(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:owner)
    """, owner=owner).all()
    if (any(grantable or grantor != owner for *_, grantable, grantor in rows)
            or {tuple(row[:5]) for row in rows} != expected
            or len(rows) != len(expected)):
        raise PersistenceError("migration_target_invalid")
    for role in roles:
        if execute(conn, """
            SELECT pg_catalog.has_database_privilege(:role,current_database(),'CREATE,TEMPORARY')
              OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
                         WHERE pg_catalog.has_schema_privilege(:role,n.oid,'CREATE'))
        """, role=role).scalar_one():
            raise PersistenceError("migration_target_invalid")


def verify_inventory(conn, *, runtime_role, gateway_role, worker_role):
    """Verify the explicit 0004 catalog before enabling the profile."""
    from .context import execute
    from .errors import PersistenceError
    from .migration import _identity_target_inventory, _operator
    from .source_migration import EXPECTED_STRUCTURE_SHA256 as SOURCE_STRUCTURE_SHA256
    from .source_migration import structure_digest as source_structure_digest

    if execute(conn, "SELECT version_num FROM wl_pg.alembic_version").scalars().all() != [ingestion.REVISION]:
        raise PersistenceError("schema_unsupported")
    owner = _operator(conn)
    namespaces = execute(conn, """
        SELECT nspname,pg_catalog.pg_get_userbyid(nspowner)
        FROM pg_catalog.pg_namespace
        WHERE nspname NOT LIKE 'pg_%' AND nspname NOT IN ('information_schema','public')
    """).all()
    if {tuple(row) for row in namespaces} != {
        (name, owner) for name in ("wl_pg", "wl_identity", "wl_sources", "wl_ingestion")
    }:
        raise PersistenceError("migration_target_invalid")
    _identity_target_inventory(conn, "0002_identity")
    if (source_structure_digest(conn) != SOURCE_STRUCTURE_SHA256
            or _structure_digest(conn, runtime_role) != EXPECTED_STRUCTURE_SHA256):
        raise PersistenceError("migration_target_invalid")
    functions = verify_functions(conn)
    verify_grants(conn, runtime_role, gateway_role, worker_role)
    return {"schema_revision": ingestion.REVISION, "functions": functions}


def migrate_ingestion(database, runtime_role, gateway_role, worker_role, key_digest, catalog,
                      *, fault=None):
    """Install 0004 only on a verified and initialized predecessor."""
    import re
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import SQLAlchemyError

    from .context import execute
    from .errors import PersistenceError
    from .source_migration import _source_operator_lock
    from .source_migration import verify_inventory as verify_sources_inventory
    from ..data_sources.catalog_v1 import catalog_digest, validate_catalog

    if type(key_digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", key_digest):
        raise PersistenceError("invalid_config")
    validate_catalog(catalog)
    try:
        with database.engine.begin() as conn:
            owner, _ = _checked_roles(conn, (runtime_role, gateway_role, worker_role))
            execute(conn, "SELECT pg_catalog.pg_advisory_xact_lock(1950174004)")
            configuration = Config()
            configuration.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
            configuration.attributes.update(connection=conn, identity_key_digest=key_digest,
                                            ingestion_operator_roles=(runtime_role, owner),
                                            ingestion_fault=fault)
            if not execute(conn, "SELECT pg_catalog.to_regclass('wl_pg.alembic_version') IS NOT NULL").scalar_one():
                raise PersistenceError("schema_unsupported")
            revisions = execute(conn, "SELECT version_num FROM wl_pg.alembic_version").scalars().all()
            if revisions not in ([ingestion.PREDECESSOR], [ingestion.REVISION]):
                raise PersistenceError("schema_unsupported")
            _source_operator_lock(conn)
            state = execute(conn, """
                SELECT a.key_digest,st.ready,
                       a.bootstrap_closed AND u.id IS NOT NULL AS initialized
                FROM wl_identity.instance_auth_state a
                JOIN wl_pg.instance_state st ON st.id=a.id
                LEFT JOIN wl_identity.users u ON u.id=a.admin_user_id WHERE a.id=1
            """).mappings().one()
            if not state["ready"] or not state["initialized"]:
                raise PersistenceError("restore_required")
            if state["key_digest"] != key_digest:
                raise PersistenceError("invalid_config")
            if execute(conn, "SELECT digest FROM wl_sources.catalog_state WHERE id=1").scalar_one() != catalog_digest(catalog):
                raise PersistenceError("migration_target_invalid")
            if revisions == [ingestion.PREDECESSOR]:
                verify_sources_inventory(conn, runtime_role=runtime_role, gateway_role=gateway_role)
                if _structure_digest(conn, runtime_role, predecessor=True) != EXPECTED_PREDECESSOR_SHA256:
                    raise PersistenceError("migration_target_invalid")
                command.upgrade(configuration, ingestion.REVISION)
                grants(conn, runtime_role, gateway_role, worker_role)
                if fault is not None:
                    fault("after_grants")
            result = verify_inventory(conn, runtime_role=runtime_role, gateway_role=gateway_role,
                                      worker_role=worker_role)
            result["ready"] = execute(conn, "SELECT ready FROM wl_ingestion.instance_state WHERE id=1").scalar() is True
            if fault is not None:
                fault("before_commit")
        return result
    except SQLAlchemyError:
        raise PersistenceError("migration_target_invalid") from None
