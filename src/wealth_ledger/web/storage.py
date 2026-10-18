"""Versioned Web metadata and bounded filesystem access, separate from ledgers."""
from __future__ import annotations

from contextlib import closing, contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import sqlite3
import time
import uuid

from .config import WebSettings

SCHEMA_VERSION = 2
ID = re.compile(r"^[a-f0-9]{32}$")
ARTIFACT_TYPES = {".pdf": "application/pdf", ".ods": "application/vnd.oasis.opendocument.spreadsheet",
                  ".md": "text/markdown; charset=utf-8", ".json": "application/json",
                  ".csv": "text/csv; charset=utf-8", ".png": "image/png"}
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


class WebError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


def contained(root, relative):
    """Registry paths are relative, bounded and never follow symlinks."""
    if not isinstance(relative, str) or "\\" in relative or any(ord(c) < 32 for c in relative):
        raise WebError(404, "not_found", "Resource not found")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or ".." in parts.parts or "." in relative.split("/"):
        raise WebError(404, "not_found", "Resource not found")
    root = Path(root)
    path = root
    for component in parts.parts:
        path /= component
        if path.is_symlink():
            raise WebError(404, "not_found", "Resource not found")
    if not path.resolve().is_relative_to(root.resolve()):
        raise WebError(404, "not_found", "Resource not found")
    return path


def private_write(path, raw):
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_instance(settings: WebSettings):
    """Trusted CLI only: initialize a dedicated empty instance or migrate metadata."""
    root = settings.data_root
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "admin/instance.json"
    if not marker.exists() and any(root.iterdir()):
        raise ValueError("New Web instances require an empty data directory; use explicit adoption later")
    root.chmod(0o700)
    for name in ("admin", "secrets", "portfolios", "uploads", "cache"):
        path = contained(root, name)
        path.mkdir(exist_ok=True, mode=0o700)
    existing_instance = marker.exists()
    if existing_instance:
        if json.loads(contained(root, "admin/instance.json").read_text()) != {"schema_version": 1}:
            raise ValueError("Unsupported Web instance format")
    else:
        private_write(marker, b'{"schema_version":1}\n')
    key = contained(root, "secrets/csrf.key")
    if not key.exists():
        if existing_instance:
            raise ValueError("Instance secret is missing; restore it or explicitly reset the instance offline")
        descriptor = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    if len(key.read_bytes()) != 32:
        raise ValueError("Invalid instance CSRF key")
    db = contained(root, "admin/app.sqlite3")
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            raise ValueError("Unsupported Web metadata schema; do not downgrade")
        if version == 0:
            conn.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE owner(id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, credential_version INTEGER NOT NULL);
            CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('anonymous','authenticated')),
                owner_id INTEGER REFERENCES owner(id), credential_version INTEGER,
                created_at REAL NOT NULL, last_activity REAL NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE throttle(bucket TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL);
            CREATE TABLE portfolios(id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES owner(id),
                name TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE artifacts(id TEXT PRIMARY KEY, portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
                report_id TEXT NOT NULL, relative_path TEXT NOT NULL, sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL, media_type TEXT NOT NULL);
            PRAGMA user_version=1;
            COMMIT;
            """)
        if conn.execute("PRAGMA user_version").fetchone()[0] == 1:
            backups = contained(root, "admin/backups")
            backups.mkdir(exist_ok=True, mode=0o700)
            backup = backups / ("app-v1-" + uuid.uuid4().hex + ".sqlite3")
            temporary = backup.with_name("." + backup.name)
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
                with closing(sqlite3.connect(temporary)) as target:
                    conn.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise ValueError("Metadata backup integrity verification failed")
                with temporary.open("rb") as stream:
                    os.fsync(stream.fileno())
                os.link(temporary, backup)
            finally:
                temporary.unlink(missing_ok=True)
            conn.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE uploads(id TEXT PRIMARY KEY, portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
                kind TEXT NOT NULL, provider TEXT, original_name TEXT NOT NULL,
                sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL, created_at REAL NOT NULL,
                UNIQUE(portfolio_id,kind,sha256));
            CREATE TABLE jobs(id TEXT PRIMARY KEY, portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
                kind TEXT NOT NULL, status TEXT NOT NULL, request_json TEXT NOT NULL,
                request_digest TEXT NOT NULL, input_fingerprint TEXT, execution_at TEXT NOT NULL,
                idempotency_key TEXT NOT NULL, preview_id TEXT REFERENCES jobs(id),
                core_operation_id TEXT UNIQUE, result_json TEXT, error_code TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL, enqueued_at REAL,
                UNIQUE(portfolio_id,idempotency_key));
            CREATE INDEX jobs_status ON jobs(status,created_at);
            PRAGMA user_version=2;
            COMMIT;
            """)
    db.chmod(0o600)


