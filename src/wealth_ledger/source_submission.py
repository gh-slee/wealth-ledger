"""Frozen, explicitly confirmed canonical submissions shared by host CLI and Web.

This is an opt-in data-only path. Report projections and native daily-workflow
cutover remain gated; no plugin is executed during confirmation or recovery.
"""
from __future__ import annotations
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from . import source_ingestion as core, source_v2 as v2
from .operations import input_fingerprint, list_operations
from .source_context_pipeline import parse_sources
from .source_pipeline import CONFIG_BYTES, INPUT_BYTES, NORMALIZED_BYTES, _json, bounded_read, host_config
from .workspace import resolve_workspace

MANIFEST_BYTES = 256 * 1024
FORMAT = "wealth-ledger-frozen-source-submission"
SHA = re.compile(r"[a-f0-9]{64}")
OP = re.compile(r"OP-[a-f0-9]{32}")


class SubmissionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__("Source submission rejected: " + code)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _closed(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise SubmissionError("invalid_submission")
    return value


def parse_bindings(value):
    """Explicit per-portfolio choices; host-global preview aliases are not applied."""
    try:
        _closed(value, ("schema_version", "bindings"))
        if type(value["schema_version"]) is not int or value["schema_version"] != 1 or not isinstance(value["bindings"], list) or len(value["bindings"]) > 200:
            raise SubmissionError("invalid_bindings")
        result, seen = [], set()
        for item in value["bindings"]:
            if not isinstance(item, dict) or item.get("target_kind") not in {"new", "canonical", "legacy_holdings", "legacy_crypto"}:
                raise SubmissionError("invalid_bindings")
            keys = {"provider", "source_account_id", "target_kind"}
            if item["target_kind"] != "new": keys.add("ledger_account_id")
            _closed(item, keys)
            if any(not isinstance(v, str) or not v or len(v) > 200 or v != v.strip() or any(ord(c) < 32 for c in v) for v in item.values()):
                raise SubmissionError("invalid_bindings")
            account = v2.AccountKey(item["provider"], item["source_account_id"])
            if account in seen: raise SubmissionError("invalid_bindings")
            seen.add(account)
            result.append(core.new_binding(account) if item["target_kind"] == "new" else
                core.Binding(account, item["ledger_account_id"], item["target_kind"]))
        return tuple(result)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        if isinstance(exc, SubmissionError): raise
        raise SubmissionError("invalid_bindings") from None


def _all_bindings(project, batches, choices):
    conn = core._open(project)
    try:
        stored = {(r["provider"], r["source_account"]): r for r in core._rows(conn, "src_bindings")}
        holdings = {r["account_id"]:r for r in core._rows(conn, "accounts")}
        crypto = {(r["provider"],r["source_account"]):r for r in core._rows(conn, "crypto_accounts")}
        supplied = {b.account:b for b in choices}
        if len(supplied) != len(choices): raise SubmissionError("invalid_bindings")
        accounts = {a.key:a for batch in batches for a in batch.accounts}
        if set(supplied) - set(accounts): raise SubmissionError("invalid_bindings")
        result = []
        for key, account in sorted(accounts.items(), key=lambda item:(item[0].provider,item[0].account_id)):
            old = stored.get((key.provider, key.account_id))
            binding = supplied.get(key)
            if binding is None and old:
                binding = core.Binding(key, old["ledger_account"], old["target_kind"])
            if binding is None: raise SubmissionError("binding_required")
            legacy_holding = holdings.get(key.account_id) if account.role == "investment" else None
            legacy_crypto = crypto.get((key.provider,key.account_id)) if account.role == "crypto" else None
            if not old and ((legacy_holding and (binding.target_kind != "legacy_holdings" or binding.ledger_account_id != key.account_id)) or
                    (legacy_crypto and (binding.target_kind != "legacy_crypto" or binding.ledger_account_id != legacy_crypto["account_id"]))):
                raise SubmissionError("legacy_mapping_required")
            result.append(binding)
        return tuple(result)
    finally:
        if conn: conn.close()


def mapping_review(project, batches):
    conn=core._open(project)
    try:
        stored={(r["provider"],r["source_account"]):r for r in core._rows(conn,"src_bindings")}
        holdings={r["account_id"]:r for r in core._rows(conn,"accounts")}
        crypto={(r["provider"],r["source_account"]):r for r in core._rows(conn,"crypto_accounts")}
        result=[]
        accounts={a.key:a for batch in batches for a in batch.accounts}
        for key,account in sorted(accounts.items(),key=lambda item:(item[0].provider,item[0].account_id)):
            old=stored.get((key.provider,key.account_id))
            choice={"provider":key.provider,"source_account_id":key.account_id,"target_kind":"new"}
            if old:choice.update(target_kind=old["target_kind"],ledger_account_id=old["ledger_account"])
            elif account.role=="investment" and key.account_id in holdings:
                choice.update(target_kind="legacy_holdings",ledger_account_id=key.account_id)
            elif account.role=="crypto" and (key.provider,key.account_id) in crypto:
                choice.update(target_kind="legacy_crypto",ledger_account_id=crypto[(key.provider,key.account_id)]["account_id"])
            result.append({"label":account.label,"role":account.role,"account_type":account.account_type,
                "masked_identifier":account.masked_identifier,"suggested_choice":choice})
        return result
    finally:
        if conn:conn.close()


def _review(plan):
    bindings = {b.account:b for b in plan.bindings}
    accounts = {a.key:a for source in plan.inputs for a in source.batch.accounts}
    return [{"provider":key.provider, "source_account_id":key.account_id, "label":account.label,
             "account_type":account.account_type, "role":account.role, "masked_identifier":account.masked_identifier,
             "ledger_account_id":bindings[key].ledger_account_id, "target_kind":bindings[key].target_kind}
            for key,account in sorted(accounts.items(),key=lambda item:(item[0].provider,item[0].account_id))]


def _safe_directory(directory):
    path = Path(directory).expanduser().absolute()
    # Canonicalize the caller-selected parent (including platform temp aliases),
    # then anchor all IO there. The bundle itself must never be a symlink.
    if path.is_symlink():raise SubmissionError("unsafe_submission_path")
    return path.parent.resolve()/path.name


def _workspace_hash(project):
    return _hash(str(Path(project).resolve()).encode())


def _pending(project, operation_id=None):
    if any(row["operation_id"] != operation_id and row["status"] in {"started","data_started","data_committed","report_failed"}
           for row in list_operations(project)):
        raise SubmissionError("unfinished_operation")


def prepare_submission(project, paths, *, contexts, bindings, directory, config_path=None,
                       selections=None, operation_id=None, timeout=60):
    """Coordinate CLI plan writes with full Web-instance backup/maintenance."""
    from .web.maintenance import workspace_activity
    project=resolve_workspace(explicit=project).workspace_root
    with workspace_activity(project):
        return _prepare_submission(project,paths,contexts=contexts,bindings=bindings,directory=directory,
            config_path=config_path,selections=selections,operation_id=operation_id,timeout=timeout)


def _prepare_submission(project, paths, *, contexts, bindings, directory, config_path=None,
                        selections=None, operation_id=None, timeout=60):
    """Parse once in a child, statefully validate, then atomically save private evidence."""
    project = resolve_workspace(explicit=project).workspace_root
    _pending(project)
    before = input_fingerprint(project)
    config = host_config(config_path)
    parsed = parse_sources(paths, contexts=contexts, config_path=config_path, selections=selections, timeout=timeout)
    try:
        effective = _all_bindings(project, parsed.batches, bindings)
    except SubmissionError as exc:
        if exc.code!="binding_required":raise
        return {"status":"mapping_required","account_review":mapping_review(project,parsed.batches),
            "report_projection_ready":False,"report_published":False,"contributions_calculated":False}
    plan = core.prepare_ingestion(project, tuple(core.SourceInput(batch, raw) for batch,raw in zip(parsed.batches,parsed.raw)), bindings=effective)
    from .source_native_compatibility import validate_native_compatibility
    validate_native_compatibility(project,plan.inputs)
    if before != input_fingerprint(project) or host_config(config_path) != config or parsed.receipt["environment_sha256"] != plan.environment_sha256:
        raise SubmissionError("stale_submission")
    operation = operation_id or "OP-" + uuid.uuid4().hex
    if not isinstance(operation,str) or not OP.fullmatch(operation): raise SubmissionError("invalid_operation")
    manifest = {"format":FORMAT, "schema_version":1, "operation_id":operation, "workspace_sha256":_workspace_hash(project),
        "input_fingerprint":before, "configuration_sha256":_hash(config), "state_sha256":plan.state_sha256,
        "environment_sha256":plan.environment_sha256, "policy":plan.policy, "plan_sha256":plan.fingerprint,
        "bindings":[asdict(b) for b in plan.bindings], "inputs":[{"raw_sha256":_hash(s.raw),
            "canonical_sha256":_hash(v2.canonical_json(s.batch).encode())} for s in plan.inputs]}
    manifest["approval_sha256"] = _hash(_encode(manifest))
    target = _safe_directory(directory)
    from .workspace import CODE_ROOT, INSTALLATION_ROOT, SOURCE_CHECKOUT
    if not SOURCE_CHECKOUT and target.is_relative_to(INSTALLATION_ROOT):
        raise SubmissionError("unsafe_submission_path")
    if SOURCE_CHECKOUT and (CODE_ROOT/".git").exists() and target.is_relative_to(CODE_ROOT) and (not target.relative_to(CODE_ROOT).parts or target.relative_to(CODE_ROOT).parts[0] not in {"work","private"}):
        raise SubmissionError("unsafe_submission_path")
    if target.exists() or target == project or any(target.is_relative_to(project/name) for name in ("data","reports","backups","config")):
        raise SubmissionError("unsafe_submission_path")
    # An empty financial workspace must remain resolvable until its first commit.
    if target.is_relative_to(project) and not (project/"data/db/portfolio.sqlite3").is_file() and not (project/"config/local.toml").is_file():
        raise SubmissionError("unsafe_submission_path")
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix=".source-submission-",dir=target.parent)); stage.chmod(0o700)
    try:
        files = {"manifest.json":_encode(manifest),"configuration.json":config}
        for index, source in enumerate(plan.inputs):
            files[str(index)+".csv"] = source.raw
            files[str(index)+".json"] = v2.canonical_json(source.batch).encode()
        for name,raw in files.items():
            with (stage/name).open("xb") as stream:
                os.chmod(stage/name,0o600);stream.write(raw)
            (stage/name).chmod(0o400)
        if before != input_fingerprint(project) or host_config(config_path) != config:
            raise SubmissionError("stale_submission")
        os.rename(stage,target)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return submission_summary(manifest,plan)


