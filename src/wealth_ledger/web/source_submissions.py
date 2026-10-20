"""Owner-scoped opt-in canonical submission jobs; all financial work stays isolated."""
from contextlib import closing
import hashlib
import json
from typing import Literal

from fastapi import Depends, Header, Request
from pydantic import Field, field_validator

from ..operations import input_fingerprint, list_operations
from ..source_context_pipeline import contexts_from_document
from ..source_environment import environment_fingerprint
from ..source_pipeline import host_config
from ..source_submission import (SubmissionError, parse_bindings, prepare_submission,
    load_submission, submission_summary, confirm_submission, recover_submission)
from .imports import Input, JobView
from .jobs import Jobs, PREVIEW_SECONDS, UNRESOLVED, digest, engine_fingerprint
from .source_plans import SourceContext, configuration_path, source_uploads
from .storage import WebError, contained
from .uploads import verified_upload


class BindingChoice(Input):
    provider: str = Field(min_length=1,max_length=200)
    source_account_id: str = Field(min_length=1,max_length=200)
    target_kind: Literal["new","canonical","legacy_holdings","legacy_crypto"]
    ledger_account_id: str | None = Field(default=None,min_length=1,max_length=200)


class SourceIngestionRequest(Input):
    upload_ids: list[str] = Field(min_length=1,max_length=5)
    contexts: list[SourceContext] = Field(min_length=1,max_length=5)
    bindings: list[BindingChoice] = Field(default_factory=list,max_length=200)
    selections: dict[str,str] = Field(default_factory=dict,max_length=5)


class SourceIngestionConfirmation(Input):
    preview_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    approval_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    acknowledge_no_reports: bool

    @field_validator("acknowledge_no_reports")
    @classmethod
    def require_acknowledgement(cls,value):
        if value is not True:raise ValueError("Explicit no-report acknowledgement is required")
        return value


def plan_directory(store, portfolio_id, preview_id):
    from .storage import ID
    if not ID.fullmatch(portfolio_id) or not ID.fullmatch(preview_id):
        raise WebError(404,"not_found","Source preview not found")
    return contained(store.root,"admin/source-submissions/"+portfolio_id+"/"+preview_id)


def enqueue_preview(store,portfolio_id,request,key,owner_id=1):
    _,project=store.portfolio(portfolio_id,owner_id)
    jobs=Jobs(store); request_digest=digest({"kind":"source_preview","request":request})
    with store.transaction() as conn:
        old=jobs._existing(conn,portfolio_id,key,request_digest)
        if old:return old
    rows=source_uploads(store,portfolio_id,request["upload_ids"],owner_id)
    try:
        contexts_from_document({"schema_version":1,"inputs":request["contexts"]},len(rows))
        parse_bindings({"schema_version":1,"bindings":request["bindings"]})
        from ..source_pipeline import validate_selections
        validate_selections(len(rows),request["selections"])
        config=host_config(configuration_path(store)); environment=environment_fingerprint()
    except ValueError:
        raise WebError(422,"invalid_source_request","Review explicit contexts, bindings and host environment") from None
    pinned={**request,"upload_hashes":{r["id"]:r["sha256"] for r in rows},"environment_sha256":environment,
        "configuration_sha256":hashlib.sha256(config).hexdigest(),"engine_fingerprint":engine_fingerprint()}
    with store.transaction() as conn:
        return jobs._existing(conn,portfolio_id,key,request_digest) or jobs._insert(conn,portfolio_id,"source_preview",pinned,key,request_digest,
            fingerprint=input_fingerprint(project))


def _evidence(store,row):
    _,project=store.portfolio(row["portfolio_id"])
    request=json.loads(row["request_json"])
    if request["engine_fingerprint"]!=engine_fingerprint() or input_fingerprint(project)!=row["input_fingerprint"]:
        raise SubmissionError("stale_submission")
    config=configuration_path(store)
    if hashlib.sha256(host_config(config)).hexdigest()!=request["configuration_sha256"]:
        raise SubmissionError("stale_configuration")
    if environment_fingerprint()!=request["environment_sha256"]:
        raise SubmissionError("stale_environment")
    uploads=source_uploads(store,row["portfolio_id"],request["upload_ids"])
    if {r["id"]:r["sha256"] for r in uploads}!=request["upload_hashes"]:
        raise SubmissionError("source_integrity")
    return project,request,[verified_upload(store,r) for r in uploads],config


