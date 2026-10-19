"""Explicitly approved source reports with atomic data and frozen publication retries.

This trusted-core workflow is independent of ordinary native import routing. No
parser, quote lookup or ETF refresh is performed after the data commit marker.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Context, localcontext
import hashlib
import json
from pathlib import Path
import os
import re
import shutil
import tempfile
import uuid

from . import operations, source_ingestion as ingestion
from .i18n import presentation_context
from .source_pipeline import host_config, bounded_read, _json
from .source_projection import _serialize
from .source_submission import (SubmissionError, _safe_directory, _workspace_hash,
    prepare_submission, load_submission, _pending, _encode)
from .source_report import make_source_payload
from .source_valuation import freeze_valuation, read_source_valuation
from .workspace import resolve_workspace

FORMAT = "wealth-ledger-source-report-preview"
MAX_MANIFEST = 512 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024
OP = re.compile(r"OP-[a-f0-9]{32}")
SHA = re.compile(r"[a-f0-9]{64}")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _target(project, directory):
    target = _safe_directory(directory)
    from .workspace import CODE_ROOT, INSTALLATION_ROOT, SOURCE_CHECKOUT
    if target.exists() or target == project or any(target.is_relative_to(project/name) for name in ("data","reports","backups","config")):
        raise SubmissionError("unsafe_submission_path")
    if not SOURCE_CHECKOUT and target.is_relative_to(INSTALLATION_ROOT):
        raise SubmissionError("unsafe_submission_path")
    if SOURCE_CHECKOUT and (CODE_ROOT/".git").exists() and target.is_relative_to(CODE_ROOT) and target.relative_to(CODE_ROOT).parts[0] not in {"work","private"}:
        raise SubmissionError("unsafe_submission_path")
    if target.is_relative_to(project) and not (project/"data/db/portfolio.sqlite3").is_file() and not (project/"config/local.toml").is_file():
        raise SubmissionError("unsafe_submission_path")
    return target


def _inputs(project, valuation):
    if not isinstance(valuation,dict) or not {"as_of","period_start","generated_at","fx"} <= set(valuation) or set(valuation)-{
            "as_of","period_start","generated_at","fx","btc_price","kind","btc_cost_policy","report_locale"}:
        raise SubmissionError("invalid_source_valuation")
    from .settings import report_locale, btc_cost_policy
    value = deepcopy(_serialize(valuation))
    locale = report_locale(project,value.pop("report_locale",None))
    value["btc_cost_policy"] = btc_cost_policy(project,value.get("btc_cost_policy"))
    value.setdefault("kind","interim")
    with presentation_context(locale) as context:
        return value,{"locale":locale,"localization":context.metadata()}


def _projection(payload):
    return {"projection_sha256":payload["source_projection"]["projection_sha256"],
            "scope_id":payload["meta"]["scope_id"],"totals":payload["totals"]}


def _summary(manifest):
    return {"status":"awaiting_confirmation","approval_sha256":manifest["approval_sha256"],
            "operation_id":manifest["operation_id"],"valuation_as_of":manifest["valuation"]["as_of"],
            "report_locale":manifest["reporting"]["locale"],"account_review":manifest["account_review"],
            "observed_totals":manifest["preview"]["totals"],"scope":"valued_observed_rows_not_complete_wealth",
            "pending_checks":["latest_official_etf_data","report_generation_and_validation"],
            "report_published":False,"ordinary_cutover_ready":False}


def prepare_source_report(project, paths=(), *, valuation, directory, contexts=(), bindings=(),
                          config_path=None, selections=None, timeout=60, operation_id=None):
    """Freeze exact input/mapping/reference approval; simulation is offline."""
    from .web.maintenance import workspace_activity
    from .preflight import _snapshot
    project=resolve_workspace(explicit=project).workspace_root
    with workspace_activity(project):
        _pending(project)
        target=_target(project,directory)
        values,reporting=_inputs(project,valuation)
        before=operations.input_fingerprint(project)
        config=host_config(config_path)
        environment=ingestion.environment_fingerprint()
        operation=operation_id or "OP-"+uuid.uuid4().hex
        if not isinstance(operation,str) or not OP.fullmatch(operation):raise SubmissionError("invalid_operation")
        if not paths and (contexts or bindings or selections):raise SubmissionError("invalid_source_scope")
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        stage=Path(tempfile.mkdtemp(prefix=".source-report-",dir=target.parent));stage.chmod(0o700)
        try:
            source=None;plan=None;review=[]
            if paths:
                source=prepare_submission(project,paths,contexts=contexts,bindings=bindings,directory=stage/"ingestion",
                    config_path=config_path,selections=selections,timeout=timeout,operation_id=operation)
                if source["status"]=="mapping_required":return source
                _,plan=load_submission(project,stage/"ingestion",source["approval_sha256"])
                review=source["account_review"]
            with tempfile.TemporaryDirectory(prefix="source-report-simulation-") as temporary:
                simulation=Path(temporary)/"portfolio"
                _snapshot(project,simulation)
                if plan is not None:ingestion._apply(simulation,plan)
                payload=make_source_payload(simulation,**values)
            manifest={"format":FORMAT,"schema_version":1,"operation_id":operation,"workspace_sha256":_workspace_hash(project),
                "input_fingerprint":before,"environment_sha256":environment,"configuration_sha256":sha(config),
                "valuation":values,"reporting":reporting,"account_review":review,"preview":_projection(payload),
                "ingestion":{key:source[key] for key in ("approval_sha256","plan_sha256")} if source else None}
            manifest["approval_sha256"]=sha(_encode(manifest))
            raw=_encode(manifest)
            if len(raw)>MAX_MANIFEST:raise SubmissionError("source_preview_limit")
            for name,data in (("manifest.json",raw),("configuration.json",config)):
                path=stage/name;path.write_bytes(data);path.chmod(0o400)
            if before!=operations.input_fingerprint(project) or config!=host_config(config_path) or environment!=ingestion.environment_fingerprint():
                raise SubmissionError("stale_submission")
            os.rename(stage,target)
            return _summary(manifest)
        finally:
            if stage.exists():shutil.rmtree(stage)


def load_source_report(project,directory,approval_sha256):
    """Decode a closed, content-bound report plan without loading plugins."""
    project=resolve_workspace(explicit=project).workspace_root
    directory=_safe_directory(directory)
    try:
        raw=bounded_read(directory/"manifest.json",MAX_MANIFEST);value=_json(raw)
        required={"format","schema_version","operation_id","workspace_sha256","input_fingerprint","environment_sha256",
                  "configuration_sha256","valuation","reporting","account_review","preview","ingestion","approval_sha256"}
        if set(value)!=required or _encode(value)!=raw or value["format"]!=FORMAT or type(value["schema_version"]) is not int or value["schema_version"]!=1:
            raise SubmissionError("invalid_submission")
        if not isinstance(value["operation_id"],str) or not OP.fullmatch(value["operation_id"]):raise SubmissionError("invalid_operation")
        for key in ("workspace_sha256","input_fingerprint","environment_sha256","configuration_sha256","approval_sha256"):
            if not isinstance(value[key],str) or not SHA.fullmatch(value[key]):raise SubmissionError("invalid_submission")
        if value["approval_sha256"]!=approval_sha256 or sha(_encode({k:v for k,v in value.items() if k!="approval_sha256"}))!=approval_sha256:
            raise SubmissionError("approval_mismatch")
        if value["workspace_sha256"]!=_workspace_hash(project):raise SubmissionError("workspace_mismatch")
        if sha(bounded_read(directory/"configuration.json",256*1024))!=value["configuration_sha256"]:raise SubmissionError("source_integrity")
        if {p.name for p in directory.iterdir()}!={"manifest.json","configuration.json"}|({"ingestion"} if value["ingestion"] is not None else set()):raise SubmissionError("invalid_submission")
        if set(value["reporting"])!={"locale","localization"} or set(value["preview"])!={"projection_sha256","scope_id","totals"}:
            raise SubmissionError("invalid_submission")
        for key in ("projection_sha256","scope_id"):
            if not isinstance(value["preview"][key],str) or not SHA.fullmatch(value["preview"][key]):raise SubmissionError("invalid_submission")
        plan=None
        if value["ingestion"] is not None:
            if set(value["ingestion"])!={"approval_sha256","plan_sha256"}:raise SubmissionError("invalid_submission")
            source,plan=load_submission(project,directory/"ingestion",value["ingestion"]["approval_sha256"])
            if source["operation_id"]!=value["operation_id"] or plan.fingerprint!=value["ingestion"]["plan_sha256"] or source["input_fingerprint"]!=value["input_fingerprint"] or plan.environment_sha256!=value["environment_sha256"] or source["configuration_sha256"]!=value["configuration_sha256"]:
                raise SubmissionError("source_integrity")
        return value,plan
    except (ValueError,TypeError,KeyError,OSError,RecursionError) as exc:
        if isinstance(exc,SubmissionError):raise
        raise SubmissionError("invalid_submission") from None


def _archive(stage,payload):
    raw=_encode(payload);digest=sha(raw)
    if len(raw)>MAX_PAYLOAD:raise SubmissionError("source_report_limit")
    relative="data/raw/source-publications/"+digest+".json"
    path=Path(stage)/relative;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=raw:raise SubmissionError("source_integrity")
    if not path.exists():path.write_bytes(raw)
    path.chmod(0o400)
    return {"payload_path":relative,"payload_sha256":digest,"source_valuation_id":payload["meta"]["source_report_observation_id"]}


def frozen_report(project,operation):
    """Verify a committed operation's frozen report without current source access."""
    if operation["request"].get("type")!="source_report_update" or operation["status"] not in {"data_committed","report_failed","published","stale"}:
        raise SubmissionError("completion_not_proven")
    evidence=operation["result"]
    relative=evidence["payload_path"]
    if not isinstance(relative,str) or not re.fullmatch(r"data/raw/source-publications/[a-f0-9]{64}\.json",relative):raise SubmissionError("source_integrity")
    root=Path(project).resolve();path=root/relative
    if any(p.is_symlink() for p in (path,*path.parents) if p.is_relative_to(root)):raise SubmissionError("source_integrity")
    raw=bounded_read(path,MAX_PAYLOAD)
    if sha(raw)!=evidence["payload_sha256"] or relative!="data/raw/source-publications/"+sha(raw)+".json":raise SubmissionError("source_integrity")
    payload=_json(raw)
    original=read_source_valuation(project,evidence["source_valuation_id"])
    original["meta"].pop("report_published",None)
    original["meta"].pop("daily_workflow_ready",None)
    if {k:v for k,v in payload.items() if k not in {"reporting","lookthrough"}}!=original or payload["reporting"]!=operation["request"]["reporting"]:
        raise SubmissionError("source_integrity")
    return payload


