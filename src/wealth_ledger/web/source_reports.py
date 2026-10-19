"""Explicit source-report approvals in the existing isolated Web job lifecycle."""
from contextlib import closing
import hashlib
import json
from typing import Literal

from fastapi import Depends, Header, Request
from pydantic import Field

from ..operations import input_fingerprint
from ..source_context_pipeline import contexts_from_document
from ..source_environment import environment_fingerprint
from ..source_pipeline import host_config, validate_selections
from ..source_publication import prepare_source_report, load_source_report, _summary
from ..source_submission import SubmissionError, parse_bindings
from .imports import Input, JobView
from .jobs import Jobs, PREVIEW_SECONDS, UNRESOLVED, digest, engine_fingerprint
from .source_plans import SourceContext, configuration_path, source_uploads
from .source_submissions import BindingChoice
from .storage import WebError, contained
from .uploads import verified_upload

PIPELINE = "source_report"


class SourceReportValuation(Input):
    as_of: str = Field(min_length=1, max_length=64)
    period_start: str = Field(min_length=1, max_length=64)
    generated_at: str = Field(min_length=1, max_length=64)
    fx: dict[str, str] = Field(max_length=6)
    btc_price: dict[str, str] | None = Field(default=None, max_length=8)
    kind: Literal["baseline", "monthly", "interim"] = "interim"
    btc_cost_policy: Literal["actual_only", "bull_average_proxy"] | None = None
    report_locale: Literal["en-CA", "zh-TW", "zh-CN"] | None = None


class SourceReportRequest(Input):
    upload_ids: list[str] = Field(default_factory=list, max_length=5)
    contexts: list[SourceContext] = Field(default_factory=list, max_length=5)
    bindings: list[BindingChoice] = Field(default_factory=list, max_length=200)
    selections: dict[str, str] = Field(default_factory=dict, max_length=5)
    valuation: SourceReportValuation


class SourceReportConfirmation(Input):
    preview_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    approval_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def plan_directory(store, portfolio, preview):
    from .storage import ID
    if not ID.fullmatch(portfolio) or not ID.fullmatch(preview):
        raise WebError(404, "not_found", "Source report preview not found")
    return contained(store.root, "admin/source-reports/" + portfolio + "/" + preview)


def enqueue_preview(store, portfolio, request, key, owner_id=1):
    _, project = store.portfolio(portfolio, owner_id)
    jobs = Jobs(store)
    request_digest = digest({"kind": "source_report_preview", "request": request})
    with store.transaction() as conn:
        old = jobs._existing(conn, portfolio, key, request_digest)
        if old: return old
    rows = source_uploads(store, portfolio, request["upload_ids"], owner_id) if request["upload_ids"] else []
    try:
        if rows:
            contexts_from_document({"schema_version": 1, "inputs": request["contexts"]}, len(rows))
            validate_selections(len(rows), request["selections"])
        elif request["contexts"] or request["bindings"] or request["selections"]:
            raise ValueError("Source context requires CSV inputs")
        parse_bindings({"schema_version": 1, "bindings": request["bindings"]})
        config = host_config(configuration_path(store))
        environment = environment_fingerprint()
    except ValueError:
        raise WebError(422, "invalid_source_request", "Review contexts, bindings and trusted host configuration") from None
    pinned = {**request, "pipeline": PIPELINE, "upload_hashes": {r["id"]: r["sha256"] for r in rows},
              "configuration_sha256": hashlib.sha256(config).hexdigest(), "environment_sha256": environment,
              "engine_fingerprint": engine_fingerprint()}
    with store.transaction() as conn:
        return jobs._existing(conn, portfolio, key, request_digest) or jobs._insert(conn, portfolio, "preview", pinned,
            key, request_digest, fingerprint=input_fingerprint(project))


def evidence(store, row):
    _, project = store.portfolio(row["portfolio_id"])
    request = json.loads(row["request_json"])
    if request.get("pipeline") != PIPELINE or request["engine_fingerprint"] != engine_fingerprint() or input_fingerprint(project) != row["input_fingerprint"]:
        raise SubmissionError("stale_submission")
    config = configuration_path(store)
    if hashlib.sha256(host_config(config)).hexdigest() != request["configuration_sha256"]:
        raise SubmissionError("stale_configuration")
    if environment_fingerprint() != request["environment_sha256"]:
        raise SubmissionError("stale_environment")
    rows = source_uploads(store, row["portfolio_id"], request["upload_ids"]) if request["upload_ids"] else []
    if {r["id"]: r["sha256"] for r in rows} != request["upload_hashes"]:
        raise SubmissionError("source_integrity")
    return project, request, [verified_upload(store, r) for r in rows], config


def execute_preview(store, jobs, row):
    project, request, paths, config = evidence(store, row)
    contexts = contexts_from_document({"schema_version": 1, "inputs": request["contexts"]}, len(paths)) if paths else ()
    result = prepare_source_report(project, paths, contexts=contexts,
        bindings=parse_bindings({"schema_version": 1, "bindings": request["bindings"]}),
        valuation=request["valuation"], directory=plan_directory(store, row["portfolio_id"], row["id"]),
        config_path=config, selections=request["selections"], operation_id="OP-" + row["id"])
    evidence(store, row)
    jobs.state(row["id"], "ready", result=result)


