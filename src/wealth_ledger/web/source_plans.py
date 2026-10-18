"""Owner-only nonbooking source-plan jobs; no browser-selected code or host paths."""
import hashlib
import json

from fastapi import Depends, Header, Request
from pydantic import Field

from ..operations import input_fingerprint
from ..source_environment import EnvironmentError, environment_fingerprint
from ..source_pipeline import BATCH_BYTES, SourcePlanError, host_config, plan_sources, validate_selections
from .imports import Input, JobView
from .jobs import Jobs, PREVIEW_SECONDS, digest, engine_fingerprint
from .storage import WebError, contained
from .uploads import get_upload, verified_upload


class SourcePlanRequest(Input):
    upload_ids: list[str] = Field(min_length=1, max_length=5)
    selections: dict[str, str] = Field(default_factory=dict, max_length=5)
    previous_plan_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


def configuration_path(store):
    return contained(store.root, "admin/source-parsers.json")


def source_uploads(store, portfolio_id, identifiers, owner_id=1):
    if not 1 <= len(identifiers) <= 5 or len(set(identifiers)) != len(identifiers):
        raise WebError(422, "invalid_request", "Supply distinct source-plan uploads")
    rows = [get_upload(store, portfolio_id, identifier, owner_id) for identifier in identifiers]
    if any(row["kind"] != "source_csv" for row in rows) or sum(row["byte_size"] for row in rows) > BATCH_BYTES:
        raise WebError(422, "invalid_request", "Source plans require bounded source_csv uploads")
    for row in rows:
        verified_upload(store, row)
    return rows


def enqueue_plan(store, portfolio_id, request, key, owner_id=1):
    _, project = store.portfolio(portfolio_id, owner_id)
    jobs = Jobs(store)
    request_digest = digest({"kind": "source_plan", "request": request})
    with store.transaction() as conn:
        existing = jobs._existing(conn, portfolio_id, key, request_digest)
        if existing:
            return existing
    rows = source_uploads(store, portfolio_id, request["upload_ids"], owner_id)
    choices = request["selections"]
    try:
        validate_selections(len(rows), choices)
    except SourcePlanError:
        raise WebError(422, "invalid_request", "Selections require valid input slots and adapter IDs") from None
    previous = None
    if request["previous_plan_id"] is not None:
        prior = jobs.get(portfolio_id, request["previous_plan_id"], owner_id)
        if prior["kind"] != "source_plan" or prior["status"] != "ready" or store.clock() - prior["created_at"] > PREVIEW_SECONDS:
            raise WebError(409, "preview_unavailable", "Supply a recent completed source plan")
        if prior["input_fingerprint"] != input_fingerprint(project):
            raise WebError(409, "stale_preview", "Portfolio changed; create a new source plan")
        previous = json.loads(prior["result_json"])
    try:
        config = host_config(configuration_path(store))
        environment = environment_fingerprint()
    except (SourcePlanError, EnvironmentError):
        raise WebError(422, "source_environment", "Trusted host parser configuration/environment requires review") from None
    pinned = {**request, "upload_hashes": {row["id"]: row["sha256"] for row in rows},
              "configuration_sha256": hashlib.sha256(config).hexdigest(), "environment_sha256": environment,
              "engine_fingerprint": engine_fingerprint(), "previous": previous}
    with store.transaction() as conn:
        existing = jobs._existing(conn, portfolio_id, key, request_digest)
        return existing or jobs._insert(conn, portfolio_id, "source_plan", pinned, key, request_digest,
                                        fingerprint=input_fingerprint(project))


def execute_plan(store, jobs, row):
    _, project = store.portfolio(row["portfolio_id"])
    request = json.loads(row["request_json"])
    try:
        if request["engine_fingerprint"] != engine_fingerprint() or input_fingerprint(project) != row["input_fingerprint"]:
            raise SourcePlanError("stale_plan")
        config = configuration_path(store)
        if hashlib.sha256(host_config(config)).hexdigest() != request["configuration_sha256"]:
            raise SourcePlanError("stale_plan")
        uploads = source_uploads(store, row["portfolio_id"], request["upload_ids"])
        if {item["id"]: item["sha256"] for item in uploads} != request["upload_hashes"]:
            raise SourcePlanError("stale_plan")
        paths = [verified_upload(store, item) for item in uploads]
        value = plan_sources(paths, config_path=config, selections=request["selections"],
                             previous=request["previous"], expected_environment=request["environment_sha256"])
        if input_fingerprint(project) != row["input_fingerprint"]:
            raise SourcePlanError("stale_plan")
        jobs.state(row["id"], "ready", result=value)
    except SourcePlanError as exc:
        jobs.state(row["id"], "blocked", error=exc.code)
    except WebError as exc:
        jobs.state(row["id"], "blocked", error=exc.code)


def install_source_plan_routes(app, store, auth, require_owner):
    prefix = "/api/v1/portfolios/{portfolio_id}"

    @app.post(prefix + "/source-plans", status_code=202, response_model=JobView)
    def source_plan(portfolio_id: str, body: SourcePlanRequest, request: Request,
                    idempotency_key: str | None = Header(default=None), owner=Depends(require_owner)):
        row = enqueue_plan(store, portfolio_id, body.model_dump(), idempotency_key, owner["owner_id"])
        auth.touch(request.cookies.get(store.settings.cookie_name))
        return Jobs.view(row)
