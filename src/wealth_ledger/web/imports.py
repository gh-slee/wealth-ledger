"""Typed upload/preview/job API; no caller-selected filesystem paths or task code."""
from contextlib import closing
from typing import Literal

from fastapi import Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .jobs import Jobs
from .storage import WebError
from .uploads import receive_upload, get_upload, verified_upload


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PreviewRequest(Input):
    upload_ids: list[str] = Field(default_factory=list, max_length=5)
    kind: Literal["baseline", "monthly", "interim"] = "monthly"
    btc_balance: str | None = Field(default=None, max_length=40, pattern=r"^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,8})?$")
    btc_balance_as_of: str | None = Field(default=None, max_length=40)
    btc_balance_source: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"^[^\x00-\x1f\x7f]+$")
    as_of: str | None = Field(default=None, max_length=40)
    wealthsimple_only: bool = False
    render_saved: bool = False

    @model_validator(mode="after")
    def validate_context(self):
        from ..prices import parse_time
        from ..wallet import quantity
        if self.btc_balance is not None:
            quantity(self.btc_balance)
            if self.btc_balance_as_of is None:
                raise ValueError("BTC totals require an explicit observation time")
        elif self.btc_balance_as_of is not None or self.btc_balance_source is not None:
            raise ValueError("Balance time/source require a BTC total")
        for value in (self.btc_balance_as_of, self.as_of):
            if value is not None:
                parse_time(value)
        return self


class Confirmation(Input):
    preview_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class UploadView(Input):
    id: str
    kind: str
    provider: str | None
    original_name: str
    sha256: str
    byte_size: int
    created_at: float


class UploadList(Input):
    uploads: list[UploadView]


class JobView(Input):
    id: str
    kind: str
    status: str
    created_at: float
    updated_at: float
    execution_at: str
    preview_id: str | None
    core_operation_id: str | None
    error_code: str | None
    result: dict[str, JsonValue] | None


class JobList(Input):
    jobs: list[JobView]


def upload_view(row):
    return {key: row[key] for key in UploadView.model_fields}


def install_import_routes(app, store, auth, require_owner):
    from .source_plans import install_source_plan_routes
    install_source_plan_routes(app, store, auth, require_owner)
    jobs = Jobs(store)
    prefix = "/api/v1/portfolios/{portfolio_id}"

    def touch(request):
        auth.touch(request.cookies.get(store.settings.cookie_name))

    @app.post(prefix + "/uploads", status_code=201, response_model=UploadView)
    async def upload(portfolio_id: str, request: Request,
                     kind: Literal["csv", "fx", "price", "opening", "cash_flows", "source_csv"] = Query(default="csv"),
                     filename: str = Query(default="source.csv", min_length=1, max_length=160),
                     owner=Depends(require_owner)):
        row = await receive_upload(store, portfolio_id, request, kind, filename, owner["owner_id"])
        touch(request)
        return upload_view(row)

    @app.get(prefix + "/uploads", response_model=UploadList)
    def uploads(portfolio_id: str, owner=Depends(require_owner)):
        store.portfolio(portfolio_id, owner["owner_id"])
        with closing(store.connect()) as conn:
            rows = conn.execute("SELECT * FROM uploads WHERE portfolio_id=? ORDER BY created_at DESC,id LIMIT 100", (portfolio_id,)).fetchall()
        return {"uploads": [upload_view(row) for row in rows]}

    @app.get(prefix + "/uploads/{upload_id}", response_class=Response)
    def source(portfolio_id: str, upload_id: str, owner=Depends(require_owner)):
        row = get_upload(store, portfolio_id, upload_id, owner["owner_id"])
        path = verified_upload(store, row)
        return Response(path.read_bytes(), media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="' + row["id"] + path.suffix + '"'})

    @app.post(prefix + "/previews", status_code=202, response_model=JobView)
    def preview(portfolio_id: str, body: PreviewRequest, request: Request,
                idempotency_key: str | None = Header(default=None), owner=Depends(require_owner)):
        row = jobs.preview(portfolio_id, body.model_dump(), idempotency_key, owner["owner_id"])
        touch(request)
        return jobs.view(row)

    @app.post(prefix + "/jobs", status_code=202, response_model=JobView)
    def confirm(portfolio_id: str, body: Confirmation, request: Request,
                idempotency_key: str | None = Header(default=None), owner=Depends(require_owner)):
        row = jobs.confirm(portfolio_id, body.preview_id, idempotency_key, owner["owner_id"])
        touch(request)
        return jobs.view(row)

    @app.get(prefix + "/jobs", response_model=JobList)
    def job_list(portfolio_id: str, owner=Depends(require_owner)):
        return {"jobs": jobs.list(portfolio_id, owner["owner_id"])}

    @app.get(prefix + "/jobs/{job_id}", response_model=JobView)
    def job(portfolio_id: str, job_id: str, owner=Depends(require_owner)):
        return jobs.view(jobs.get(portfolio_id, job_id, owner["owner_id"]))

    @app.post(prefix + "/jobs/{job_id}/cancel", response_model=JobView)
    def cancel(portfolio_id: str, job_id: str, request: Request, owner=Depends(require_owner)):
        row = jobs.cancel(portfolio_id, job_id, owner["owner_id"])
        touch(request)
        return jobs.view(row)

    @app.post(prefix + "/jobs/{job_id}/resume", status_code=202, response_model=JobView)
    def resume(portfolio_id: str, job_id: str, request: Request, owner=Depends(require_owner)):
        row = jobs.resume(portfolio_id, job_id, owner["owner_id"])
        touch(request)
        return jobs.view(row)