def verify_source_publications(project):
    for operation in operations.list_operations(project):
        if operation["request"].get("type")=="source_report_update" and operation["status"] in {"data_committed","report_failed","published","stale"}:
            payload=frozen_report(project,operation)
            if operation["status"]=="published":
                _verify_published(project,_published_target(project,operation["operation_id"]),operation["operation_id"],payload)


def confirm_source_report(project,directory,approval_sha256,*,config_path=None,on_data_committed=None):
    """Commit approved facts/valuation/analysis together, then publish frozen bytes."""
    from .publishing import database_backup
    from .source_native_compatibility import validate_native_compatibility
    project=resolve_workspace(explicit=project).workspace_root
    manifest,plan=load_source_report(project,directory,approval_sha256)
    operation=manifest["operation_id"]
    with operations.project_lock(project):
        existing=next((row for row in operations.list_operations(project) if row["operation_id"]==operation),None)
        if existing:
            if existing["request"].get("approval_sha256")!=approval_sha256 or existing["request"].get("type")!="source_report_update":raise SubmissionError("operation_requires_review")
            return _publish_committed(project,existing,on_data_committed)
        _pending(project)
        if operations.input_fingerprint(project)!=manifest["input_fingerprint"]:raise SubmissionError("stale_submission")
        if sha(host_config(config_path))!=manifest["configuration_sha256"]:raise SubmissionError("stale_configuration")
        if ingestion.environment_fingerprint()!=manifest["environment_sha256"]:raise SubmissionError("stale_environment")
        with presentation_context(manifest["reporting"]["locale"]) as context:
            if context.metadata()!=manifest["reporting"]["localization"]:raise SubmissionError("stale_localization")
        database_backup(project,"before-source-report")
        request={"type":"source_report_update","approval_sha256":approval_sha256,"reporting":manifest["reporting"]}
        operations.start(project,request,operation_id=operation)
        live_fingerprint=operations.input_fingerprint(project)
        try:
            def action(stage):
                if sha(host_config(config_path))!=manifest["configuration_sha256"]:raise SubmissionError("stale_configuration")
                accepted=None
                if plan is not None:
                    validate_native_compatibility(stage,plan.inputs)
                    accepted=ingestion._apply(stage,plan)
                payload=make_source_payload(stage,**manifest["valuation"])
                if _projection(payload)!=manifest["preview"]:raise SubmissionError("stale_projection")
                receipt=freeze_valuation(stage,**manifest["valuation"])
                payload=read_source_valuation(stage,receipt["observation_id"])
                payload["meta"].pop("report_published",None)
                payload["meta"].pop("daily_workflow_ready",None)
                payload["reporting"]=manifest["reporting"]
                if payload["totals"]["total_cad"] is not None:
                    from .lookthrough import attach_analysis
                    with localcontext(Context(prec=payload["meta"]["decimal_precision"])):
                        attach_analysis(stage,payload)
                if operations.input_fingerprint(project)!=live_fingerprint:raise SubmissionError("stale_submission")
                if sha(host_config(config_path))!=manifest["configuration_sha256"] or ingestion.environment_fingerprint()!=manifest["environment_sha256"]:
                    raise SubmissionError("stale_environment")
                return {**_archive(stage,payload),"valuation_as_of":payload["meta"]["as_of"],"ingestion":accepted,
                        "approval_sha256":approval_sha256}
            def marker(conn,result,fingerprint):
                conn.execute("UPDATE update_operations SET status='data_committed',result_json=?,valuation_as_of=?,fingerprint=?,updated_at=? WHERE operation_id=?",
                    (json.dumps(result),result["valuation_as_of"],fingerprint,datetime.now(timezone.utc).isoformat(),operation))
            operations.atomic_data(project,action,finalize=marker)
        except Exception as exc:
            if operations.get(project,operation)["status"]!="data_committed":operations.set_state(project,operation,"data_failed",error=type(exc).__name__)
            raise
        return _publish_committed(project,operations.get(project,operation),on_data_committed)


