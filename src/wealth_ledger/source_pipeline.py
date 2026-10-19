"""Shared bounded parser plans; protocol-v1 evidence is never financial submission."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from .source_environment import EnvironmentError, digest, environment_fingerprint
from .source_protocol import canonical_json, validate_batch
from .source_registry import PluginSelection, RegistryError, build_registry

CONFIG_BYTES = 64 * 1024
INPUT_BYTES = 10 * 1024 * 1024
BATCH_BYTES = 25 * 1024 * 1024
PLAN_BYTES = 1024 * 1024
NORMALIZED_BYTES = 4 * 1024 * 1024
DEFAULT_CONFIG = b'{"schema_version":1,"enabled":[],"bindings":[]}'
SHA = re.compile(r"[a-f0-9]{64}")


class SourcePlanError(ValueError):
    """Stable redacted plan errors, safe for CLI/API diagnostics."""

    def __init__(self, code):
        self.code = code
        super().__init__("Source plan rejected: " + code)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def bounded_read(path, maximum):
    try:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
            raise ValueError("Invalid evidence")
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
        if not raw or len(raw) > maximum:
            raise ValueError("Invalid evidence")
        return raw
    except (OSError, ValueError):
        raise SourcePlanError("invalid_evidence") from None


def host_config(path=None):
    if path is not None and Path(path).is_symlink():
        raise SourcePlanError("invalid_configuration")
    raw = DEFAULT_CONFIG if path is None or not Path(path).exists() else bounded_read(path, CONFIG_BYTES)
    parse_config(raw)
    return raw


def parse_config(raw):
    try:
        if type(raw) is not bytes or len(raw) > CONFIG_BYTES:
            raise ValueError("Invalid config")
        value = _json(raw)
        if (not isinstance(value, dict) or set(value) != {"schema_version", "enabled", "bindings"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or not isinstance(value["enabled"], list) or len(value["enabled"]) > 32
                or not isinstance(value["bindings"], list) or len(value["bindings"]) > 200):
            raise ValueError("Invalid config")
        enabled = []
        for item in value["enabled"]:
            if not isinstance(item, dict) or set(item) != {"distribution", "version", "entry_point", "adapter_id"}:
                raise ValueError("Invalid enablement")
            selection = PluginSelection(**item)
            from .source_registry import _selection
            _selection(selection)
            enabled.append(selection)
        seen = set()
        for item in value["bindings"]:
            if not isinstance(item, dict) or set(item) != {"provider_id", "source_account_id", "ledger_account_id"}:
                raise ValueError("Invalid binding")
            if any(not isinstance(v, str) or not v.strip() or len(v) > 200 or any(ord(c) < 32 for c in v) for v in item.values()):
                raise ValueError("Invalid binding")
            token = (item["provider_id"], item["source_account_id"])
            if token in seen:
                raise ValueError("Conflicting bindings")
            seen.add(token)
        return value, tuple(enabled)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise SourcePlanError("invalid_configuration") from None


def validate_selections(count, selections):
    if (not isinstance(selections, dict)
            or any(key not in {str(n) for n in range(1, count + 1)}
                   or not isinstance(value, str)
                   or re.fullmatch(r"[a-z][a-z0-9_.-]{0,199}", value) is None
                   for key, value in selections.items())):
        raise SourcePlanError("invalid_inputs")


def validate_inputs(inputs, selections):
    try:
        if not isinstance(inputs, tuple) or not 1 <= len(inputs) <= 5 or sum(map(len, inputs)) > BATCH_BYTES:
            raise ValueError("Invalid batch")
        validate_selections(len(inputs), selections)
        for raw in inputs:
            if type(raw) is not bytes or not raw or len(raw) > INPUT_BYTES:
                raise ValueError("Invalid bytes")
            text = raw.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError("Invalid text")
            reader = csv.reader(io.StringIO(text, newline=""), strict=True)
            header = [item.strip() for item in next(reader)]
            if not header or len(header) > 256 or len(set(header)) != len(header):
                raise ValueError("Invalid header")
            count = 0
            for row in reader:
                count += 1
                if count > 50000 or len(row) > 256:
                    raise ValueError("Input limits exceeded")
            if count == 0:
                raise ValueError("Empty CSV")
    except (ValueError, TypeError, UnicodeError, StopIteration, csv.Error):
        raise SourcePlanError("invalid_inputs") from None


def _plan(inputs, config_raw, selections, *, registry, environment):
    """Pure planning seam; production callers execute it only in a fresh child."""
    validate_inputs(inputs, selections)
    config, _ = parse_config(config_raw)
    rows = []
    for slot, raw in enumerate(inputs, 1):
        try:
            match = registry.detect(raw, adapter_id=selections.get(str(slot)))
            if match.descriptor.info.api_version != 1:
                raise SourcePlanError("protocol_v2_context_required")
            adapter = next(adapter for descriptor, adapter in registry._entries
                           if descriptor.info.adapter_id == match.descriptor.info.adapter_id)
            batch = adapter.normalize(raw, export_version=match.export_version)
            validate_batch(batch, raw)
            if batch.adapter != match.descriptor.info or batch.export_version != match.export_version or adapter.info != match.descriptor.info:
                raise SourcePlanError("normalization_identity")
            canonical = canonical_json(batch).encode()
            if len(canonical) > NORMALIZED_BYTES or len(batch.records) > 50000:
                raise SourcePlanError("normalization_limits")
            rows.append({"slot": slot, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                         "adapter": asdict(match.descriptor.info), "export_version": match.export_version,
                         "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
                         "record_counts": dict(sorted(Counter(record.kind for record in batch.records).items())),
                         "coverage_count": len(batch.coverage)})
        except RegistryError:
            raise
        except SourcePlanError:
            raise
        except Exception:
            raise SourcePlanError("normalization_failed") from None
    body = {"schema_version": 1, "status": "plan_only", "ingestible": False,
            "booking_blocker": "protocol_v1_not_bookable", "configuration_sha256": hashlib.sha256(config_raw).hexdigest(),
            "bindings_sha256": digest(config["bindings"]), "environment_sha256": environment,
            "catalog_sha256": digest([asdict(item) for item in registry.adapters]),
            "selections": selections, "inputs": rows}
    body = _json(json.dumps(body))
    return {**body, "fingerprint": digest(body)}


def validate_receipt(value):
    try:
        keys = {"schema_version", "status", "ingestible", "booking_blocker", "configuration_sha256", "bindings_sha256", "environment_sha256", "catalog_sha256", "selections", "inputs", "fingerprint"}
        if (not isinstance(value, dict) or set(value) != keys or type(value["schema_version"]) is not int
                or value["schema_version"] != 1 or value["status"] != "plan_only" or value["ingestible"] is not False
                or value["booking_blocker"] != "protocol_v1_not_bookable"
                or any(not isinstance(value[key], str) or not SHA.fullmatch(value[key]) for key in keys if key.endswith("sha256") or key == "fingerprint")):
            raise ValueError("Invalid plan")
        if digest({key: item for key, item in value.items() if key != "fingerprint"}) != value["fingerprint"]:
            raise ValueError("Invalid digest")
        if not isinstance(value["inputs"], list) or not 1 <= len(value["inputs"]) <= 5 or not isinstance(value["selections"], dict):
            raise ValueError("Invalid scope")
        return value
    except (ValueError, TypeError, KeyError, RecursionError):
        raise SourcePlanError("invalid_plan") from None


def plan_sources(paths, *, config_path=None, selections=None, previous=None, expected_environment=None,
                 timeout=60, python=None):
    """CLI/Web shared nonbooking runner with private temporary IO and a wall limit."""
    from .workspace import PACKAGE_ROOT
    if type(timeout) not in {int, float} or not 0 < timeout <= 60:
        raise SourcePlanError("invalid_timeout")
    if not isinstance(paths, (tuple, list)) or not 1 <= len(paths) <= 5:
        raise SourcePlanError("invalid_inputs")
    paths = tuple(paths)
    inputs = tuple(bounded_read(path, INPUT_BYTES) for path in paths)
    selections = {} if selections is None else selections
    validate_inputs(inputs, selections)
    config_raw = host_config(config_path)
    if previous is not None:
        validate_receipt(previous)
    with tempfile.TemporaryDirectory(prefix="wealth-ledger-source-plan-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        for index, raw in enumerate(inputs):
            target = root / (str(index) + ".csv")
            target.write_bytes(raw)
            target.chmod(0o400)
        request = {"config": config_raw.decode("utf-8"), "selections": selections,
                   "inputs": len(inputs), "expected_environment": expected_environment}
        (root / "request.json").write_text(json.dumps(request), encoding="utf-8")
        (root / "request.json").chmod(0o600)
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR") if key in os.environ}
        env.update({"PYTHONPATH": str(PACKAGE_ROOT.parent), "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPYCACHEPREFIX": str(root / "bytecode"), "PYTHONHASHSEED": "0", "PYTHONUTF8": "1", "TZ": "UTC"})
        try:
            result = subprocess.run([str(python or sys.executable), "-B", "-m", "wealth_ledger.source_pipeline", str(root)],
                env=env, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise SourcePlanError("parser_timeout") from None
        except OSError:
            raise SourcePlanError("parser_unavailable") from None
        try:
            value = _json(bounded_read(root / "result.json", PLAN_BYTES))
            if result.returncode or "error" in value:
                known = {"invalid_configuration", "invalid_inputs", "normalization_identity", "normalization_limits", "normalization_failed", "stale_environment", "environment_unverifiable"}
                known.update({"invalid_catalog", "unavailable_plugin", "ambiguous_plugin", "plugin_load_failed", "invalid_adapter", "incompatible_adapter", "duplicate_adapter", "conflicting_provider", "unknown_adapter", "invalid_input", "detection_failed", "invalid_detection", "no_match", "ambiguous_detection"})
                code = value.get("error")
                raise SourcePlanError(code if code in known else "parser_failed")
            validate_receipt(value)
        except SourcePlanError:
            raise
        except Exception:
            raise SourcePlanError("parser_failed") from None
    if host_config(config_path) != config_raw or any(bounded_read(path, INPUT_BYTES) != raw for path, raw in zip(paths, inputs)):
        raise SourcePlanError("stale_plan")
    if previous is not None and value["fingerprint"] != previous["fingerprint"]:
        raise SourcePlanError("stale_plan")
    return value


def _child(root):
    target = root / "result.json"
    try:
        request = _json(bounded_read(root / "request.json", CONFIG_BYTES * 6 + 8192))
        config_raw = request["config"].encode("utf-8")
        _, enabled = parse_config(config_raw)
        before = environment_fingerprint()
        if request["expected_environment"] is not None and before != request["expected_environment"]:
            raise SourcePlanError("stale_environment")
        registry = build_registry(enabled=enabled)
        inputs = tuple(bounded_read(root / (str(index) + ".csv"), INPUT_BYTES) for index in range(request["inputs"]))
        value = _plan(inputs, config_raw, request["selections"], registry=registry, environment=before)
        if environment_fingerprint() != before:
            raise SourcePlanError("stale_environment")
        status = 0
    except (RegistryError, SourcePlanError) as exc:
        value, status = {"error": exc.code}, 2
    except EnvironmentError:
        value, status = {"error": "environment_unverifiable"}, 2
    except Exception:
        value, status = {"error": "parser_failed"}, 2
    with target.open("x", encoding="utf-8") as stream:
        target.chmod(0o600)
        json.dump(value, stream)
    return status


if __name__ == "__main__":
    sys.exit(_child(Path(sys.argv[1])))
