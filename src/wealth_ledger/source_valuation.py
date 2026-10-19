"""Append-only frozen source-report observations, separate from source facts.

Only the application service mutates observations under the ordinary workspace
lock/staged transaction. Reading an edition verifies its retained bytes and never
revalues it with today's sources, quotes, FX, configuration or locale.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .source_projection import ProjectionError, _time, _json
from . import source_ingestion as store

TABLE = "source_report_observations"


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def read_observations(project):
    """Read all immutable editions without initializing a database."""
    root = Path(project).resolve()
    conn = store._open(root)
    try:
        if not conn or not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
            return []
        rows = [dict(row) for row in conn.execute("SELECT * FROM source_report_observations ORDER BY id")]
    finally:
        if conn:
            conn.close()
    for row in rows:
        relative = row["archive_path"]
        if not re.fullmatch(r"data/raw/source-valuations/[a-f0-9]{64}\.json", relative):
            raise ProjectionError("source_valuation_archive_unsafe")
        path = root / relative
        if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)):
            raise ProjectionError("source_valuation_archive_unsafe")
        raw = (row["payload_json"]+"\n").encode()
        if relative != "data/raw/source-valuations/"+row["payload_sha256"]+".json" or not path.is_file() or path.read_bytes() != raw or _hash(raw) != row["payload_sha256"]:
            raise ProjectionError("source_valuation_integrity")
        payload = json.loads(row["payload_json"])
        meta = payload["meta"]
        if (meta["report_model"] != "source-neutral-1" or meta["source_report_observation_id"] != row["id"]
                or meta["revision"] != row["revision"] or meta["as_of"] != row["as_of_utc"] or meta["scope_id"] != row["scope_id"]):
            raise ProjectionError("source_valuation_integrity")
        row["payload"] = payload
    return rows


def read_source_valuation(project, observation_id):
    if type(observation_id) is not int or observation_id <= 0:
        raise ProjectionError("invalid_source_valuation_id")
    for row in read_observations(project):
        if row["id"] == observation_id:
            return deepcopy(row["payload"])
    raise ProjectionError("source_valuation_not_found")


def _summary(payload, observation_id=None):
    meta = payload["meta"]
    return {"snapshot_id": observation_id if observation_id is not None else meta["source_report_observation_id"],
            "as_of": meta["as_of"], "kind": meta["kind"], "revision": meta["revision"], "is_complete": False,
            "data_status": meta["data_status"], "totals": deepcopy(payload["totals"]), "accounts": deepcopy(payload["accounts"])}


def attach_history(payload, rows):
    """Show actual same-scope observations; never bridge missing calendar months."""
    selected = {}
    meta = payload["meta"]
    for row in rows:
        if row["scope_id"] == meta["scope_id"] and _time(row["as_of_utc"]) <= _time(meta["as_of"]):
            selected[row["as_of_utc"]] = row
    prior = next((row for row in reversed(rows) if row["as_of_utc"]==meta["as_of"]),None)
    meta["revision"] = prior["revision"] + 1 if prior else 1
    history = [_summary(row["payload"]) for when, row in sorted(selected.items()) if when != meta["as_of"]]
    history.append(_summary(payload))
    payload["history"] = history
    meta["baseline_as_of"] = history[0]["as_of"]
    meta["history_snapshot_ids"] = [row["snapshot_id"] for row in history if row["snapshot_id"] is not None]
    meta["official_snapshot_ids"] = []
    meta["missing_official_months"] = []


def freeze_valuation(stage, **inputs):
    """Internal staged action; callers must use ApplicationService.source_valuation."""
    from .source_report import make_source_payload
    from .core import _now
    rows = read_observations(stage)
    payload = make_source_payload(stage, **inputs)
    meta = payload["meta"]
    signature = _hash(_json({"projection": payload["source_projection"]["projection_sha256"],
                            "scope": meta["scope_id"], "kind": meta["kind"]}).encode())
    last = next((row for row in reversed(rows) if row["as_of_utc"] == meta["as_of"]), None)
    if last and last["signature"] == signature:
        return {"status": "duplicate", "observation_id": last["id"], "revision": last["revision"],
                "payload_sha256": last["payload_sha256"], "report_published": False, "daily_workflow_ready": False}
    db = Path(stage)/"data/db/portfolio.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS source_report_observations(
          id INTEGER PRIMARY KEY,as_of_utc TEXT NOT NULL,revision INTEGER NOT NULL,scope_id TEXT NOT NULL,
          signature TEXT NOT NULL,payload_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,archive_path TEXT NOT NULL,
          created_at TEXT NOT NULL,UNIQUE(as_of_utc,revision))""")
        conn.execute("BEGIN IMMEDIATE")
        observation_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM source_report_observations").fetchone()[0]
        revision = conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM source_report_observations WHERE as_of_utc=?", (meta["as_of"],)).fetchone()[0]
        meta.update(source_report_observation_id=observation_id, revision=revision)
        payload["history"][-1] = _summary(payload, observation_id)
        meta["history_snapshot_ids"] = [row["snapshot_id"] for row in payload["history"]]
        encoded = _json(payload)
        raw = (encoded+"\n").encode()
        sha = _hash(raw)
        relative = "data/raw/source-valuations/"+sha+".json"
        path = Path(stage)/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ProjectionError("source_valuation_archive_collision")
        if not path.exists():
            path.write_bytes(raw)
        path.chmod(0o400)
        conn.execute("INSERT INTO source_report_observations VALUES(?,?,?,?,?,?,?,?,?)",
                     (observation_id,meta["as_of"],revision,meta["scope_id"],signature,sha,encoded,relative,_now()))
    return {"status": "source_valuation_recorded", "observation_id": observation_id, "revision": revision,
            "payload_sha256": sha, "report_published": False, "daily_workflow_ready": False}