def confirm_preview(store, portfolio, body, key, owner_id=1):
    _, project = store.portfolio(portfolio, owner_id)
    jobs = Jobs(store)
    request_digest = digest({"kind": "source_report_update", "request": body})
    with store.transaction() as conn:
        old = jobs._existing(conn, portfolio, key, request_digest)
        if old: return old
    preview = jobs.get(portfolio, body["preview_id"], owner_id)
    if (preview["kind"] != "preview" or preview["status"] != "ready"
            or json.loads(preview["request_json"]).get("pipeline") != PIPELINE
            or store.clock() - preview["created_at"] > PREVIEW_SECONDS):
        raise WebError(409, "preview_unavailable", "Run a fresh successful source report preview")
    result = json.loads(preview["result_json"])
    if result.get("status") != "awaiting_confirmation" or body["approval_sha256"] != result.get("approval_sha256"):
        raise WebError(409, "approval_mismatch", "Review exact source report inputs and approval fingerprint")
    with closing(store.connect()) as conn:
        old = conn.execute("SELECT * FROM jobs WHERE portfolio_id=? AND kind='update' AND preview_id=?",
                           (portfolio, preview["id"])).fetchone()
        if old: return dict(old)
    try:
        evidence(store, preview)
        manifest, _ = load_source_report(project, plan_directory(store, portfolio, preview["id"]), body["approval_sha256"])
        if _summary(manifest) != result: raise SubmissionError("approval_mismatch")
    except ValueError:
        raise WebError(409, "stale_source_preview", "Source evidence, settings or environment changed") from None
    pinned = {"pipeline": PIPELINE, "preview_id": preview["id"], "approval_sha256": body["approval_sha256"],
              "preview_created_at": preview["created_at"], "engine_fingerprint": engine_fingerprint()}
    with store.transaction() as conn:
        old = jobs._existing(conn, portfolio, key, request_digest)
        if old: return old
        old = conn.execute("SELECT * FROM jobs WHERE portfolio_id=? AND kind='update' AND preview_id=?",
                           (portfolio, preview["id"])).fetchone()
        if old: return dict(old)
        if conn.execute("SELECT 1 FROM jobs WHERE portfolio_id=? AND kind IN ('update','record','source_commit') AND status IN (?,?,?,?,?,?)",
                        (portfolio, *UNRESOLVED)).fetchone():
            raise WebError(409, "portfolio_busy", "Resolve existing financial work first")
        return jobs._insert(conn, portfolio, "update", pinned, key, request_digest, preview=preview["id"],
                            fingerprint=preview["input_fingerprint"], execution=preview["execution_at"])


def execute_update(store, jobs, row, service):
    request = json.loads(row["request_json"])
    if row["core_operation_id"] != "OP-" + row["preview_id"]:
        raise SubmissionError("operation_requires_review")
    saved = next((op for op in service.operations() if op["operation_id"] == row["core_operation_id"]), None)
    callback = lambda operation: jobs.state(row["id"], "data_committed")
    if saved:
        if saved["request"].get("type") != "source_report_update" or saved["request"].get("approval_sha256") != request["approval_sha256"]:
            raise SubmissionError("operation_requires_review")
        service.source_report_resume(row["core_operation_id"], on_data_committed=callback)
    else:
        if store.clock() - request["preview_created_at"] > PREVIEW_SECONDS or request["engine_fingerprint"] != engine_fingerprint():
            raise SubmissionError("stale_submission")
        service.source_report_confirm(plan_directory(store, row["portfolio_id"], row["preview_id"]),
            request["approval_sha256"], config_path=configuration_path(store), on_data_committed=callback)
    from .worker import publish_registry
    from ..operations import project_lock
    with project_lock(service.root):
        publish_registry(store, jobs, row, service, service.operation(row["core_operation_id"]))


def install_routes(app, store, auth, require_owner):
    prefix = "/api/v1/portfolios/{portfolio_id}"

    @app.post(prefix + "/source-report-previews", status_code=202, response_model=JobView)
    def preview(portfolio_id: str, body: SourceReportRequest, request: Request,
                idempotency_key: str | None = Header(default=None), owner=Depends(require_owner)):
        value = body.model_dump()
        value["bindings"] = [{k: v for k, v in item.items() if v is not None} for item in value["bindings"]]
        value["valuation"] = body.valuation.model_dump(exclude_none=True)
        row = enqueue_preview(store, portfolio_id, value, idempotency_key, owner["owner_id"])
        auth.touch(request.cookies.get(store.settings.cookie_name))
        return Jobs.view(row)

    @app.post(prefix + "/source-reports", status_code=202, response_model=JobView)
    def confirm(portfolio_id: str, body: SourceReportConfirmation, request: Request,
                idempotency_key: str | None = Header(default=None), owner=Depends(require_owner)):
        row = confirm_preview(store, portfolio_id, body.model_dump(), idempotency_key, owner["owner_id"])
        auth.touch(request.cookies.get(store.settings.cookie_name))
        return Jobs.view(row)
