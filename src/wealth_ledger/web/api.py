"""Versioned owner API with bounded uploads and durable job contracts."""
from __future__ import annotations

import json
import logging
import re
import uuid

from fastapi import Depends, FastAPI, Request, Response, Security
from fastapi.security import APIKeyCookie
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from typing import Literal

from .auth import Auth, ABSOLUTE_SECONDS, ANONYMOUS_SECONDS
from .config import WebSettings
from .storage import Store, WebError

LOGGER = logging.getLogger("wealth_ledger.web")
MAX_JSON_BYTES = 16 * 1024


def error_response(status, code, message, request_id):
    return JSONResponse({"error": {"code": code, "message": message, "request_id": request_id}}, status_code=status)


class SecurityBoundary:
    """Same-origin boundary, bounded bodies, CSRF and private response headers."""
    def __init__(self, app, *, settings, auth):
        self.app, self.settings, self.auth = app, settings, auth

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from ..locking import LockBusy
        from .maintenance import instance_activity
        try:
            with instance_activity(self.settings.data_root):
                await self._request(scope, receive, send)
        except LockBusy:
            response = error_response(503, "maintenance", "Instance maintenance is in progress", uuid.uuid4().hex)
            response.headers.update({"Cache-Control": "no-store, private", "Retry-After": "30",
                "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"})
            await response(scope, receive, send)

    async def _request(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = False

        async def protected_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in
                           {b"cache-control", b"pragma", b"x-request-id"}]
                headers.extend([(b"cache-control", b"no-store, private"), (b"pragma", b"no-cache"),
                    (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"), (b"content-security-policy", (
                        b"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                        if request.url.path in {"/", "/login", "/app"} or request.url.path.startswith(("/app/", "/assets/"))
                        else b"default-src 'none'; frame-ancestors 'none'")),
                    (b"x-request-id", request_id.encode())])
                if self.settings.secure_cookie:
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message = {**message, "headers": headers}
            await send(message)

        async def reject(status, code, message):
            await error_response(status, code, message, request_id)(scope, receive, protected_send)

        try:
            hosts = request.headers.getlist("host")
            if len(hosts) != 1 or hosts[0].lower() != self.settings.authority:
                return await reject(400, "invalid_host", "Invalid host")
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origins = request.headers.getlist("origin")
                if len(origins) != 1 or origins[0] != self.settings.public_origin:
                    return await reject(403, "origin_rejected", "Invalid origin")
                token = request.cookies.get(self.settings.cookie_name)
                self.auth.require_csrf(token, request.headers.get("x-csrf-token"))
                upload_match = re.fullmatch(r"/api/v1/portfolios/([a-f0-9]{32})/uploads", request.url.path)
                streaming = request.method == "POST" and upload_match is not None
                limit = 10 * 1024 * 1024 if streaming else MAX_JSON_BYTES
                if len(request.headers.getlist("content-length")) > 1:
                    return await reject(400, "invalid_length", "Invalid content length")
                if request.headers.get("content-length"):
                    try:
                        length = int(request.headers["content-length"])
                    except ValueError:
                        return await reject(400, "invalid_length", "Invalid content length")
                    if length < 0 or length > limit:
                        return await reject(413, "body_too_large", "Request body is too large")
                if streaming:
                    owner = self.auth.session(token)
                    if not owner:
                        return await reject(401, "authentication_required", "Authentication required")
                    self.auth.store.portfolio(upload_match[1], owner["owner_id"])
                    total = 0
                    async def bounded_receive():
                        nonlocal total
                        item = await receive()
                        total += len(item.get("body", b""))
                        if total > limit:
                            raise WebError(413, "body_too_large", "Upload is too large")
                        return item
                    await self.app(scope, bounded_receive, protected_send)
                    return
                body = bytearray()
                while True:
                    item = await receive()
                    if item["type"] == "http.disconnect":
                        return
                    body.extend(item.get("body", b""))
                    if len(body) > MAX_JSON_BYTES:
                        return await reject(413, "body_too_large", "Request body is too large")
                    if not item.get("more_body", False):
                        break
                replayed = False
                async def replay_receive():
                    nonlocal replayed
                    if not replayed:
                        replayed = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()
                await self.app(scope, replay_receive, protected_send)
            else:
                await self.app(scope, receive, protected_send)
        except WebError as exc:
            if started:
                raise
            await reject(exc.status, exc.code, exc.message)
        except Exception:
            if started:
                raise
            LOGGER.error("request_failed request_id=%s", request_id)
            await reject(500, "internal_error", "Request could not be completed")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Login(Input):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=256)


