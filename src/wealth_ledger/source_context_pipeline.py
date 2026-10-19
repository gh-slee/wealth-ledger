"""Isolated explicit-context v2 previews; production confirmation stays gated."""
from __future__ import annotations
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import source_v2 as v2
from .source_environment import EnvironmentError, digest, environment_fingerprint
from .source_pipeline import (CONFIG_BYTES, INPUT_BYTES, NORMALIZED_BYTES, PLAN_BYTES,
    SourcePlanError, _json, bounded_read, host_config, parse_config, validate_inputs)
from .source_registry import RegistryError, build_registry

CONTEXT_BYTES = 64 * 1024
BLOCKER = "production_v2_pipeline_pending"


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError("Invalid context schema")
    return value


def _account(value):
    return v2.AccountKey(**_object(value, ("provider", "account_id")))


def parse_context(value):
    """Decode a bounded, closed host schema; never load a class or code from JSON."""
    try:
        _object(value, ("evidence_at", "source_reference"),
            ("account_alias", "source_timezone", "format_selection", "revisions", "scope_revisions"))
        revisions, scopes = value.get("revisions", []), value.get("scope_revisions", [])
        if not isinstance(revisions, list) or not isinstance(scopes, list) or len(revisions) + len(scopes) > 200:
            raise ValueError("Invalid parent choices")
        parents = []
        for item in revisions:
            _object(item, ("account", "kind", "source_id", "observation_id", "supersedes_revision"))
            parents.append(v2.RevisionContext(**{**item, "account": _account(item["account"])}))
        scope_parents = []
        for item in scopes:
            _object(item, ("kind", "scope_id", "supersedes_revision"), ("account", "record_kind", "observation_id"))
            scope_parents.append(v2.ScopeRevisionContext(**{**item,
                "account": _account(item["account"]) if item.get("account") is not None else None}))
        context = v2.ParseContext(datetime.fromisoformat(value["evidence_at"]), value["source_reference"],
            value.get("account_alias"), value.get("source_timezone"), value.get("format_selection"), tuple(parents), tuple(scope_parents))
        v2.validate_context(context)
        return context
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise SourcePlanError("invalid_context") from None


def contexts_from_document(value, count):
    try:
        _object(value, ("schema_version", "inputs"))
        if type(value["schema_version"]) is not int or value["schema_version"] != 1 or not isinstance(value["inputs"], list) or len(value["inputs"]) != count:
            raise ValueError("Context count differs from input count")
        if len(json.dumps(value, allow_nan=False).encode()) > CONTEXT_BYTES:
            raise ValueError("Context limit exceeded")
        return tuple(parse_context(item) for item in value["inputs"])
    except (ValueError, TypeError, RecursionError):
        raise SourcePlanError("invalid_context") from None


def context_document(contexts):
    return {"schema_version": 1, "inputs": [json.loads(v2.canonical_json(context)) for context in contexts]}


def _plan(inputs, contexts, config_raw, selections, *, registry, environment):
    validate_inputs(inputs, selections)
    config, _ = parse_config(config_raw)
    contexts = contexts_from_document(context_document(contexts), len(inputs))
    rows, batches = [], []
    for slot, (raw, context) in enumerate(zip(inputs, contexts), 1):
        try:
            match = registry.detect(raw, adapter_id=selections.get(str(slot)))
            if match.descriptor.info.api_version != 2:
                raise SourcePlanError("protocol_v2_required")
            adapter = next(adapter for descriptor, adapter in registry._entries
                if descriptor.info.adapter_id == match.descriptor.info.adapter_id)
            batch = adapter.normalize(raw, export_version=match.export_version, context=context)
            v2.validate_batch(batch, raw, context=context)
            if batch.adapter != match.descriptor.info or batch.export_version != match.export_version or adapter.info != match.descriptor.info:
                raise SourcePlanError("normalization_identity")
            canonical = v2.canonical_json(batch).encode()
            if len(canonical) > NORMALIZED_BYTES or len(batch.records) > 50000:
                raise SourcePlanError("normalization_limits")
            batches.append(canonical)
            rows.append({"slot": slot, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "adapter": asdict(batch.adapter), "export_version": batch.export_version,
                "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
                "record_counts": dict(sorted(Counter(row.kind for row in batch.records).items())),
                "coverage_count": len(batch.coverage), "account_count": len(batch.accounts)})
        except (RegistryError, SourcePlanError):
            raise
        except Exception:
            raise SourcePlanError("normalization_failed") from None
    body = {"schema_version": 2, "status": "plan_only", "ingestible": False, "booking_blocker": BLOCKER,
        "configuration_sha256": hashlib.sha256(config_raw).hexdigest(), "bindings_sha256": digest(config["bindings"]),
        "contexts_sha256": digest(context_document(contexts)), "environment_sha256": environment,
        "catalog_sha256": digest([asdict(item) for item in registry.adapters]), "selections": selections, "inputs": rows}
    body = _json(json.dumps(body))
    return {**body, "fingerprint": digest(body)}, tuple(batches)