def resume_source_report(project,operation_id,*,on_data_committed=None):
    project=resolve_workspace(explicit=project).workspace_root
    if not isinstance(operation_id,str) or not OP.fullmatch(operation_id):raise SubmissionError("invalid_operation")
    with operations.project_lock(project):
        return _publish_committed(project,operations.get(project,operation_id),on_data_committed)


def _publish_committed(project,operation,on_data_committed=None):
    from .publishing import recover_publication,publish
    frozen=frozen_report(project,operation)
    op=operation["operation_id"]
    if operation["status"]=="published":
        # Verify original artifacts but never move a newer latest pointer backwards.
        from .publishing import verify_bundle
        output=operation["output"]
        target=_published_target(project,op)
        _verify_published(project,target,op,frozen)
        return {"operation_id":op,"status":"already_published",**output,"output":str(target)}
    if operation["status"] not in {"data_committed","report_failed"}:raise SubmissionError("operation_requires_review")
    _pending(project,op)
    if operations.fingerprint(project)!=operation["fingerprint"]:
        operations.set_state(project,op,"stale",error="source_state_changed")
        raise SubmissionError("stale_submission")
    try:
        if on_data_committed is not None:on_data_committed(op)
        candidate=_published_target(project,op,required=False)
        if candidate is not None:
            _verify_published(project,candidate,op,frozen)
        recovered=recover_publication(project,op) if candidate is not None else None
        if recovered is None:
            with presentation_context(frozen["reporting"]["locale"]) as context:
                if context.metadata()!=frozen["reporting"]["localization"]:raise SubmissionError("stale_localization")
            recovered=publish(project,frozen,{"operation_id":op,"source_valuation_id":operation["result"]["source_valuation_id"],
                "approval_sha256":operation["request"]["approval_sha256"]},frozen_analysis=True)
        _verify_published(project,Path(recovered["output"]),op,frozen)
        operations.set_state(project,op,"published",output_json=json.dumps(recovered),error=None)
        return {"operation_id":op,"status":"published",**recovered}
    except Exception as exc:
        operations.set_state(project,op,"report_failed",error=type(exc).__name__)
        raise operations.ReportOperationError("Source report publication failed; resume the saved operation without reimporting") from exc


def _verify_published(project,target,operation,payload):
    from .publishing import verify_bundle
    manifest=verify_bundle(project,target,operation)
    if (_json(bounded_read(target/"data.json",MAX_PAYLOAD))!=payload
            or manifest.get("source_valuation_id")!=payload["meta"]["source_report_observation_id"]
            or manifest.get("report_model")!="source-neutral-1"):
        raise SubmissionError("source_publication_integrity")


def _published_target(project,operation,*,required=True):
    root=Path(project).resolve();candidates=[]
    for candidate in (root/"reports").glob("*/r*/manifest.json"):
        if any(p.is_symlink() for p in (candidate,*candidate.parents) if p.is_relative_to(root)):
            raise SubmissionError("source_publication_integrity")
        if _json(bounded_read(candidate,MAX_PAYLOAD)).get("import",{}).get("operation_id")==operation:
            candidates.append(candidate.parent)
    if not candidates and not required:return None
    if len(candidates)!=1:raise SubmissionError("source_publication_requires_review")
    return candidates[0]
