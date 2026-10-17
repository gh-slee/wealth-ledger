"""Versioned bundled company identities with auditable private overrides."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .workspace import CODE_ROOT


def _read(path):
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Company aliases must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _companies(value):
    rows = value.get("companies")
    if not isinstance(rows, list):
        raise ValueError("Company aliases require a companies array")
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or (not {"id", "name", "aliases"} <= set(row) or not set(row) <= {"id", "name", "aliases", "sources"}):
            raise ValueError("Company aliases require id/name/aliases and optional sources")
        if any(not isinstance(row[k], str) or not row[k].strip() for k in ("id", "name")):
            raise ValueError("Company alias identity/name must be nonempty strings")
        if row["id"] in ids:
            raise ValueError("Duplicate company alias identity")
        ids.add(row["id"])
        if "sources" in row and (not isinstance(row["sources"], list) or any(not isinstance(v, str) or not v.strip() for v in row["sources"])):
            raise ValueError("Company alias sources must be nonempty strings")
        if not isinstance(row["aliases"], list) or any(not isinstance(a, str) or not a.strip() for a in row["aliases"]):
            raise ValueError("Company aliases must be nonempty strings")
    return rows


def company_aliases(workspace, *, code_root=CODE_ROOT):
    """v2 legacy full files remain valid; v1 overrides replace companies by ID.

    Bundle -> legacy workspace v2 file -> optional private v1 overrides. Identity
    collisions across companies fail before any official data download.
    """
    bundled = Path(code_root) / "config/company-aliases.json"
    base, base_hash = _read(bundled)
    if base.get("version") != 2:
        raise ValueError("Unsupported bundled company-alias version")
    _companies(base)
    evidence = {"schema_version": 1, "bundled_sha256": base_hash,
                "legacy_sha256": None, "override_sha256": None,
                "precedence": ["bundled_v2", "workspace_legacy_v2", "workspace_override_v1"]}
    legacy = Path(workspace) / "config/company-aliases.json"
    if legacy.is_file() and legacy.resolve() != bundled.resolve():
        base, evidence["legacy_sha256"] = _read(legacy)
        if base.get("version") != 2:
            raise ValueError("Unsupported workspace company-alias version")
        _companies(base)
    override = Path(workspace) / "config/company-aliases.override.json"
    if override.is_file():
        changes, evidence["override_sha256"] = _read(override)
        if set(changes) != {"schema_version", "companies"} or changes["schema_version"] != 1:
            raise ValueError("Company overrides require schema_version 1 and companies")
        rows = {row["id"]: row for row in _companies(base)}
        rows.update({row["id"]: row for row in _companies(changes)})
        base = {**base, "companies": list(rows.values())}
    from .lookthrough import Identities, digest
    Identities([], base)
    evidence["effective_sha256"] = digest(base)
    return base, evidence