def submission_summary(manifest, plan):
    return {"status":"awaiting_confirmation", "approval_sha256":manifest["approval_sha256"],
        "operation_id":manifest["operation_id"], "plan_sha256":plan.fingerprint,
        "account_review":_review(plan), "record_count":sum(len(s.batch.records) for s in plan.inputs),
        "report_projection_ready":False, "report_published":False, "contributions_calculated":False,
        "required_acknowledgement":"canonical_data_only_without_reports"}


def load_submission(project, directory, approval_sha256):
    """Strict core-only decode, with no parser imports or dynamic JSON class loading."""
    try:
        project = resolve_workspace(explicit=project).workspace_root
        target = _safe_directory(directory)
        raw = bounded_read(target/"manifest.json",MANIFEST_BYTES)
        manifest = _json(raw)
        if _encode(manifest)!=raw:raise SubmissionError("source_integrity")
        _closed(manifest,("format","schema_version","operation_id","workspace_sha256","input_fingerprint","configuration_sha256",
            "state_sha256","environment_sha256","policy","plan_sha256","bindings","inputs","approval_sha256"))
        if manifest["format"] != FORMAT or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or not isinstance(manifest["operation_id"],str) or not OP.fullmatch(manifest["operation_id"]):
            raise SubmissionError("invalid_submission")
        for key in ("workspace_sha256","input_fingerprint","configuration_sha256","state_sha256","environment_sha256","plan_sha256","approval_sha256"):
            if not isinstance(manifest[key],str) or not SHA.fullmatch(manifest[key]): raise SubmissionError("invalid_submission")
        if manifest["approval_sha256"] != approval_sha256 or _hash(_encode({k:v for k,v in manifest.items() if k!="approval_sha256"})) != approval_sha256:
            raise SubmissionError("approval_mismatch")
        if manifest["workspace_sha256"] != _workspace_hash(project): raise SubmissionError("workspace_mismatch")
        if not isinstance(manifest["inputs"],list) or not 1<=len(manifest["inputs"])<=5 or not isinstance(manifest["bindings"],list) or len(manifest["bindings"])>200:
            raise SubmissionError("invalid_submission")
        expected = {"manifest.json","configuration.json"}|{str(i)+ext for i in range(len(manifest["inputs"])) for ext in (".csv",".json")}
        if {p.name for p in target.iterdir()} != expected: raise SubmissionError("invalid_submission")
        if _hash(bounded_read(target/"configuration.json",CONFIG_BYTES)) != manifest["configuration_sha256"]:
            raise SubmissionError("source_integrity")
        bindings = []
        for value in manifest["bindings"]:
            _closed(value,("account","ledger_account_id","target_kind")); _closed(value["account"],("provider","account_id"))
            bindings.append(core.Binding(v2.AccountKey(**value["account"]),value["ledger_account_id"],value["target_kind"]))
        sources, total = [], 0
        for index,item in enumerate(manifest["inputs"]):
            _closed(item,("raw_sha256","canonical_sha256"))
            original = bounded_read(target/(str(index)+".csv"),INPUT_BYTES)
            canonical = bounded_read(target/(str(index)+".json"),NORMALIZED_BYTES)
            total += len(original)
            if total > 25*1024*1024 or _hash(original)!=item["raw_sha256"] or _hash(canonical)!=item["canonical_sha256"]:
                raise SubmissionError("source_integrity")
            sources.append(core.SourceInput(v2.decode_batch(canonical,original),original))
        plan = core.IngestionPlan(tuple(sources),tuple(bindings),manifest["state_sha256"],manifest["environment_sha256"],manifest["policy"],manifest["plan_sha256"])
        core._validate_plan(plan)
        _review(plan)
        return manifest,plan
    except (ValueError,TypeError,KeyError,OSError,RecursionError) as exc:
        if isinstance(exc,SubmissionError):raise
        raise SubmissionError("invalid_submission") from None


