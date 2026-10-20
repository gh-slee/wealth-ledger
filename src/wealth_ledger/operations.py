"""Atomic staged input commits and durable two-phase report operations."""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
import shlex
import sqlite3
import tempfile
import uuid

from .core import initialize


def _db(project):
    return Path(project) / "data/db/portfolio.sqlite3"


def _connection(project):
    initialize(project)
    conn = sqlite3.connect(_db(project))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS update_operations(
        operation_id TEXT PRIMARY KEY, status TEXT NOT NULL, request_json TEXT NOT NULL,
        result_json TEXT, valuation_as_of TEXT, fingerprint TEXT, output_json TEXT,
        error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.commit()
    return conn


@contextmanager
def project_lock(project):
    """Kernel ownership spans CLI/containers; unknown legacy locks fail closed."""
    import os
    from .locking import file_lock
    path = Path(project) / "work/update.lock"
    from .web.maintenance import workspace_activity
    with workspace_activity(project), file_lock(path.with_name("update.guard")):
        if path.is_symlink():
            raise ValueError("Unsafe update lock path")
        if path.exists():
            try:
                old = json.loads(path.read_text())
                if old.get("lock_protocol") != 2 or not isinstance(old.get("token"), str):
                    raise ValueError("Unknown lock owner")
            except (ValueError, AttributeError) as exc:
                raise ValueError("Unknown legacy work/update.lock; review it locally before removal") from exc
            # Acquiring the stable kernel guard proves a protocol-2 owner is gone.
            path.unlink()
        token = uuid.uuid4().hex
        path.write_text(json.dumps({"lock_protocol": 2, "token": token, "pid": os.getpid(),
                                    "started_at": datetime.now(timezone.utc).isoformat()}))
        try:
            yield
        finally:
            if path.exists() and not path.is_symlink():
                try:
                    if json.loads(path.read_text()).get("token") == token:
                        path.unlink()
                except (ValueError, AttributeError):
                    pass


def fingerprint(project):
    """Only input revisions determine whether a saved report operation is stale."""
    db = _db(project)
    if not db.exists():
        return hashlib.sha256(b"empty").hexdigest()
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        names = {"sources", "accounts", "snapshots", "positions", "cash_flows", "manual_cash_flows", "flow_periods", "flow_coverage", "coverage_declarations", "source_report_observations"}
        values = []
        for name in sorted(tables):
            if name in names or name.startswith(("crypto_", "wallet_", "src_")):
                rows=sorted((tuple(r) for r in conn.execute(f'SELECT * FROM "{name}"')), key=repr)
                if rows:
                    values.append((name,rows))
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def input_fingerprint(project):
    """Financial revisions plus configuration/reference/cutoff inputs for previews."""
    project = Path(project)
    evidence = []
    for name in ("config", "data/fx", "data/prices"):
        for path in sorted((project / name).rglob("*")):
            if path.is_file():
                if path.is_symlink():
                    raise ValueError("Input evidence cannot be a symlink")
                evidence.append((path.relative_to(project).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    pointer = project / "reports/latest.json"
    if pointer.exists():
        evidence.append(("reports/latest.json", hashlib.sha256(pointer.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps([fingerprint(project), evidence], sort_keys=True).encode()).hexdigest()


def _install_evidence(source, destination):
    """Never expose a partially copied immutable file after an interrupted write."""
    descriptor, name = tempfile.mkstemp(prefix=".evidence-", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_data(project, action, *, finalize=None):
    """Run importers in an isolated database and install all rows atomically.

    Immutable source archives may survive a rejected batch, but none of its
    financial records enter the live database. Files retain relative paths.
    """
    project = Path(project).resolve()
    initialize(project)
    expected = fingerprint(project)
    directory = Path(tempfile.mkdtemp(prefix="input-stage-", dir=project / "work"))
    try:
        stage = directory / "project"
        (stage / "data/db").mkdir(parents=True)
        (stage / "work").mkdir()
        for child in (project / "data").iterdir():
            if child.name != "db":
                destination = stage / "data" / child.name
                if child.is_dir():
                    shutil.copytree(child, destination)
                else:
                    shutil.copy2(child, destination)
        if (project / "config").exists():
            shutil.copytree(project / "config", stage / "config")
        with closing(sqlite3.connect(_db(project))) as source, closing(sqlite3.connect(_db(stage))) as target:
            source.backup(target)
        result = action(stage)
        with closing(sqlite3.connect(_db(project))) as conn, conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("ATTACH DATABASE ? AS candidate", (str(_db(stage)),))
            conn.execute("BEGIN IMMEDIATE")
            if fingerprint(project) != expected:
                raise ValueError("Inputs changed concurrently; retry this batch against current data")
            for path in (stage / "data").rglob("*"):
                relative = path.relative_to(stage)
                if path.is_file() and relative.parts[1] != "db":
                    destination = project / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists() and destination.read_bytes() != path.read_bytes():
                        raise ValueError(f"Immutable input/cache collision: {relative}")
                    if not destination.exists():
                        _install_evidence(path, destination)
            conn.execute("PRAGMA defer_foreign_keys=ON")
            schema = conn.execute("SELECT name,sql FROM candidate.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            for name, sql in schema:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone():
                    conn.execute(sql)
            for name, sql in reversed(schema):
                quoted = '"' + name.replace('"', '""') + '"'
                if name == "update_operations":
                    continue
                conn.execute(f"DELETE FROM main.{quoted}")
            for name, sql in schema:
                quoted = '"' + name.replace('"', '""') + '"'
                if name == "update_operations":
                    continue
                conn.execute(f"INSERT INTO main.{quoted} SELECT * FROM candidate.{quoted}")
            for name, sql in conn.execute("SELECT name,sql FROM candidate.sqlite_master WHERE type='index' AND sql IS NOT NULL"):
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                    conn.execute(sql)
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Staged input foreign-key validation failed")
            if finalize is not None:
                finalize(conn, result, fingerprint(stage))
        return result
    finally:
        shutil.rmtree(directory)


def start(project, request, *, data_only=False, operation_id=None):
    op = operation_id or "OP-" + uuid.uuid4().hex[:16]
    import re
    if not re.fullmatch(r"OP-[a-f0-9]{16,32}", op):
        raise ValueError("Invalid operation ID")
    now = datetime.now(timezone.utc).isoformat()
    with _connection(project) as conn:
        conn.execute("INSERT INTO update_operations(operation_id,status,request_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                     (op, "data_started" if data_only else "started", json.dumps(request, default=str), now, now))
    return op


def set_state(project, operation_id, status, **values):
    allowed = {"request_json", "result_json", "valuation_as_of", "fingerprint", "output_json", "error"}
    if any(k not in allowed for k in values):
        raise ValueError("Unknown operation state field")
    fields = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **values}
    with _connection(project) as conn:
        conn.execute("UPDATE update_operations SET " + ",".join(k + "=?" for k in fields) + " WHERE operation_id=?", (*fields.values(), operation_id))


def get(project, operation_id):
    rows = list_operations(project)
    row = next((r for r in rows if r["operation_id"] == operation_id), None)
    if row is None:
        raise ValueError("Unknown operation ID")
    return row


def list_operations(project):
    db = _db(project)
    if not db.exists():
        return []
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='update_operations'").fetchone():
            return []
        result = [dict(r) for r in conn.execute("SELECT * FROM update_operations ORDER BY created_at DESC")]
    for row in result:
        for key in ("request_json", "result_json", "output_json"):
            row[key.removesuffix("_json")] = json.loads(row.pop(key)) if row[key] is not None else None
    return result


def record_data_operation(project, request, action, *, operation_id=None):
    """Commit data and its durable completion marker in the same transaction."""
    from .settings import ensure_report_locale_setting
    ensure_report_locale_setting(project)
    if operation_id:
        saved = next((row for row in list_operations(project) if row["operation_id"] == operation_id), None)
        if saved:
            if saved["request"] != json.loads(json.dumps(request, default=str)) or saved["status"] != "data_only_complete":
                raise ValueError("Existing data operation requires review")
            return {"operation_id": operation_id, "report_published": False, **saved["result"]}
    op = start(project, request, data_only=True, operation_id=operation_id)
    def complete(conn, result, value):
        conn.execute("UPDATE update_operations SET status='data_only_complete',result_json=?,fingerprint=?,updated_at=? WHERE operation_id=?",
                     (json.dumps(result), value, datetime.now(timezone.utc).isoformat(), op))
    try:
        result = atomic_data(project, action, finalize=complete)
        return {"operation_id": op, "report_published": False, **result}
    except Exception as exc:
        # Cleanup/delivery can fail after the data and completion marker committed.
        # A durable receipt must never be downgraded into a retryable failed write.
        with closing(_connection(project)) as conn, conn:
            conn.execute("""UPDATE update_operations SET status='data_failed',error=?,updated_at=?
                WHERE operation_id=? AND status!='data_only_complete'""",
                (str(exc),datetime.now(timezone.utc).isoformat(),op))
        raise


class ReportOperationError(ValueError):
    """A committed input operation can be resumed without repeating observations."""


def execute_update(project, request, publisher, *, resume=None, operation_id=None, on_data_committed=None):
    from .workflow import ingest_inputs, select_context, prepare_update
    from .prices import parse_time
    project = Path(project)
    if resume:
        saved = get(project, resume)
        if saved["status"] == "published":
            return {"operation_id": resume, "status": "already_published", **saved["output"]}
        if saved["status"] not in ("data_committed", "report_failed"):
            raise ValueError("This operation has no committed report inputs to resume")
        if fingerprint(project) != saved["fingerprint"]:
            set_state(project, resume, "stale", error="Input revisions changed; generate a new report from current data")
            raise ValueError("Operation is stale: input revisions changed; generate a new report from current data")
        from .publishing import recover_publication
        recovered = recover_publication(project, resume)
        if recovered is not None:
            set_state(project, resume, "published", output_json=json.dumps(recovered), error=None)
            return {"operation_id": resume, "status": "published", **recovered}
        op, request, accepted = resume, saved["request"], saved["result"]
        for key,relative in accepted.get('reference_overrides',{}).items():
            request[key]=str(project/relative)
        target = saved["valuation_as_of"]
    else:
        from .settings import btc_cost_policy, report_locale, ensure_report_locale_setting
        from .i18n import presentation_context, validate_catalogs
        validate_catalogs()
        selected_locale = report_locale(project, request.get("report_locale"))
        with presentation_context(selected_locale) as presentation:
            locale_metadata = presentation.metadata()
        ensure_report_locale_setting(project)
        request = {**request, "execution_at": parse_time(request["execution_at"]).isoformat() if request.get("execution_at") else datetime.now(timezone.utc).isoformat(),
                   "btc_cost_policy": btc_cost_policy(project, request.get("btc_cost_policy")),
                   "report_locale": selected_locale, "localization": locale_metadata}
        op = start(project, request, operation_id=operation_id)
        try:
            def ingest(stage):
                overrides={}
                local_request=dict(request)
                for key in ('fx_file','opening_file','price_file'):
                    if request.get(key):
                        path=Path(request[key]).expanduser().resolve()
                        raw=path.read_bytes()
                        json.loads(raw)
                        digest=hashlib.sha256(raw).hexdigest()
                        destination=stage/'data/raw/reference'/datetime.now(timezone.utc).strftime('%Y/%m')/f'{key}-{digest}.json'
                        destination.parent.mkdir(parents=True,exist_ok=True)
                        if destination.exists() and destination.read_bytes()!=raw:
                            raise ValueError('Reference override archive collision')
                        if not destination.exists():
                            destination.write_bytes(raw)
                        destination.chmod(0o400)
                        overrides[key]=str(destination.relative_to(stage))
                        local_request[key]=str(destination)
                accepted = ingest_inputs(stage, request.get("paths", []),
                    kind=request.get("kind", "monthly"), fx_file=local_request.get("fx_file"),
                    opening_file=local_request.get("opening_file"), btc_balance=request.get("btc_balance"),
                    btc_balance_as_of=request.get("btc_balance_as_of"),
                    btc_balance_source=request.get("btc_balance_source"), now=parse_time(request["execution_at"]))
                context = select_context(stage, accepted, snapshot_id=request.get("snapshot_id"),
                    as_of=request.get("as_of"), now=parse_time(request["execution_at"]))
                if request.get("wealthsimple_only"):
                    if context["base"] is None:
                        raise ValueError("No Wealthsimple holdings for brokerage-only report")
                    context["target"] = context["base"]["meta"]["as_of"]
                if local_request.get('price_file'):
                    from .prices import validate_quote
                    try:
                        value=json.loads(Path(local_request['price_file']).read_bytes())
                        validate_quote(value,context['target'])
                        if not value.get('evidence_sha256'):
                            raise ValueError('Verified BTC quote requires an evidence reference hash')
                    except (KeyError,TypeError) as exc:
                        raise ValueError('Invalid verified BTC quote JSON fields') from exc
                if local_request.get('fx_file'):
                    from .fx import validate_rates
                    from .workflow import LOCAL
                    try:
                        validate_rates(json.loads(Path(local_request['fx_file']).read_bytes()),parse_time(context['target']).astimezone(LOCAL).date().isoformat())
                    except (KeyError,TypeError) as exc:
                        raise ValueError('Invalid verified FX JSON fields') from exc
                accepted["selected_snapshot_id"] = context["selected"]
                accepted["has_crypto"] = context["has_crypto"]
                accepted["target"] = context["target"]
                accepted['reference_overrides']=overrides
                return accepted
            def commit_marker(conn, accepted, digest):
                saved_request = dict(request)
                for key, relative in accepted.get("reference_overrides", {}).items():
                    saved_request[key] = str(project / relative)
                conn.execute("""UPDATE update_operations SET status='data_committed',
                    request_json=?,result_json=?,valuation_as_of=?,fingerprint=?,updated_at=?
                    WHERE operation_id=?""", (json.dumps(saved_request), json.dumps(accepted),
                    accepted["target"], digest, datetime.now(timezone.utc).isoformat(), op))
            accepted = atomic_data(project, ingest, finalize=commit_marker)
            for key,relative in accepted.get('reference_overrides',{}).items():
                request[key]=str(project/relative)
            target = accepted["target"]
        except Exception as exc:
            # Cleanup can fail after the transaction commits. Never overwrite its
            # durable marker with a claim that no data was committed.
            if get(project, op)["status"] != "data_committed":
                set_state(project, op, "data_failed", error=str(exc))
            raise
    try:
        if on_data_committed is not None:
            on_data_committed(op)
        from .i18n import presentation_context, LEGACY_LOCALE
        selected_locale = request.get("report_locale", LEGACY_LOCALE)
        with presentation_context(selected_locale) as presentation:
            if request.get("localization") and presentation.metadata() != request["localization"]:
                raise ValueError("The saved operation translation catalog changed; render a new edition from committed inputs")
        payload, result = prepare_update(project, accepted=accepted,
            snapshot_id=accepted.get("selected_snapshot_id"),
            fx_file=request.get("fx_file"), price_file=request.get("price_file"),
            as_of=target if accepted.get("has_crypto") and not request.get("wealthsimple_only") else None,
            wealthsimple_only=request.get("wealthsimple_only", False), now=parse_time(request["execution_at"]),
            btc_cost_policy=request.get("btc_cost_policy"))
        payload["reporting"] = {"locale": selected_locale, "localization": presentation.metadata()}
        result["operation_id"] = op
        output = publisher(payload, result, request.get("lookthrough_run_id"))
        set_state(project, op, "published", output_json=json.dumps(output, default=str), error=None,
                  fingerprint=fingerprint(project))
        return {"operation_id": op, "status": "published", **output}
    except Exception as exc:
        set_state(project, op, "report_failed", error=str(exc), fingerprint=fingerprint(project))
        from .i18n import tr
        retry = shlex.join(['scripts/update.py', '--workspace', str(project.resolve()), '--resume-operation', op])
        with presentation_context(selected_locale):
            message = tr("cli.operation_retry.workspace", operation=op, valuation=target, retry=retry, cause=str(exc))
        raise ReportOperationError(message) from exc