def execute_preview(store,jobs,row):
    project,request,paths,config=_evidence(store,row)
    contexts=contexts_from_document({"schema_version":1,"inputs":request["contexts"]},len(paths))
    bindings=parse_bindings({"schema_version":1,"bindings":request["bindings"]})
    result=prepare_submission(project,paths,contexts=contexts,bindings=bindings,
        directory=plan_directory(store,row["portfolio_id"],row["id"]),config_path=config,selections=request["selections"],
        operation_id="OP-"+row["id"])
    _evidence(store,row)
    jobs.state(row["id"],"ready",result=result)


def confirm_preview(store,portfolio_id,body,key,owner_id=1):
    _,project=store.portfolio(portfolio_id,owner_id)
    jobs=Jobs(store); request_digest=digest({"kind":"source_commit","request":body})
    with store.transaction() as conn:
        old=jobs._existing(conn,portfolio_id,key,request_digest)
        if old:return old
    preview=jobs.get(portfolio_id,body["preview_id"],owner_id)
    if preview["kind"]!="source_preview" or preview["status"]!="ready" or store.clock()-preview["created_at"]>PREVIEW_SECONDS:
        raise WebError(409,"preview_unavailable","Run a fresh successful source ingestion preview")
    result=json.loads(preview["result_json"])
    if result.get("status")!="awaiting_confirmation" or body["approval_sha256"]!=result.get("approval_sha256"):
        raise WebError(409,"approval_mismatch","Review exact account mappings and approval fingerprint")
    try:
        _evidence(store,preview)
        manifest,plan=load_submission(project,plan_directory(store,portfolio_id,preview["id"]),body["approval_sha256"])
        if submission_summary(manifest,plan)!=result:
            raise SubmissionError("approval_mismatch")
    except ValueError:
        raise WebError(409,"stale_source_preview","Source evidence, configuration or state changed") from None
    pinned={"preview_id":preview["id"],"approval_sha256":body["approval_sha256"],"plan_sha256":result["plan_sha256"],
        "acknowledge_no_reports":body["acknowledge_no_reports"],"preview_created_at":preview["created_at"],
        "configuration_sha256":manifest["configuration_sha256"],"engine_fingerprint":engine_fingerprint()}
    with store.transaction() as conn:
        old=jobs._existing(conn,portfolio_id,key,request_digest)
        if old:return old
        old=conn.execute("SELECT * FROM jobs WHERE portfolio_id=? AND kind='source_commit' AND preview_id=?",(portfolio_id,preview["id"])).fetchone()
        if old:return dict(old)
        if conn.execute("SELECT 1 FROM jobs WHERE portfolio_id=? AND kind IN ('update','record','source_commit') AND status IN (?,?,?,?,?,?)",(portfolio_id,*UNRESOLVED)).fetchone():
            raise WebError(409,"portfolio_busy","Resolve existing financial work first")
        return jobs._insert(conn,portfolio_id,"source_commit",pinned,key,request_digest,preview=preview["id"],fingerprint=preview["input_fingerprint"])


def safe_result(value):
    keys={"operation_id","status","new_records","unresolved_transfers","report_projection_ready","report_published","contributions_calculated","policy"}
    return {k:v for k,v in value.items() if k in keys}


def completed_result(store,row):
    _,project=store.portfolio(row["portfolio_id"])
    request=json.loads(row["request_json"])
    result=recover_submission(project,row["core_operation_id"],request["plan_sha256"])
    return safe_result(result) if result is not None else None


