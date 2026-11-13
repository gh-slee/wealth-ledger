"""Private, receipt-bound evidence for an explicit ingestion restore."""
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import ingestion_schema, source_schema
from .context import COUNTER_MAX, execute
from .errors import PersistenceError
from .ingestion_migration import EXPECTED_STRUCTURE_SHA256
from .source_migration import EXPECTED_STRUCTURE_SHA256 as SOURCES_STRUCTURE_SHA256


FORMAT = "kurafolio-ingestion-restore-v1"
MANIFEST_LIMIT = 16_384
DUMP_NAME = "ingestion.dump"
MANIFEST_NAME = "manifest.json"
RELATIONS = (
    *("wl_ingestion." + table for table in ingestion_schema.READ_TABLES),
    *("wl_pg." + table for table in ("tenant_roots", "portfolios", "issuers", "accounts",
                                    "connections", "instruments")),
    *("wl_sources." + table for table in source_schema.TABLES),
)
PROFILE = {
    "format": FORMAT,
    "revision": ingestion_schema.REVISION,
    "postgres_major": "18",
    "structure_sha256": EXPECTED_STRUCTURE_SHA256,
    "sources_structure_sha256": SOURCES_STRUCTURE_SHA256,
    "functions": "68",
    "initialized": True,
}


def _digest_token(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _counter(value):
    return (type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None
            and int(value) <= COUNTER_MAX)


def _unique_object(items):
    result = dict(items)
    if len(result) != len(items):
        raise ValueError()
    return result


def _canonical_manifest(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _manifest(raw, receipt):
    if not 0 < len(raw) <= MANIFEST_LIMIT or not _digest_token(receipt):
        raise PersistenceError("restore_required")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), receipt):
        raise PersistenceError("restore_required")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_object)
        if type(value) is not dict or set(value) != {*PROFILE, "dump_sha256", "incarnation",
                                                     "restore_epoch", "relations"}:
            raise ValueError()
        if any(type(value[key]) is not type(expected) or value[key] != expected
               for key, expected in PROFILE.items()):
            raise ValueError()
        incarnation = uuid.UUID(value["incarnation"])
        if (not incarnation.int or str(incarnation) != value["incarnation"]
                or not _counter(value["restore_epoch"]) or not _digest_token(value["dump_sha256"])):
            raise ValueError()
        relations = value["relations"]
        if type(relations) is not dict or set(relations) != set(RELATIONS):
            raise ValueError()
        for evidence in relations.values():
            if (type(evidence) is not dict or set(evidence) != {"rows", "sha256"}
                    or not _counter(evidence["rows"]) or not _digest_token(evidence["sha256"])):
                raise ValueError()
        if raw != _canonical_manifest(value):
            raise ValueError()
    except (AttributeError, RecursionError, TypeError, ValueError):
        raise PersistenceError("restore_required") from None
    return value


@contextmanager
def _private_directory(path):
    # Walk with directory descriptors so neither the final directory nor a parent
    # component can be replaced by a symlink during verification.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    path = Path(os.path.abspath(path))
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise PersistenceError("invalid_config")
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _read_private(directory, name):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(name, flags, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()):
            raise PersistenceError("restore_required")
        yield stream


def _copy_digest(source, destination=None):
    digest = hashlib.sha256()
    while block := source.read(1024 * 1024):
        digest.update(block)
        if destination is not None:
            destination.write(block)
    return digest.hexdigest()


@contextmanager
def verified_archive(path, receipt):
    """Yield the authenticated manifest and a private copy of the exact archive."""
    try:
        with _private_directory(path) as directory:
            with _read_private(directory, MANIFEST_NAME) as stream:
                manifest = _manifest(stream.read(MANIFEST_LIMIT + 1), receipt)
            with _read_private(directory, DUMP_NAME) as archive, tempfile.TemporaryFile() as copy:
                if archive.read(5) != b"PGDMP":
                    raise PersistenceError("restore_required")
                archive.seek(0)
                digest = _copy_digest(archive, copy)
                if not hmac.compare_digest(digest, manifest["dump_sha256"]):
                    raise PersistenceError("restore_required")
                copy.seek(0)
                yield manifest, copy
    except OSError:
        raise PersistenceError("restore_required") from None