class ReportingSettings(Input):
    locale: Literal["en-CA", "zh-TW", "zh-CN"]
    btc_cost_policy: Literal["actual_only", "bull_average_proxy"]


class NewPortfolio(ReportingSettings):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")
    locale: Literal["en-CA", "zh-TW", "zh-CN"] = "en-CA"
    btc_cost_policy: Literal["actual_only", "bull_average_proxy"] = "actual_only"


class PasswordChange(Input):
    current_password: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=14, max_length=256)


class CsrfView(Input):
    csrf_token: str


class LoginView(CsrfView):
    authenticated: Literal[True]


class SessionView(Input):
    authenticated: Literal[True]
    username: str
    expires_at: float
    idle_timeout_seconds: int


class PortfolioView(Input):
    id: str
    name: str
    created_at: float


class PortfolioList(Input):
    portfolios: list[PortfolioView]


class ArtifactView(Input):
    id: str
    report_id: str
    sha256: str
    byte_size: int
    media_type: str


class ArtifactList(Input):
    artifacts: list[ArtifactView]


class ErrorDetail(Input):
    code: str
    message: str
    request_id: str


class ErrorView(Input):
    error: ErrorDetail


def create_app(settings: WebSettings | None = None, *, clock=None, frontend_root=None):
    settings = settings or WebSettings.from_environment()
    store = Store(settings, **({"clock": clock} if clock else {}))
    if not store.owner():
        raise ValueError("Initialize the owner through the host CLI before serving")
    auth = Auth(store)
    app = FastAPI(title="Wealth Ledger API", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None,
                  responses={code: {"model": ErrorView} for code in (400,401,403,404,409,413,422,429,500,503)})
    session_cookie = APIKeyCookie(name=settings.cookie_name, auto_error=False, scheme_name="OwnerSession")
    app.state.store, app.state.auth, app.state.settings = store, auth, settings
    app.add_middleware(SecurityBoundary, settings=settings, auth=auth)

    @app.exception_handler(WebError)
    async def web_error(request, exc):
        return error_response(exc.status, exc.code, exc.message, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Pydantic input/error context can contain passwords or private data.
        return error_response(422, "invalid_request", "Request fields are invalid", request.state.request_id)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(exc.status_code, "not_found" if exc.status_code == 404 else "request_rejected",
                              "Resource not found" if exc.status_code == 404 else "Request rejected", request.state.request_id)

    def require_owner(cookie: str | None = Security(session_cookie)):
        session = auth.session(cookie)
        if not session:
            raise WebError(401, "authentication_required", "Authentication required")
        return session

    def token(request):
        return request.cookies.get(settings.cookie_name)

    def set_cookie(response, value, max_age):
        response.set_cookie(settings.cookie_name, value, max_age=max_age, httponly=True,
                            secure=settings.secure_cookie, samesite="lax", path="/")

    def remove_cookie(response):
        response.delete_cookie(settings.cookie_name, httponly=True, secure=settings.secure_cookie,
                               samesite="lax", path="/")

    @app.get("/healthz")
    def health():
        return {"status": "ready", "api_version": 1}

    @app.get("/api/v1/auth/csrf", response_model=CsrfView)
    def csrf(request: Request, response: Response):
        current = token(request)
        if not auth.session(current, authenticated=False):
            peer = request.client.host if request.client else "unknown"
            current = auth.issue_anonymous(peer)
            set_cookie(response, current, ANONYMOUS_SECONDS)
        return {"csrf_token": auth.csrf(current)}

    @app.post("/api/v1/auth/login", response_model=LoginView)
    def login(body: Login, request: Request, response: Response):
        peer = request.client.host if request.client else "unknown"
        current = auth.login(token(request), body.username, body.password.get_secret_value(), peer)
        set_cookie(response, current, ABSOLUTE_SECONDS)
        return {"authenticated": True, "csrf_token": auth.csrf(current)}

    @app.get("/api/v1/auth/session", response_model=SessionView)
    def session(owner=Depends(require_owner)):
        return {"authenticated": True, "username": owner["username"], "expires_at": owner["expires_at"],
                "idle_timeout_seconds": 1800}

    @app.post("/api/v1/auth/activity", status_code=204)
    def activity(request: Request, owner=Depends(require_owner)):
        auth.touch(token(request))
        return Response(status_code=204)

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request, owner=Depends(require_owner)):
        auth.logout(token(request))
        response = Response(status_code=204)
        remove_cookie(response)
        return response

    @app.post("/api/v1/auth/password", status_code=204)
    def change_password(body: PasswordChange, request: Request, owner=Depends(require_owner)):
        # Password verification is throttled as well as the login endpoint.
        auth.budget("password:" + auth.peer_key(request.client.host if request.client else "unknown"), 5, 900)
        auth.change_password(token(request), body.current_password.get_secret_value(), body.new_password.get_secret_value())
        response = Response(status_code=204)
        remove_cookie(response)
        return response

    @app.get("/api/v1/portfolios", response_model=PortfolioList)
    def portfolios(owner=Depends(require_owner)):
        return {"portfolios": store.portfolios(owner["owner_id"])}

    @app.post("/api/v1/portfolios", status_code=201, response_model=PortfolioView)
    def new_portfolio(body: NewPortfolio, request: Request, owner=Depends(require_owner)):
        if not body.name.strip():
            raise WebError(422, "invalid_request", "Portfolio name cannot be blank")
        result = store.create_portfolio(body.name.strip(), body.locale, body.btc_cost_policy, owner["owner_id"])
        auth.touch(token(request))
        return {key: result[key] for key in ("id", "name", "created_at")}

    @app.get("/api/v1/portfolios/{portfolio_id}", response_model=PortfolioView)
    def portfolio(portfolio_id: str, owner=Depends(require_owner)):
        row, _ = store.portfolio(portfolio_id, owner["owner_id"])
        return {key: row[key] for key in ("id", "name", "created_at")}

    @app.get("/api/v1/portfolios/{portfolio_id}/settings", response_model=ReportingSettings)
    def reporting_settings(portfolio_id: str, owner=Depends(require_owner)):
        return store.reporting_settings(portfolio_id, owner["owner_id"])

    @app.put("/api/v1/portfolios/{portfolio_id}/settings", response_model=ReportingSettings)
    def save_settings(portfolio_id: str, body: ReportingSettings, request: Request, owner=Depends(require_owner)):
        try:
            result = store.save_settings(portfolio_id, body.locale, body.btc_cost_policy, owner["owner_id"])
        except ValueError as exc:
            raise WebError(409, "portfolio_busy", "Portfolio settings are busy; review local operations") from exc
        auth.touch(token(request))
        return result

    @app.get("/api/v1/portfolios/{portfolio_id}/artifacts", response_model=ArtifactList)
    def artifacts(portfolio_id: str, owner=Depends(require_owner)):
        return {"artifacts": store.artifacts(portfolio_id, owner["owner_id"])}

    @app.get("/api/v1/portfolios/{portfolio_id}/artifacts/{artifact_id}", response_class=Response)
    def download(portfolio_id: str, artifact_id: str, owner=Depends(require_owner)):
        raw, media_type, filename = store.read_artifact(portfolio_id, artifact_id, owner["owner_id"])
        return Response(raw, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    from .imports import install_import_routes
    from .reports import install_report_routes
    install_import_routes(app, store, auth, require_owner)
    install_report_routes(app, store, require_owner)
    from .exports import install_export_routes
    install_export_routes(app, store, require_owner)
    from .financial import install_financial_routes
    install_financial_routes(app, store, auth, require_owner)

    @app.get("/api/v1/openapi.json", include_in_schema=False)
    def openapi(owner=Depends(require_owner)):
        return app.openapi()

    from .frontend import install_frontend
    install_frontend(app, frontend_root)
    return app
