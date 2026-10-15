"""Atomic staged input commits and durable two-phase report operations."""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
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
    """Serialize mutating CLI operations; never break an unknown owner's lock."""
    import os
    path = Path(project) / "work/update.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("x")
    except FileExistsError as exc:
        raise ValueError("Another update owns work/update.lock; inspect its PID before removing a stale lock") from exc
    try:
        handle.write(json.dumps({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}))
        handle.close()
        yield
    finally:
        path.unlink(missing_ok=True)


def fingerprint(project):
    """Only input revisions determine whether a saved report operation is stale."""
    db = _db(project)
    if not db.exists():
        return hashlib.sha256(b"empty").hexdigest()
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        names = {"sources", "accounts", "snapshots", "positions", "cash_flows", "flow_periods", "flow_coverage", "coverage_declarations"}
        values = []
        for name in sorted(tables):
            if name in names or name.startswith(("crypto_", "wallet_")):
                rows=sorted((tuple(r) for r in conn.execute(f'SELECT * FROM "{name}"')), key=repr)
                if rows:
                    values.append((name,rows))
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def atomic_data(project, action):
    """Run importers in an isolated database and install all rows atomically.

    Immutable source archives may survive a rejected batch, but none of its
    financial records enter the live database. Files retain relative paths.
    """
    project = Path(project).resolve()
    initialize(project)
    expected = fingerprint(project)
    directory = Path(tempfile.mkdtemp(prefix="input-stage-", dir=project / "work"))
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
    try:
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
                        shutil.copy2(path, destination)
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
        return result
    finally:
        shutil.rmtree(directory)


def start(project, request, *, data_only=False):
    op = "OP-" + uuid.uuid4().hex[:16]
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


def record_data_operation(project, request, action):
    """A data-only CLI command never advances valuation time or publishes."""
    from .settings import ensure_report_locale_setting
    ensure_report_locale_setting(project)
    op = start(project, request, data_only=True)
    try:
        result = atomic_data(project, action)
        set_state(project, op, "data_only_complete", result_json=json.dumps(result), fingerprint=fingerprint(project))
        return {"operation_id": op, "report_published": False, **result}
    except Exception as exc:
        set_state(project, op, "data_failed", error=str(exc))
        raise


class ReportOperationError(ValueError):
    """A committed input operation can be resumed without repeating observations."""


def execute_update(project, request, publisher, *, resume=None):
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
        request = {**request, "execution_at": datetime.now(timezone.utc).isoformat(),
                   "btc_cost_policy": btc_cost_policy(project, request.get("btc_cost_policy")),
                   "report_locale": selected_locale, "localization": locale_metadata}
        op = start(project, request)
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
            accepted = atomic_data(project, ingest)
            for key,relative in accepted.get('reference_overrides',{}).items():
                request[key]=str(project/relative)
            target = accepted["target"]
            set_state(project, op, "data_committed", request_json=json.dumps(request), result_json=json.dumps(accepted),
                      valuation_as_of=target, fingerprint=fingerprint(project))
        except Exception as exc:
            set_state(project, op, "data_failed", error=str(exc))
            raise
    try:
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
        raise ReportOperationError(f"資料已保存，報告未發布。Operation {op}; valuation {target}. "
                                  f"Retry: scripts/update.py --resume-operation {op}. Cause: {exc}") from exc