def _relation_evidence(conn):
    conn.exec_driver_sql("""
        SET LOCAL TimeZone TO 'UTC';
        SET LOCAL DateStyle TO 'ISO, YMD';
        SET LOCAL IntervalStyle TO 'postgres';
        SET LOCAL bytea_output TO 'hex';
        SET LOCAL extra_float_digits TO 3;
        SET LOCAL client_encoding TO 'UTF8'
    """)
    evidence = {}
    for relation in RELATIONS:
        keys = execute(conn, """
            SELECT pg_catalog.quote_ident(a.attname) ||
                   CASE WHEN a.attcollation <> 0 THEN ' COLLATE pg_catalog."C"' ELSE '' END
            FROM pg_catalog.pg_index i
            CROSS JOIN LATERAL pg_catalog.unnest(i.indkey) WITH ORDINALITY AS k(attnum, ordinal)
            JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
            WHERE i.indrelid = pg_catalog.to_regclass(:relation) AND i.indisprimary
              AND k.ordinal <= i.indnkeyatts
            ORDER BY k.ordinal
        """, relation=relation).scalars().all()
        if not keys:
            raise PersistenceError("restore_required")
        digest = hashlib.sha256(f"{FORMAT}\0{relation}\0".encode("ascii"))
        rows = 0
        with conn.connection.driver_connection.cursor(name="wl_ingestion_restore_rows") as cursor:
            cursor.itersize = 1
            cursor.execute(f"SELECT pg_catalog.to_jsonb(t)::text FROM {relation} AS t ORDER BY {', '.join(keys)}")
            for (value,) in cursor:
                encoded = value.encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
                rows += 1
        evidence[relation] = {"rows": str(rows), "sha256": digest.hexdigest()}
    return evidence