def recover_submission(project, operation_id, plan_sha256):
    """Only a matching atomic completion receipt proves success; never rerun inputs."""
    if not isinstance(operation_id,str) or not OP.fullmatch(operation_id) or not isinstance(plan_sha256,str) or not SHA.fullmatch(plan_sha256):
        raise SubmissionError("invalid_operation")
    project = resolve_workspace(explicit=project).workspace_root
    saved = next((r for r in list_operations(project) if r["operation_id"]==operation_id),None)
    if saved is None:return None
    if saved["request"] != {"type":"source_v2_canonical_ingestion","plan_sha256":plan_sha256,"policy":core.POLICY} or saved["status"]!="data_only_complete":
        raise SubmissionError("operation_requires_review")
    core.verify_store(project)
    return {"operation_id":operation_id,"report_published":False,**saved["result"]}


def confirm_submission(project, directory, approval_sha256, *, acknowledge_no_reports=False, config_path=None):
    if acknowledge_no_reports is not True:raise SubmissionError("report_gate_acknowledgement_required")
    manifest,plan = load_submission(project,directory,approval_sha256)
    completed = recover_submission(project,manifest["operation_id"],plan.fingerprint)
    if completed is not None:return completed
    if _hash(host_config(config_path)) != manifest["configuration_sha256"]:
        raise SubmissionError("stale_configuration")
    _pending(project)
    result = core.commit_ingestion(resolve_workspace(explicit=project),plan,operation_id=manifest["operation_id"],
        expected_fingerprint=manifest["input_fingerprint"], require_clear_operations=True,
        configuration_evidence=(config_path,manifest["configuration_sha256"]))
    return result