def upgrade_instance(settings, *, timeout=30):
    """Drain standard clients before upgrading only the Web metadata database."""
    from .maintenance import maintenance
    validate_identity(settings)
    with maintenance(settings.data_root, timeout=timeout, purpose="upgrade"):
        prepare_instance(settings)


def validate_identity(settings):
    """Identify an existing instance without requiring the current metadata schema."""
    root = settings.data_root
    marker = contained(root, "admin/instance.json")
    key = contained(root, "secrets/csrf.key")
    db = contained(root, "admin/app.sqlite3")
    if not marker.is_file() or not key.is_file() or not db.is_file():
        raise ValueError("Initialize an instance before performing maintenance")
    if json.loads(marker.read_text()) != {"schema_version": 1} or len(key.read_bytes()) != 32:
        raise ValueError("Invalid instance identity; review or restore it offline")


class Store:
    def __init__(self, settings: WebSettings, *, clock=time.time):
        self.settings, self.root, self.clock = settings, settings.data_root, clock
        self.db = contained(self.root, "admin/app.sqlite3")
        key = contained(self.root, "secrets/csrf.key")
        marker = contained(self.root, "admin/instance.json")
        if not self.db.is_file() or not key.is_file() or not marker.is_file():
            raise ValueError("Initialize the owner through the host CLI before serving")
        if json.loads(marker.read_text()) != {"schema_version": 1}:
            raise ValueError("Unsupported Web instance format")
        self.csrf_key = key.read_bytes()
        if len(self.csrf_key) != 32:
            raise ValueError("Invalid instance CSRF key")
        with closing(self.connect()) as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("Unsupported Web metadata schema; run the host initialization command")

    def connect(self):
        conn = sqlite3.connect(self.db.as_uri() + "?mode=rw", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def transaction(self):
        with closing(self.connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def owner(self):
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM owner WHERE id=1").fetchone()
            return dict(row) if row else None

    def set_owner(self, username, password_hash, *, reset=False):
        with self.transaction() as conn:
            existing = conn.execute("SELECT id FROM owner WHERE id=1").fetchone()
            if reset and existing:
                conn.execute("UPDATE owner SET password_hash=?,credential_version=credential_version+1 WHERE id=1", (password_hash,))
                conn.execute("DELETE FROM sessions")
                conn.execute("DELETE FROM throttle")
            elif not reset and not existing:
                conn.execute("INSERT INTO owner VALUES(1,?,?,1)", (username, password_hash))
            else:
                raise ValueError("Owner already exists" if existing else "Owner is not initialized")

    def portfolio(self, portfolio_id, owner_id=1):
        if not isinstance(portfolio_id, str) or not ID.fullmatch(portfolio_id):
            raise WebError(404, "not_found", "Portfolio not found")
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM portfolios WHERE id=? AND owner_id=?", (portfolio_id, owner_id)).fetchone()
        if not row:
            raise WebError(404, "not_found", "Portfolio not found")
        project = contained(self.root, "portfolios/" + portfolio_id)
        if not project.is_dir():
            raise WebError(409, "portfolio_unavailable", "Portfolio storage is unavailable")
        return dict(row), project

    def portfolios(self, owner_id=1):
        with closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,name,created_at FROM portfolios WHERE owner_id=? ORDER BY created_at,id", (owner_id,))]

    def create_portfolio(self, name, locale, cost_policy, owner_id=1):
        from ..i18n import normalize_locale
        from ..settings import btc_cost_policy
        locale = normalize_locale(locale)
        cost_policy = btc_cost_policy(self.root, cost_policy)
        portfolio_id = uuid.uuid4().hex
        project = contained(self.root, "portfolios/" + portfolio_id)
        project.mkdir(mode=0o700)
        try:
            (project / "config").mkdir(mode=0o700)
            raw = f'[reporting]\nlocale = "{locale}"\nbtc_cost_policy = "{cost_policy}"\n'.encode()
            private_write(project / "config/local.toml", raw)
            with self.transaction() as conn:
                conn.execute("INSERT INTO portfolios VALUES(?,?,?,?)", (portfolio_id, owner_id, name, self.clock()))
        except BaseException:
            import shutil
            shutil.rmtree(project)
            raise
        return self.portfolio(portfolio_id, owner_id)[0]

    def reporting_settings(self, portfolio_id, owner_id=1):
        from ..settings import report_locale, btc_cost_policy
        _, project = self.portfolio(portfolio_id, owner_id)
        contained(project, "config/local.toml")
        try:
            return {"locale": report_locale(project), "btc_cost_policy": btc_cost_policy(project)}
        except ValueError as exc:
            raise WebError(409, "invalid_settings", "Portfolio settings need local review") from exc

    def save_settings(self, portfolio_id, locale, cost_policy, owner_id=1):
        from ..i18n import normalize_locale
        from ..settings import btc_cost_policy
        locale = normalize_locale(locale)
        cost_policy = btc_cost_policy(self.root, cost_policy)
        from ..operations import project_lock
        import tomllib
        _, project = self.portfolio(portfolio_id, owner_id)
        path = contained(project, "config/local.toml")
        with project_lock(project):
            text = path.read_text() if path.exists() else ""
            try:
                parsed = tomllib.loads(text)
                if not isinstance(parsed.get("reporting", {}), dict):
                    raise ValueError("Invalid reporting section")
                section = re.search(r"(?m)^\[reporting\][ \t]*(?:#.*)?$", text)
                if not section and "reporting" in parsed:
                    raise ValueError("Inline reporting tables need local review")
            except (ValueError, tomllib.TOMLDecodeError) as exc:
                raise WebError(409, "invalid_settings", "Portfolio settings need local review") from exc
            if not section:
                text = text.rstrip() + '\n\n[reporting]\n'
                section = re.search(r"(?m)^\[reporting\]$", text)
            after = text[section.end():]
            next_section = re.search(r"(?m)^\[", after)
            end = section.end() + next_section.start() if next_section else len(text)
            contents = text[section.end():end]
            for key, value in (("locale", locale), ("btc_cost_policy", cost_policy)):
                entry = key + " = " + json.dumps(value)
                pattern = r"(?m)^[ \t]*" + key + r"[ \t]*=.*$"
                contents = re.sub(pattern, entry, contents) if re.search(pattern, contents) else contents.rstrip() + "\n" + entry + "\n"
            updated = text[:section.end()] + contents + text[end:]
            tomllib.loads(updated)
            private_write(path, updated.encode())
        return self.reporting_settings(portfolio_id, owner_id)

    def register_artifact(self, portfolio_id, report_id, relative_path, owner_id=1, *, connection=None):
        """Trusted future worker hook; not an HTTP registration or export endpoint."""
        _, project = self.portfolio(portfolio_id, owner_id)
        if not isinstance(report_id, str) or not ID.fullmatch(report_id):
            raise ValueError("Report IDs must be server-generated identifiers")
        if not relative_path.startswith(("reports/", "data/raw/")):
            raise ValueError("Artifacts must be retained report/source evidence")
        path = contained(project, relative_path)
        media_type = ARTIFACT_TYPES.get(path.suffix.lower())
        if not media_type or not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError("Unsupported or oversized artifact")
        with path.open("rb") as stream:
            raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ValueError("Oversized artifact")
        artifact_id = uuid.uuid4().hex
        with (nullcontext(connection) if connection is not None else self.transaction()) as conn:
            existing = conn.execute("SELECT id,sha256,byte_size FROM artifacts WHERE portfolio_id=? AND report_id=? AND relative_path=?",
                                    (portfolio_id, report_id, relative_path)).fetchall()
            if existing:
                if len(existing) != 1 or existing[0]["sha256"] != hashlib.sha256(raw).hexdigest() or existing[0]["byte_size"] != len(raw):
                    raise ValueError("Registered artifact changed; local review is required")
                return existing[0]["id"]
            conn.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)", (artifact_id, portfolio_id, report_id,
                relative_path, hashlib.sha256(raw).hexdigest(), len(raw), media_type))
        return artifact_id

    def artifacts(self, portfolio_id, owner_id=1):
        self.portfolio(portfolio_id, owner_id)
        with closing(self.connect()) as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,report_id,sha256,byte_size,media_type FROM artifacts WHERE portfolio_id=? ORDER BY id", (portfolio_id,))]

    def read_artifact(self, portfolio_id, artifact_id, owner_id=1):
        _, project = self.portfolio(portfolio_id, owner_id)
        if not isinstance(artifact_id, str) or not ID.fullmatch(artifact_id):
            raise WebError(404, "not_found", "Artifact not found")
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id=? AND portfolio_id=?", (artifact_id, portfolio_id)).fetchone()
        if not row:
            raise WebError(404, "not_found", "Artifact not found")
        if not row["relative_path"].startswith(("reports/", "data/raw/")):
            raise WebError(409, "artifact_integrity", "Artifact integrity check failed")
        path = contained(project, row["relative_path"])
        if not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise WebError(409, "artifact_integrity", "Artifact integrity check failed")
        with path.open("rb") as stream:
            raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        if len(raw) != row["byte_size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise WebError(409, "artifact_integrity", "Artifact integrity check failed")
        return raw, row["media_type"], artifact_id + path.suffix.lower()
