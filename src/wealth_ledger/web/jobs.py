"""Durable user-visible jobs and immutable confirmation contracts, not queue truth."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid

from .storage import ID, WebError
from .uploads import BATCH_BYTES, get_upload, verified_upload

ACTIVE = ("queued", "running", "data_committed")
UNRESOLVED = (*ACTIVE, "report_failed", "interrupted", "needs_review")
PREVIEW_SECONDS = 24 * 3600


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def engine_fingerprint():
    from ..workspace import CODE_ROOT
    base = CODE_ROOT / "src/wealth_ledger"
    return digest([(path.relative_to(base).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
                   for path in sorted(base.rglob("*")) if path.suffix in {".py", ".json"} and path.is_file()])


def timestamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class Jobs:
    def __init__(self, store):
        self.store = store

    def get(self, portfolio_id, job_id, owner_id=1):
        self.store.portfolio(portfolio_id, owner_id)
        if not isinstance(job_id, str) or not ID.fullmatch(job_id):
            raise WebError(404, "not_found", "Job not found")
        with closing(self.store.connect()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=? AND portfolio_id=?", (job_id, portfolio_id)).fetchone()
        if not row:
            raise WebError(404, "not_found", "Job not found")
        return dict(row)

    def internal(self, job_id):
        if not isinstance(job_id, str) or not ID.fullmatch(job_id):
            raise ValueError("Invalid internal job ID")
        with closing(self.store.connect()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Unknown internal job")
        return dict(row)

    def list(self, portfolio_id, owner_id=1):
        self.store.portfolio(portfolio_id, owner_id)
        with closing(self.store.connect()) as conn:
            return [self.view(dict(row)) for row in conn.execute(
                "SELECT * FROM jobs WHERE portfolio_id=? ORDER BY created_at DESC,id LIMIT 100", (portfolio_id,))]

    @staticmethod
    def view(row):
        result = {key: row[key] for key in ("id", "kind", "status", "created_at", "updated_at", "execution_at",
                                           "preview_id", "core_operation_id", "error_code")}
        result["result"] = json.loads(row["result_json"]) if row["result_json"] else None
        return result

    def _existing(self, conn, portfolio_id, key, request_digest):
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
            raise WebError(422, "invalid_idempotency_key", "Supply an 8-128 character idempotency key")
        row = conn.execute("SELECT * FROM jobs WHERE portfolio_id=? AND idempotency_key=?", (portfolio_id, key)).fetchone()
        if row and row["request_digest"] != request_digest:
            raise WebError(409, "idempotency_conflict", "This key belongs to a different request")
        return dict(row) if row else None

    def _insert(self, conn, portfolio_id, kind, request, key, request_digest, *, preview=None, fingerprint=None, execution=None):
        if conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','data_committed')").fetchone()[0] >= 20:
            raise WebError(429, "job_capacity", "Job capacity is reached")
        identifier = uuid.uuid4().hex
        now = self.store.clock()
        operation = "OP-" + uuid.uuid4().hex if kind in {"update", "record"} else None
        conn.execute("""INSERT INTO jobs(id,portfolio_id,kind,status,request_json,request_digest,input_fingerprint,
            execution_at,idempotency_key,preview_id,core_operation_id,created_at,updated_at)
            VALUES(?,?,?,'queued',?,?,?,?,?,?,?,?,?)""", (identifier, portfolio_id, kind,
            json.dumps(request, sort_keys=True), request_digest, fingerprint, execution or timestamp(now),
            key, preview, operation, now, now))
        return dict(conn.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())

    def request_uploads(self, portfolio_id, identifiers, owner_id=1):
        rows = [get_upload(self.store, portfolio_id, identifier, owner_id) for identifier in identifiers]
        if len(identifiers) != len(set(identifiers)) or len(rows) > 5:
            raise WebError(422, "invalid_request", "Duplicate or excessive uploads")
        if sum(row["byte_size"] for row in rows) > BATCH_BYTES:
            raise WebError(413, "batch_too_large", "Evidence batch is too large")
        if any(row["kind"] == "cash_flows" for row in rows):
            raise WebError(422, "invalid_upload", "Use financial declarations for cash-flow CSVs")
        slots = [row["provider"] if row["kind"] == "csv" else row["kind"] for row in rows]
        if len(slots) != len(set(slots)):
            raise WebError(422, "ambiguous_batch", "Supply at most one file for each source or reference kind")
        for row in rows:
            verified_upload(self.store, row)
        return rows

    def preview(self, portfolio_id, request, key, owner_id=1):
        self.store.portfolio(portfolio_id, owner_id)
        request_digest = digest({"kind": "preview", "request": request})
        with self.store.transaction() as conn:
            existing = self._existing(conn, portfolio_id, key, request_digest)
            if existing:
                return existing
        rows = self.request_uploads(portfolio_id, request["upload_ids"], owner_id)
        if not rows and request.get("btc_balance") is None and not request.get("render_saved"):
            raise WebError(422, "invalid_request", "Supply evidence or an explicitly dated BTC total")
        request = {**request, "upload_hashes": {row["id"]: row["sha256"] for row in rows},
                   "engine_fingerprint": engine_fingerprint()}
        with self.store.transaction() as conn:
            existing = self._existing(conn, portfolio_id, key, request_digest)
            return existing or self._insert(conn, portfolio_id, "preview", request, key, request_digest)

    def record_preview(self, portfolio_id, declaration, key, owner_id=1):
        self.store.portfolio(portfolio_id, owner_id)
        request_digest = digest({"kind":"record_preview", "declaration":declaration})
        with self.store.transaction() as conn:
            existing = self._existing(conn, portfolio_id, key, request_digest)
            if existing:
                return existing
        request = {"declaration":declaration, "engine_fingerprint":engine_fingerprint()}
        if declaration["command"] == "cash_flow_upload":
            upload = get_upload(self.store, portfolio_id, declaration["upload_id"], owner_id)
            if upload["kind"] != "cash_flows":
                raise WebError(422,"invalid_upload","Select a cash-flow CSV")
            verified_upload(self.store, upload)
            request["upload_sha256"] = upload["sha256"]
        with self.store.transaction() as conn:
            existing = self._existing(conn, portfolio_id, key, request_digest)
            return existing or self._insert(conn, portfolio_id, "record_preview", request, key, request_digest)

    def confirm(self, portfolio_id, preview_id, key, owner_id=1, *, preview_kind="preview"):
        _, project = self.store.portfolio(portfolio_id, owner_id)
        kind = "record" if preview_kind == "record_preview" else "update"
        request_digest = digest({"kind": kind, "preview_id": preview_id})
        with self.store.transaction() as conn:
            existing = self._existing(conn, portfolio_id, key, request_digest)
            if existing:
                return existing
            preview = conn.execute("SELECT * FROM jobs WHERE id=? AND portfolio_id=? AND kind=?", (preview_id, portfolio_id, preview_kind)).fetchone()
            if not preview:
                raise WebError(404, "not_found", "Preview not found")
            if preview["status"] != "ready" or self.store.clock() - preview["created_at"] > PREVIEW_SECONDS:
                raise WebError(409, "preview_unavailable", "Run a new successful preview before confirmation")
            if conn.execute("SELECT 1 FROM jobs WHERE portfolio_id=? AND kind IN ('update','record') AND status IN (?,?,?,?,?,?)",
                            (portfolio_id, *UNRESOLVED)).fetchone():
                raise WebError(409, "portfolio_busy", "Resolve the existing update before submitting another")
            from ..operations import input_fingerprint
            if input_fingerprint(project) != preview["input_fingerprint"]:
                raise WebError(409, "stale_preview", "Portfolio inputs changed; run preview again")
            return self._insert(conn, portfolio_id, kind, json.loads(preview["request_json"]), key,
                                request_digest, preview=preview_id, fingerprint=preview["input_fingerprint"],
                                execution=preview["execution_at"])

    def claim(self, job_id):
        with self.store.transaction() as conn:
            return conn.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='queued'",
                                (self.store.clock(), job_id)).rowcount == 1

    def state(self, job_id, status, *, result=None, error=None, fingerprint=None):
        with self.store.transaction() as conn:
            conn.execute("UPDATE jobs SET status=?,result_json=?,error_code=?,updated_at=?,input_fingerprint=COALESCE(?,input_fingerprint) WHERE id=?",
                         (status, json.dumps(result) if result is not None else None, error,
                          self.store.clock(), fingerprint, job_id))

    def cancel(self, portfolio_id, job_id, owner_id=1):
        self.get(portfolio_id, job_id, owner_id)
        with self.store.transaction() as conn:
            if conn.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=? AND status='queued'",
                            (self.store.clock(), job_id)).rowcount != 1:
                raise WebError(409, "unsafe_cancellation", "Only queued work can be cancelled")
        return self.get(portfolio_id, job_id, owner_id)

    def resume(self, portfolio_id, job_id, owner_id=1):
        row = self.get(portfolio_id, job_id, owner_id)
        if row["kind"] != "update" or row["status"] not in {"report_failed", "data_committed"}:
            raise WebError(409, "unsafe_resume", "Only a proven committed report operation can resume")
        with self.store.transaction() as conn:
            if conn.execute("UPDATE jobs SET status='queued',error_code=NULL,enqueued_at=NULL,updated_at=? WHERE id=? AND status=?",
                            (self.store.clock(), job_id, row["status"])).rowcount != 1:
                raise WebError(409, "job_changed", "Job state changed")
        return self.get(portfolio_id, job_id, owner_id)

    def core_request(self, row):
        request = json.loads(row["request_json"])
        if request["engine_fingerprint"] != engine_fingerprint():
            raise WebError(409, "stale_engine", "Application changed; run preview again")
        uploads = self.request_uploads(row["portfolio_id"], request["upload_ids"])
        if {upload["id"]: upload["sha256"] for upload in uploads} != request["upload_hashes"]:
            raise WebError(409, "upload_integrity", "Preview upload scope changed")
        core = {key: value for key, value in request.items() if key not in {"upload_ids", "upload_hashes", "engine_fingerprint", "render_saved"} and value is not None}
        core["paths"] = []
        for upload in uploads:
            path = str(verified_upload(self.store, upload))
            if upload["kind"] == "csv":
                core["paths"].append(path)
            else:
                core[{"fx": "fx_file", "price": "price_file", "opening": "opening_file"}[upload["kind"]]] = path
        core["execution_at"] = row["execution_at"]
        return core