def validate_receipt(value):
    try:
        from .source_pipeline import SHA, validate_selections
        hashes = {"configuration_sha256", "bindings_sha256", "contexts_sha256", "environment_sha256", "catalog_sha256"}
        keys = hashes | {"schema_version", "status", "ingestible", "booking_blocker", "selections", "inputs", "fingerprint"}
        if not isinstance(value, dict) or set(value) != keys or type(value["schema_version"]) is not int or value["schema_version"] != 2 or value["status"] != "plan_only" or value["ingestible"] is not False or value["booking_blocker"] != BLOCKER:
            raise ValueError("Invalid source context plan")
        if any(not isinstance(value[key], str) or not SHA.fullmatch(value[key]) for key in hashes | {"fingerprint"}):
            raise ValueError("Invalid digest")
        if digest({key: item for key, item in value.items() if key != "fingerprint"}) != value["fingerprint"]:
            raise ValueError("Invalid plan fingerprint")
        if not isinstance(value["inputs"], list) or not 1 <= len(value["inputs"]) <= 5:
            raise ValueError("Invalid input scope")
        validate_selections(len(value["inputs"]), value["selections"])
        for slot, row in enumerate(value["inputs"], 1):
            if set(row) != {"slot", "raw_sha256", "adapter", "export_version", "canonical_sha256", "record_counts", "coverage_count", "account_count"} or type(row["slot"]) is not int or row["slot"] != slot:
                raise ValueError("Invalid input evidence")
            if any(not isinstance(row[key], str) or not SHA.fullmatch(row[key]) for key in ("raw_sha256", "canonical_sha256")):
                raise ValueError("Invalid source digest")
            info = v2.AdapterInfo(**{**row["adapter"], "export_versions": tuple(row["adapter"]["export_versions"]), "kinds": tuple(row["adapter"]["kinds"])})
            v2.validate_info(info)
            if row["export_version"] not in info.export_versions or not isinstance(row["record_counts"], dict) or not set(row["record_counts"]) <= set(info.kinds) or any(type(n) is not int or n <= 0 for n in row["record_counts"].values()):
                raise ValueError("Invalid source counts")
            if (type(row["coverage_count"]) is not int or not 0 <= row["coverage_count"] <= 50000
                    or type(row["account_count"]) is not int or not 0 < row["account_count"] <= 50000):
                raise ValueError("Invalid scope counts")
        return value
    except (ValueError, TypeError, KeyError, RecursionError):
        raise SourcePlanError("invalid_plan") from None


@dataclass(frozen=True)
class ParsedSources:
    """Private host results; summary is safe to use as a nonbooking plan receipt."""
    receipt: dict
    batches: tuple[v2.NormalizedBatch, ...]
    raw: tuple[bytes, ...]