def _publish_backup(path, archive, manifest):
    raw = _canonical_manifest(manifest)
    receipt = hashlib.sha256(raw).hexdigest()
    _manifest(raw, receipt)
    # A private staging directory holds fully written files. Hard-linking each
    # staged file publishes only complete bytes, with no overwrite race.
    try:
        with _private_directory(path) as directory:
            staged = ".backup-" + uuid.uuid4().hex
            os.mkdir(staged, mode=0o700, dir_fd=directory)
            staging = os.open(staged, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            published = []
            try:
                for name in (DUMP_NAME, MANIFEST_NAME):
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                    with os.fdopen(os.open(name, flags, 0o600, dir_fd=staging), "wb") as output:
                        if name == DUMP_NAME:
                            archive.seek(0)
                            shutil.copyfileobj(archive, output, length=1024 * 1024)
                        else:
                            output.write(raw)
                        output.flush()
                        os.fsync(output.fileno())
                for name in (DUMP_NAME, MANIFEST_NAME):
                    os.link(name, name, src_dir_fd=staging, dst_dir_fd=directory, follow_symlinks=False)
                    published.append(name)
                os.fsync(directory)
            except OSError:
                for name in published:
                    os.unlink(name, dir_fd=directory)
                raise
            finally:
                for name in (DUMP_NAME, MANIFEST_NAME):
                    try:
                        os.unlink(name, dir_fd=staging)
                    except FileNotFoundError:
                        pass
                os.close(staging)
                os.rmdir(staged, dir_fd=directory)
    except OSError:
        raise PersistenceError("private_export_failed") from None
    return receipt


def _pg_tool(config, conn, name, options, *, stdin=None, stdout=None):
    import subprocess
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.pq import Conninfo

    connection = conninfo_to_dict(config.conninfo)
    environment_names = {item.keyword.decode(): item.envvar.decode()
                         for item in Conninfo.get_defaults() if item.envvar}
    if (not connection.keys() <= environment_names.keys() or "service" in connection
            or any("," in connection.get(key, "") for key in ("host", "hostaddr", "port"))):
        raise PersistenceError("invalid_config")
    pgconn = conn.connection.driver_connection.pgconn
    address = pgconn.hostaddr.decode()
    if address:
        connection["hostaddr"] = address
        connection["port"] = pgconn.port.decode()
    elif not connection.get("host", "").startswith("/") or connection.get("hostaddr"):
        # Require an explicit socket directory for a Unix connection.
        raise PersistenceError("invalid_config")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update({environment_names[key]: value for key, value in connection.items()})
    environment["PGCLIENTENCODING"] = "UTF8"
    environment["LC_ALL"] = "C"
    try:
        executable = shutil.which(name)
        if executable is None:
            raise PersistenceError("restore_required")
        version = subprocess.run([executable, "--version"], env=environment, check=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        if re.match(rb"^pg_(?:dump|restore) \(PostgreSQL\) 18(?:[.\s]|$)", version.stdout) is None:
            raise PersistenceError("schema_unsupported")
        subprocess.run([executable, "--no-password", *options], env=environment, check=True,
                       stdin=stdin if stdin is not None else subprocess.DEVNULL,
                       stdout=stdout if stdout is not None else subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=1800)
    except (OSError, subprocess.SubprocessError):
        raise PersistenceError("restore_required") from None


def _initialized_realm(conn):
    state = execute(conn, """
        SELECT p.incarnation, p.restore_epoch, a.last_observed_at
        FROM wl_pg.instance_state p
        JOIN wl_identity.instance_auth_state a ON a.id = p.id
        JOIN wl_identity.users u ON u.id = a.admin_user_id
        WHERE p.id = 1 AND a.bootstrap_closed
          AND p.incarnation <> '00000000-0000-0000-0000-000000000000'
    """).mappings().one_or_none()
    if state is None:
        raise PersistenceError("restore_required")
    return state


def _utf8(conn):
    if execute(conn, "SHOW server_encoding").scalar_one() != "UTF8":
        raise PersistenceError("schema_unsupported")


def backup_ingestion(config, path, roles):
    """Capture the dump and manifest from the same read-only snapshot."""
    from sqlalchemy.exc import SQLAlchemyError
    from .context import Database
    from .ingestion_migration import verify_inventory
    database = Database(config)
    try:
        with tempfile.TemporaryFile() as archive:
            with database.engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
                execute(conn, "SET TRANSACTION READ ONLY")
                execute(conn, "SELECT pg_catalog.pg_advisory_xact_lock(1950174004)")
                _utf8(conn)
                verify_inventory(conn, **roles)
                state = _initialized_realm(conn)
                _verify_history(conn)
                snapshot = execute(conn, "SELECT pg_catalog.pg_export_snapshot()").scalar_one()
                _pg_tool(config, conn, "pg_dump", ["--format=custom", "--enable-row-security",
                                            "--snapshot=" + snapshot], stdout=archive)
                archive.seek(0)
                if archive.read(5) != b"PGDMP":
                    raise PersistenceError("restore_required")
                archive.seek(0)
                manifest = dict(PROFILE, dump_sha256=_copy_digest(archive),
                                incarnation=str(state["incarnation"]), restore_epoch=str(state["restore_epoch"]),
                                relations=_relation_evidence(conn))
            receipt = _publish_backup(path, archive, manifest)
        return {"manifest_sha256": receipt}
    except (OSError, SQLAlchemyError):
        raise PersistenceError("restore_required") from None
    finally:
        database.close()


def _verify_history(conn):
    # Check links that ordinary scoped foreign keys cannot express. Typed bytes
    # and their stored SHA-256 digests are also checked by the frozen constraints.
    broken = execute(conn, """
        SELECT EXISTS (
            SELECT 1 FROM wl_ingestion.accepted_plans p
            JOIN wl_ingestion.receipts r
              ON (r.tenant_id,r.portfolio_id,r.id) = (p.tenant_id,p.portfolio_id,p.receipt_id)
            WHERE r.operation_kind <> 'ACCEPT' OR r.accepted_plan_id IS DISTINCT FROM p.id
               OR r.plan_digest IS DISTINCT FROM p.digest OR r.preview_id IS DISTINCT FROM p.preview_id
            UNION ALL
            SELECT 1 FROM wl_ingestion.receipts r
            JOIN wl_ingestion.accepted_plans p
              ON (p.tenant_id,p.portfolio_id,p.id) = (r.tenant_id,r.portfolio_id,r.accepted_plan_id)
            WHERE p.receipt_id IS DISTINCT FROM r.id
            UNION ALL
            SELECT 1 FROM wl_ingestion.source_revisions r
            JOIN wl_ingestion.accepted_inputs i
              ON (i.tenant_id,i.portfolio_id,i.id) = (r.tenant_id,r.portfolio_id,r.input_id)
            WHERE r.typed_bytes IS DISTINCT FROM wl_ingestion._canonical_v1(
                CASE WHEN r.collection='membership'
                THEN pg_catalog.convert_from(i.canonical_bytes,'UTF8')::jsonb->'membership'
                ELSE pg_catalog.convert_from(i.canonical_bytes,'UTF8')::jsonb
                  ->r.collection->(r.local_id::integer) END)
            UNION ALL
            SELECT 1 FROM wl_ingestion.source_revisions r
            JOIN wl_ingestion.source_revisions p
              ON (p.tenant_id,p.portfolio_id,p.id) = (r.tenant_id,r.portfolio_id,r.parent_id)
            WHERE p.collection <> r.collection
            UNION ALL
            SELECT 1 FROM wl_ingestion.activity_heads h
            JOIN wl_ingestion.source_revisions r
              ON (r.tenant_id,r.portfolio_id,r.id) = (h.tenant_id,h.portfolio_id,h.revision_id)
            WHERE r.collection <> 'records' OR r.accepted_change NOT IN ('original','correction','void')
               OR h.active <> (r.accepted_change <> 'void')
               OR pg_catalog.convert_from(r.typed_bytes,'UTF8')::jsonb->>'record_type' IS DISTINCT FROM 'activity'
            UNION ALL
            SELECT 1 FROM wl_ingestion.snapshot_heads h
            JOIN wl_ingestion.source_revisions r
              ON r.tenant_id=h.tenant_id AND r.portfolio_id=h.portfolio_id
                 AND r.id IN (h.latest_revision_id,h.complete_base_revision_id)
            WHERE r.collection <> 'snapshots' OR r.accepted_change NOT IN ('original','correction')
            UNION ALL
            SELECT 1 FROM wl_ingestion.lineage l
            JOIN wl_ingestion.accepted_inputs i
              ON (i.tenant_id,i.portfolio_id,i.id) = (l.tenant_id,l.portfolio_id,l.input_id)
            WHERE i.raw_digest <> l.raw_digest OR i.installation_id <> l.installation_id
               OR l.evidence_digest IS DISTINCT FROM pg_catalog.encode(pg_catalog.sha256(
                   wl_ingestion._canonical_v1(CASE WHEN l.collection='membership'
                   THEN pg_catalog.convert_from(i.canonical_bytes,'UTF8')::jsonb->'membership'
                   ELSE pg_catalog.convert_from(i.canonical_bytes,'UTF8')::jsonb
                     ->l.collection->(l.local_id::integer) END)), 'hex')
            UNION ALL
            SELECT 1 FROM wl_ingestion.outbox o
            JOIN wl_ingestion.receipts r
              ON (r.tenant_id,r.portfolio_id,r.id) = (o.tenant_id,o.portfolio_id,o.receipt_id)
            WHERE o.plan_digest IS DISTINCT FROM r.plan_digest
        )
    """).scalar_one()
    if broken:
        raise PersistenceError("restore_required")
    cyclic = execute(conn, """
        WITH RECURSIVE ancestry(tenant_id, portfolio_id, id, parent_id) AS (
            SELECT tenant_id,portfolio_id,id,parent_id FROM wl_ingestion.source_revisions
            WHERE parent_id IS NULL
            UNION ALL
            SELECT r.tenant_id,r.portfolio_id,r.id,r.parent_id FROM wl_ingestion.source_revisions r
            JOIN ancestry p ON (r.tenant_id,r.portfolio_id,r.parent_id)=(p.tenant_id,p.portfolio_id,p.id)
        )
        SELECT (SELECT count(*) FROM ancestry) <> (SELECT count(*) FROM wl_ingestion.source_revisions)
    """).scalar_one()
    if cyclic:
        raise PersistenceError("restore_required")


def _target_fence(conn):
    """Only the database owner and separately trusted cluster admins may connect."""
    secure = execute(conn, """
        SELECT d.datdba = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)
          AND current_user = session_user
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.aclexplode(
                COALESCE(d.datacl, pg_catalog.acldefault('d',d.datdba))
              ) AS a WHERE a.grantee=0 AND a.privilege_type='CONNECT'
          )
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_roles r
              WHERE r.rolcanlogin AND NOT r.rolsuper AND r.rolname <> current_user
                AND pg_catalog.has_database_privilege(r.oid, d.oid, 'CONNECT')
          )
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_stat_activity a
              WHERE a.datid = d.oid AND a.pid <> pg_catalog.pg_backend_pid()
          )
        FROM pg_catalog.pg_database d WHERE d.datname = pg_catalog.current_database()
    """).scalar_one()
    if not secure:
        raise PersistenceError("restore_required")


def _empty_target(conn):
    # pg_catalog and information_schema are the only server-managed namespaces
    # in a new template0 database other than public and pg_toast.
    empty = execute(conn, """
        SELECT NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_namespace
            WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast','public')
        ) AND NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_depend d
            WHERE d.refclassid = 'pg_catalog.pg_namespace'::regclass
              AND d.refobjid = 'public'::regnamespace
        ) AND NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'
        ) AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_largeobject_metadata)
          AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_event_trigger)
          AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_publication)
          AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_subscription WHERE subdbid = (
                SELECT oid FROM pg_catalog.pg_database WHERE datname = pg_catalog.current_database()))
          AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_foreign_server)
    """).scalar_one()
    if not empty:
        raise PersistenceError("restore_required")
    execute(conn, "ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")
    # Refuse other creation defaults, including any ACL that would leak during
    # archive load. PostgreSQL stores global defaults per database.
    defaults = execute(conn, """
        SELECT defaclrole = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)
          AND defaclnamespace = 0 AND defaclobjtype = 'f'
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.aclexplode(defaclacl) a
              WHERE a.grantee <> defaclrole OR a.grantor <> defaclrole
          ) AS restricted
        FROM pg_catalog.pg_default_acl
    """).scalars().all()
    if defaults != [True]:
        raise PersistenceError("restore_required")


def _fence_authority(conn, state, fault):
    if state["restore_epoch"] >= COUNTER_MAX:
        raise PersistenceError("counter_exhausted")
    now = execute(conn, "SELECT wl_identity._clock_timestamp_v1()").scalar_one()
    if now < state["last_observed_at"] or not execute(
        conn, "SELECT pg_catalog.isfinite(:instant)", instant=now
    ).scalar_one():
        raise PersistenceError("restore_required")

    execute(conn, "UPDATE wl_identity.sessions SET revoked = true WHERE NOT revoked")
    execute(conn, """UPDATE wl_identity.invites SET status='revoked', revocation_reason='restore'
                     WHERE status='issued'""")
    execute(conn, "UPDATE wl_identity.setup_codes SET status='revoked' WHERE status='issued'")
    if execute(conn, """
        SELECT EXISTS (SELECT 1 FROM wl_pg.jobs WHERE status='running' AND fencing_token=:maximum)
    """, maximum=COUNTER_MAX).scalar_one():
        raise PersistenceError("counter_exhausted")
    execute(conn, """
        UPDATE wl_pg.jobs j SET fencing_token=fencing_token+1,worker_id=NULL,lease_expires_at=NULL,
          status=CASE WHEN EXISTS (
            SELECT 1 FROM wl_pg.job_effect_receipts r
            WHERE (r.tenant_id,r.portfolio_id,r.job_id)=(j.tenant_id,j.portfolio_id,j.id)
          ) THEN 'succeeded' WHEN attempt>=max_attempts THEN 'failed' ELSE 'queued' END
        WHERE status='running'
    """)
    if fault is not None:
        fault("after_identity_invalidation")
    execute(conn, """
        UPDATE wl_ingestion.leases SET state='cancelled' WHERE state IN ('offered','active')
    """)
    execute(conn, "UPDATE wl_ingestion.workers SET enabled=false WHERE enabled")
    # The transition trigger decides expiry against the DB clock. If a set
    # crosses its deadline mid-statement, the entire attempt rolls back safely.
    execute(conn, """
        UPDATE wl_ingestion.sets
        SET state = CASE WHEN expires_at <= :instant THEN 'EXPIRED' ELSE 'CANCELLED' END,
            revision = revision + CASE WHEN expires_at <= :instant THEN 0 ELSE 1 END,
            cleanup_state = 'pending', prepare_session_digest = NULL, prepare_credential_version = NULL
        WHERE state NOT IN ('COMMITTED','REJECTED','CANCELLED','EXPIRED')
    """, instant=now)
    execute(conn, """
        UPDATE wl_ingestion.members m SET state=pg_catalog.lower(s.state)
        FROM wl_ingestion.sets s
        WHERE (s.tenant_id,s.portfolio_id,s.id)=(m.tenant_id,m.portfolio_id,m.set_id)
          AND s.state IN ('CANCELLED','EXPIRED')
          AND m.state NOT IN ('committed','rejected','cancelled','expired')
    """)
    # A raw slot may outlive this transaction. _purge_v1 releases only the
    # storage reservation for transient payload, and leaves raw accounting.
    pending = execute(conn, """
        SELECT tenant_id,portfolio_id,id FROM wl_ingestion.sets
        WHERE cleanup_state IN ('pending','failed')
        ORDER BY tenant_id,portfolio_id,id
    """)
    for tenant, portfolio, set_id in pending:
        execute(conn, "SELECT wl_ingestion._purge_v1(:tenant,:portfolio,:set_id)",
                tenant=tenant, portfolio=portfolio, set_id=set_id)

    if execute(conn, """
        SELECT EXISTS(SELECT 1 FROM wl_ingestion.stages)
            OR EXISTS(SELECT 1 FROM wl_ingestion.decisions)
            OR EXISTS(SELECT 1 FROM wl_ingestion.previews)
            OR EXISTS(SELECT 1 FROM wl_ingestion.members WHERE context_bytes IS NOT NULL)
    """).scalar_one():
        raise PersistenceError("restore_required")

    incarnation = uuid.uuid4()
    execute(conn, """
        UPDATE wl_pg.instance_state SET incarnation=:incarnation, restore_epoch=restore_epoch+1 WHERE id=1
    """, incarnation=incarnation)
    execute(conn, "UPDATE wl_identity.instance_auth_state SET last_observed_at=:instant WHERE id=1", instant=now)
    execute(conn, """
        INSERT INTO wl_identity.auth_audit VALUES(:id,:instant,'restore_finalized',:incarnation,NULL)
    """, id=uuid.uuid4(), instant=now, incarnation=incarnation)
    if fault is not None:
        fault("after_restore_epoch")
    return incarnation


def _verify_quarantine(conn, incarnation, epoch):
    _target_fence(conn)
    intact = execute(conn, """
        SELECT NOT p.ready AND p.incarnation=:incarnation AND p.restore_epoch=:epoch
          AND NOT EXISTS (SELECT 1 FROM wl_ingestion.instance_state WHERE ready)
          AND NOT EXISTS (SELECT 1 FROM wl_identity.sessions WHERE NOT revoked)
          AND NOT EXISTS (SELECT 1 FROM wl_identity.invites WHERE status='issued')
          AND NOT EXISTS (SELECT 1 FROM wl_pg.jobs WHERE status='running')
          AND NOT EXISTS (SELECT 1 FROM wl_ingestion.workers WHERE enabled)
          AND NOT EXISTS (SELECT 1 FROM wl_ingestion.leases WHERE state IN ('offered','active'))
          AND NOT EXISTS (SELECT 1 FROM wl_ingestion.sets
                          WHERE state NOT IN ('COMMITTED','REJECTED','CANCELLED','EXPIRED'))
        FROM wl_pg.instance_state p WHERE id=1
    """, incarnation=incarnation, epoch=epoch).scalar_one()
    if not intact:
        raise PersistenceError("restore_required")


def restore_ingestion(config, path, receipt, roles, *, fault=None):
    """Load a checked archive into an operator-fenced empty database and quarantine it."""
    from sqlalchemy.exc import SQLAlchemyError
    from .context import Database
    from .ingestion_migration import _checked_roles, verify_inventory
    from .source_migration import _source_operator_lock

    database = Database(config)
    try:
        with verified_archive(path, receipt) as (manifest, archive), database.engine.connect() as conn:
            # Session locks span the separate pg_restore connection and both
            # database transactions. Release explicitly before pooling the session.
            with conn.begin():
                execute(conn, "SELECT pg_catalog.pg_advisory_lock(1950174004)")
            try:
                with conn.begin():
                    _checked_roles(conn, tuple(roles.values()))
                    _utf8(conn)
                    _target_fence(conn)
                    _empty_target(conn)
                with conn.begin():
                    _pg_tool(config, conn, "pg_restore", ["--dbname=" + _database_name(config), "--no-owner",
                                                         "--no-acl", "--single-transaction"], stdin=archive)
                if fault is not None:
                    fault("after_archive_load")
                with conn.begin():
                    _target_fence(conn)
                    verify_inventory(conn, **roles, quarantined=True)
                    _source_operator_lock(conn)
                    state = _initialized_realm(conn)
                    if (str(state["incarnation"]) != manifest["incarnation"]
                            or str(state["restore_epoch"]) != manifest["restore_epoch"]):
                        raise PersistenceError("restore_required")
                    execute(conn, "UPDATE wl_pg.instance_state SET ready=false WHERE id=1")
                    execute(conn, "UPDATE wl_ingestion.instance_state SET ready=false WHERE ready")
                    if _relation_evidence(conn) != manifest["relations"]:
                        raise PersistenceError("restore_required")
                    _verify_history(conn)
                    if fault is not None:
                        fault("after_restore_verification")
                    incarnation = _fence_authority(conn, state, fault)
                    if _relation_evidence(conn) != manifest["relations"]:
                        raise PersistenceError("restore_required")
                    epoch = state["restore_epoch"] + 1
                    execute(conn, "SET CONSTRAINTS ALL IMMEDIATE")
                    _verify_quarantine(conn, incarnation, epoch)
                    if fault is not None:
                        fault("before_restore_commit")
                with conn.begin():
                    _verify_quarantine(conn, incarnation, epoch)
                    verify_inventory(conn, **roles, quarantined=True)
            finally:
                with conn.begin():
                    execute(conn, "SELECT pg_catalog.pg_advisory_unlock(1950174004)")
    except (OSError, SQLAlchemyError):
        raise PersistenceError("restore_required") from None
    finally:
        database.close()
    return {"schema_revision": ingestion_schema.REVISION, "ready": False, "quarantined": True}


def _database_name(config):
    from psycopg.conninfo import conninfo_to_dict
    # Use the private libpq environment for connection settings. pg_restore
    # requires a nonempty dbname argument to select database mode. A conninfo
    # quoting helper ensures this value cannot be interpreted as a second DSN.
    from psycopg.conninfo import make_conninfo
    return make_conninfo(dbname=conninfo_to_dict(config.conninfo)["dbname"])