def execute_commit(store,jobs,row):
    completed=completed_result(store,row)
    if completed is not None:
        jobs.state(row["id"],"recorded",result=completed);return
    request=json.loads(row["request_json"])
    if store.clock()-request["preview_created_at"]>PREVIEW_SECONDS or request["engine_fingerprint"]!=engine_fingerprint():
        raise SubmissionError("stale_submission")
    _,project=store.portfolio(row["portfolio_id"])
    config=configuration_path(store)
    if hashlib.sha256(host_config(config)).hexdigest()!=request["configuration_sha256"]:
        raise SubmissionError("stale_configuration")
    result=confirm_submission(project,plan_directory(store,row["portfolio_id"],row["preview_id"]),request["approval_sha256"],
        acknowledge_no_reports=request["acknowledge_no_reports"],config_path=config)
    jobs.state(row["id"],"recorded",result=safe_result(result))


def install_routes(app,store,auth,require_owner):
    prefix="/api/v1/portfolios/{portfolio_id}"

    @app.post(prefix+"/source-ingestion-previews",status_code=202,response_model=JobView)
    def preview(portfolio_id:str,body:SourceIngestionRequest,request:Request,idempotency_key:str|None=Header(default=None),owner=Depends(require_owner)):
        value=body.model_dump()
        value["bindings"]=[{k:v for k,v in item.items() if v is not None} for item in value["bindings"]]
        row=enqueue_preview(store,portfolio_id,value,idempotency_key,owner["owner_id"])
        auth.touch(request.cookies.get(store.settings.cookie_name));return Jobs.view(row)

    @app.post(prefix+"/source-ingestions",status_code=202,response_model=JobView)
    def confirm(portfolio_id:str,body:SourceIngestionConfirmation,request:Request,idempotency_key:str|None=Header(default=None),owner=Depends(require_owner)):
        row=confirm_preview(store,portfolio_id,body.model_dump(),idempotency_key,owner["owner_id"])
        auth.touch(request.cookies.get(store.settings.cookie_name));return Jobs.view(row)

    def resolve_job(portfolio_id,job_id,owner,discard):
        from .worker import job_guard
        from ..locking import LockBusy
        jobs=Jobs(store);row=jobs.get(portfolio_id,job_id,owner["owner_id"])
        if row["kind"]!="source_commit" or row["status"] not in {"needs_review","interrupted","blocked","failed","recorded"}:
            raise WebError(409,"unsafe_recovery","Only inactive source submissions can be reviewed")
        try:
            with job_guard(store,job_id):
                if discard:
                    from ..operations import project_lock
                    from ..source_ingestion import POLICY
                    _,project=store.portfolio(portfolio_id,owner["owner_id"])
                    with project_lock(project):
                        saved=next((r for r in list_operations(project) if r["operation_id"]==row["core_operation_id"]),None)
                        request=json.loads(row["request_json"])
                        expected={"type":"source_v2_canonical_ingestion","plan_sha256":request["plan_sha256"],"policy":POLICY}
                        if saved is not None and (saved["status"]!="data_failed" or saved["request"]!=expected):
                            raise WebError(409,"unsafe_discard","An existing financial operation requires receipt recovery or review")
                        jobs.state(job_id,"cancelled",error="uncommitted_submission_discarded")
                else:
                    result=completed_result(store,row)
                    if result is None:raise WebError(409,"completion_not_proven","No matching completed receipt exists")
                    jobs.state(job_id,"recorded",result=result)
        except LockBusy:
            raise WebError(409,"job_busy","The source submission is still active") from None
        except SubmissionError:
            raise WebError(409,"completion_not_proven","The financial operation requires review") from None
        return Jobs.view(jobs.get(portfolio_id,job_id,owner["owner_id"]))

    @app.post(prefix+"/source-ingestions/{job_id}/recover",response_model=JobView)
    def recover(portfolio_id:str,job_id:str,owner=Depends(require_owner)):
        return resolve_job(portfolio_id,job_id,owner,False)

    @app.post(prefix+"/source-ingestions/{job_id}/discard",response_model=JobView)
    def discard(portfolio_id:str,job_id:str,owner=Depends(require_owner)):
        return resolve_job(portfolio_id,job_id,owner,True)