def parse_sources(paths, *, contexts, config_path=None, selections=None, previous=None,
                  expected_environment=None, timeout=60, python=None):
    """Bounded fresh child execution, then strict archive decode without plugin code."""
    from .workspace import PACKAGE_ROOT
    if type(timeout) not in {int, float} or not 0 < timeout <= 60:
        raise SourcePlanError("invalid_timeout")
    if not isinstance(paths, (tuple, list)) or not 1 <= len(paths) <= 5:
        raise SourcePlanError("invalid_inputs")
    inputs = tuple(bounded_read(path, INPUT_BYTES) for path in paths)
    selections = {} if selections is None else selections
    validate_inputs(inputs, selections)
    document = context_document(contexts)
    contexts = contexts_from_document(document, len(inputs))
    config = host_config(config_path)
    if previous is not None:
        validate_receipt(previous)
    with tempfile.TemporaryDirectory(prefix="wealth-ledger-source-context-") as directory:
        root = Path(directory); root.chmod(0o700)
        for index, raw in enumerate(inputs):
            target = root / (str(index) + ".csv"); target.write_bytes(raw); target.chmod(0o400)
        request = {"config": config.decode(), "contexts": document, "selections": selections,
            "inputs": len(inputs), "expected_environment": expected_environment}
        target = root / "request.json"; target.write_text(json.dumps(request)); target.chmod(0o600)
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR") if key in os.environ}
        env.update({"PYTHONPATH": str(PACKAGE_ROOT.parent), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(root / "bytecode"), "PYTHONHASHSEED": "0", "PYTHONUTF8": "1", "TZ": "UTC"})
        try:
            result = subprocess.run([str(python or sys.executable), "-B", "-m", "wealth_ledger.source_context_pipeline", str(root)],
                env=env, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise SourcePlanError("parser_timeout") from None
        except OSError:
            raise SourcePlanError("parser_unavailable") from None
        try:
            value = _json(bounded_read(root / "result.json", PLAN_BYTES))
            if result.returncode or "error" in value:
                known = {"invalid_context", "protocol_v2_required", "normalization_identity", "normalization_limits", "normalization_failed", "stale_environment", "environment_unverifiable", "no_match", "ambiguous_detection", "unknown_adapter", "invalid_configuration", "unavailable_plugin", "ambiguous_plugin", "plugin_load_failed", "invalid_adapter", "incompatible_adapter", "duplicate_adapter", "conflicting_provider", "invalid_catalog", "detection_failed", "invalid_detection"}
                raise SourcePlanError(value.get("error") if value.get("error") in known else "parser_failed")
            validate_receipt(value)
            if value["configuration_sha256"] != hashlib.sha256(config).hexdigest() or value["contexts_sha256"] != digest(document) or value["selections"] != selections or len(value["inputs"]) != len(inputs):
                raise SourcePlanError("invalid_plan")
            if expected_environment is not None and value["environment_sha256"] != expected_environment:
                raise SourcePlanError("stale_environment")
            batches = []
            for slot, (raw, context, row) in enumerate(zip(inputs, contexts, value["inputs"])):
                canonical = bounded_read(root / (str(slot) + ".json"), NORMALIZED_BYTES)
                if row["canonical_sha256"] != hashlib.sha256(canonical).hexdigest() or row["raw_sha256"] != hashlib.sha256(raw).hexdigest():
                    raise SourcePlanError("invalid_plan")
                batch = v2.decode_batch(canonical, raw)
                v2.validate_batch(batch, raw, context=context)
                if json.loads(v2.canonical_json(batch.adapter)) != row["adapter"] or batch.export_version != row["export_version"] or dict(Counter(item.kind for item in batch.records)) != row["record_counts"] or len(batch.accounts) != row["account_count"] or len(batch.coverage) != row["coverage_count"]:
                    raise SourcePlanError("invalid_plan")
                batches.append(batch)
        except SourcePlanError:
            raise
        except Exception:
            raise SourcePlanError("parser_failed") from None
    if host_config(config_path) != config or any(bounded_read(path, INPUT_BYTES) != raw for path, raw in zip(paths, inputs)):
        raise SourcePlanError("stale_plan")
    if previous is not None and value["fingerprint"] != previous["fingerprint"]:
        raise SourcePlanError("stale_plan")
    return ParsedSources(value, tuple(batches), inputs)


def plan_context_sources(paths, **kwargs):
    return parse_sources(paths, **kwargs).receipt


def _child(root):
    target = root / "result.json"
    try:
        from .source_builtin import registrations
        request = _json(bounded_read(root / "request.json", CONFIG_BYTES + CONTEXT_BYTES + 16384))
        config = request["config"].encode()
        _, enabled = parse_config(config)
        before = environment_fingerprint()
        if request["expected_environment"] is not None and before != request["expected_environment"]:
            raise SourcePlanError("stale_environment")
        registry = build_registry(builtins=registrations(), enabled=enabled)
        inputs = tuple(bounded_read(root / (str(index) + ".csv"), INPUT_BYTES) for index in range(request["inputs"]))
        contexts = contexts_from_document(request["contexts"], len(inputs))
        value, canonical = _plan(inputs, contexts, config, request["selections"], registry=registry, environment=before)
        if environment_fingerprint() != before:
            raise SourcePlanError("stale_environment")
        for index, raw in enumerate(canonical):
            path = root / (str(index) + ".json"); path.write_bytes(raw); path.chmod(0o400)
        status = 0
    except (RegistryError, SourcePlanError) as exc:
        value, status = {"error": exc.code}, 2
    except EnvironmentError:
        value, status = {"error": "environment_unverifiable"}, 2
    except Exception:
        value, status = {"error": "parser_failed"}, 2
    with target.open("x", encoding="utf-8") as stream:
        target.chmod(0o600); json.dump(value, stream)
    return status


if __name__ == "__main__":
    raise SystemExit(_child(Path(sys.argv[1])))
