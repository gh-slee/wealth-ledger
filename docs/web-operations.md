# Web API: operation and acceptance

The optional API implements owner sessions, independent portfolios/settings, bounded
CSV/reference uploads, offline preview, explicit confirmation, isolated durable
report jobs and protected artifact downloads. React analysis/report pages are implemented; advanced
financial forms and full backup/adoption remain planned. The CLI stays available.
See the [upload/job protocol and recovery guide](web-imports.md). See [the staged design](self-hosted-webapp.md)
and [TODO](../TODO.md). Production features do not use an LLM.

Native HTTP startup/restart and synthetic security tests pass. Docker image
startup/restart and Compose health/container-replacement tests have also passed
locally on Linux/arm64 using Docker Desktop. This accepts the WEB-002 foundation;
it does not establish wider platform/release acceptance or a complete investment app.
WEB-003 additionally passes synthetic transaction/process interruption tests and
Compose CSV/preview/worker-report persistence acceptance; see [imports/jobs](web-imports.md).

## Optional installation and native startup

The financial CLI still installs from `requirements.lock` without FastAPI. API users
install the separate locked dependency set, using Python 3.12+ from a source checkout:

```bash
python -m pip install -r requirements-web.lock
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" init-owner
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" serve
```

`init-owner` requires a new empty dedicated directory (created if missing) or an
already initialized instance. It prompts twice for a 14-256 character password.
The default username is `owner`; `--username` selects a stable ASCII name when
initializing. Repeating initialization cannot overwrite an owner. Initialization is
only a trusted host command; there is no HTTP registration/claim endpoint.

Open `http://localhost:8000/` for the built dashboard and `/healthz` for a minimal
readiness response. Native source checkouts need `npm --prefix frontend ci --ignore-scripts`
and `npm --prefix frontend run build` first; Docker builds static assets automatically.
See [the browser manual](web-frontend.md). API docs/OpenAPI are authenticated; public Swagger/Redoc/CDN
pages are disabled. The public origin defaults to `http://localhost:8000` and must
match the browser exactly. Use `--public-origin` or `WEALTH_LEDGER_PUBLIC_ORIGIN`
for another origin; the host/port must match requests. Non-loopback origins require
HTTPS. `serve --host`/`--port` control the listener independently for reverse proxies.

`WEALTH_LEDGER_DATA_ROOT` is an alternative to `--data-root`. There is **no** fallback
to a checkout-local or maintainer ledger. The Web root must be outside the code
checkout, not the home/filesystem root. CLI data cannot be adopted by pointing the
API at an existing nonempty ledger. Formal copy/verify/switch remains WEB-006.

## Authentication protocol

The browser/API share one origin. A client uses this sequence:

1. `GET /api/v1/auth/csrf`: obtain a bounded anonymous HttpOnly cookie and CSRF token.
2. `POST /api/v1/auth/login`: JSON `username`/`password`, cookie, exact `Origin` and
   `X-CSRF-Token`. Login rotates the cookie and returns the authenticated CSRF token.
3. Send the new cookie on queries; include `Origin`/`X-CSRF-Token` on every mutation,
   including logout/password changes. A new `GET auth/csrf` retrieves the token for
   the current session without extending its lifetime. Store it only in memory.
4. `POST /api/v1/auth/activity` records deliberate user activity. Polling/session/
   portfolio queries do not extend the 30-minute idle deadline. Absolute expiry is
   12 hours regardless of activity; anonymous tokens last 10 minutes.
5. `POST /api/v1/auth/logout` revokes the current session and expires its cookie.
   Password change/reset revokes all sessions; clients must sign in again.

A native API exploration example keeps credentials out of shell arguments/history:

```python
import getpass
import http.cookiejar
import json
import urllib.request

origin = "http://localhost:8000"
client = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
)

def call(path, payload=None, csrf=None):
    headers = {"Origin": origin}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        origin + path, headers=headers,
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    with client.open(request) as response:
        return json.load(response)

csrf = call("/api/v1/auth/csrf")["csrf_token"]
login = call("/api/v1/auth/login", {
    "username": input("Owner username: "),
    "password": getpass.getpass("Owner password: "),
}, csrf)
portfolio = call("/api/v1/portfolios", {"name": "My portfolio"}, login["csrf_token"])
print(portfolio["id"])
```

No credentials/financial response cache belongs in browser localStorage. The React
implementation cancels/clears requests and queries on logout, authentication expiry
and portfolio switching; its financial state stays only in memory.

## Available API

All listed portfolio/settings/artifact/OpenAPI endpoints require the owner session.
Mutations also require CSRF/Origin validation. All responses are `no-store, private`.
Amounts in financial responses remain Decimal strings, never float truth.

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Minimal readiness, no financial/owner details |
| `GET /api/v1/auth/csrf` | Anonymous/current session CSRF bootstrap |
| `POST /api/v1/auth/login` | Password verification and session rotation |
| `GET /api/v1/auth/session` | Owner/session deadlines without extending idle time |
| `POST /api/v1/auth/activity` | Deliberate activity; body may be empty |
| `POST /api/v1/auth/logout` | Revoke current session |
| `POST /api/v1/auth/password` | `current_password`/`new_password`; revoke all sessions |
| `GET, POST /api/v1/portfolios` | List/create independent portfolios |
| `GET /api/v1/portfolios/{id}` | Portfolio metadata, no host paths |
| `GET, PUT /api/v1/portfolios/{id}/settings` | `locale` and `btc_cost_policy` |
| `GET /api/v1/portfolios/{id}/reports` | Published editions, scoped cursor pagination and registered filenames |
| `GET /api/v1/portfolios/{id}/reports/{report_id}?locale=en-CA` | Hash-verified frozen analysis; no imports, reference fetches or revaluation |
| `GET /api/v1/portfolios/{id}/artifacts` | Registered artifact metadata only |
| `GET /api/v1/portfolios/{id}/artifacts/{artifact_id}` | Scoped attachment with size/hash validation |
| `GET /api/v1/openapi.json` | Versioned authenticated schema |

New portfolios default to `en-CA`/`actual_only`. Settings support `en-CA`, `zh-TW`,
`zh-CN`, and the explicit `bull_average_proxy` opt-in. They are stored in that
portfolio's `config/local.toml`; unrelated TOML sections are retained. Invalid or
unsupported inline configuration fails without overwriting it. Settings honor the
same CLI portfolio lock; they do not regenerate reports or create financial records.

IDs and filesystem mappings are server-owned. Requests cannot choose a workspace,
raw host path or owner ID. Each portfolio lives at `<instance>/portfolios/<id>` and
can later be used with the existing CLI's explicit `--workspace`. Creating one does
not initialize a financial database or import any data.

Artifact registration is a **trusted internal worker hook**, separate from source
uploads. It accepts retained `reports/` or `data/raw/` files and
stores SHA-256/size/media type. Downloads are owner/portfolio scoped, reject traversal
and symlinks, check the bytes before returning them, use attachment names generated
from artifact IDs, and cap a file at 64 MiB. No unregistered local report is
implicitly published. Completed worker bundles are verified and registered with the
published job in one metadata transaction. The browser report library lists registered frozen editions; ZIPs/streaming
exports remain WEB-005.

Errors use `{"error":{"code":"...","message":"...","request_id":"..."}}`.
Validation responses do not echo passwords, supplied values or filesystem errors.
This foundation uses English API messages/stable codes; the UI translates
codes through its three-locale presentation layer. No account data is placed in logs.

## Password reset and session storage

```bash
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" reset-password
```

A reset prompts on the host and revokes all sessions. `--password-stdin` is available
for controlled automation using a private input pipe/file, never a password argument
or environment variable. Only hashes are stored in `admin/app.sqlite3`; opaque
session tokens are random and stored as SHA-256 hashes. CSRF HMAC uses the private
32-byte `secrets/csrf.key`. Missing/invalid instance secrets fail closed, not silent
rotation. Keep the complete instance/secret directory private and backed up.
SQLite remains unencrypted. Full consistent backup/restore is WEB-005.

Login budgets persist in metadata: five attempts per transport peer/15 minutes,
20 per instance/15 minutes, reset on successful login. CSRF creation is limited to
60 new anonymous sessions per peer/five minutes. Password changes are throttled;
at most two Argon2 operations run concurrently per API process. Forwarded IP/host/
protocol headers are not trusted. Behind a reverse proxy, users may share a peer
budget; explicit trusted-proxy support is future work. Host reset clears budgets.

## Experimental Docker contributor recipe

The base image is digest-pinned; dependencies have an optional Web lock. Runtime is
UID/GID 10001, read-only code, dropped capabilities and a writable `/data` named volume.
Compose binds only `127.0.0.1:8000`; it mounts no host checkout or Docker socket.
Compose has an API service and one separate worker, sharing the private volume.
The worker starts after API health and executes each job in a fresh subprocess.

Prepare the context from audited source, then run acceptance when Docker is available:

```bash
python scripts/docker_context.py --output work/docker-context
WEALTH_LEDGER_DOCKER_TEST=1 PYTHONPATH=src python -m unittest discover -s tests -p 'test_web_docker.py' -v
```

The helper refuses existing output paths and includes only code, locked dependencies,
bundled fonts/company aliases and licenses. It scans input content and emits a
source manifest. `.dockerignore` denies by default; Dockerfile uses explicit COPY
paths. Neither tool uploads/pushes an image. For later rebuilds choose a fresh context
and set `WEALTH_LEDGER_BUILD_CONTEXT` to it. Do not use a private workspace as context.

The foundation's local startup sequence is:

```bash
docker compose build
docker compose run --rm -it web init-owner
docker compose up -d
```

The image serves the built browser UI at the configured origin. Broader release
and platform acceptance remain WEB-007.
Use `docker compose run --rm -it web reset-password` for a trusted host reset.
`docker compose down` retains the named volume. Volume deletion removes private
state and is never a routine upgrade step. Image/container replacement is not an
off-device backup. Do not mount the old CLI directory as `/data` to migrate it.

For HTTPS behind a reverse proxy, set the exact HTTPS public origin and preserve
the public Host header. The upstream listener may remain HTTP on loopback; Uvicorn
ignores forwarded headers. HTTPS-origin cookies use Secure and `__Host-` naming;
plain HTTP is accepted only for explicit loopback origins. Deployment beyond this
foundation requires the remaining Web acceptance stages.

## Contributor checks and remaining acceptance

```bash
python -m pip install -r requirements-web-test.lock
PYTHONPATH=src python -m unittest discover -s tests -v
python scripts/check_language.py
python scripts/check_publication.py --worktree
```

Normal discovery skips the opt-in Docker runtime test; Web tests skip if optional
dependencies are absent. CI installs the Web test lock and has a separate Docker
job. Container tests create unique synthetic image/container/volume names and remove
only those resources. They exercise non-root/read-only startup, login, portfolio
settings, image privacy and restart persistence. A second test renders the repository
Compose model into a uniquely named synthetic project, verifies health/non-root/
read-only/mount boundaries, replaces the container and checks session/settings
persistence. Only test listener/context/resource names and timing/restart behavior
are overridden; production service security settings remain in place. Native HTTP
restart acceptance runs without Docker. Do not substitute a real ledger for these tests.

Pending gates: remote CI for this scope, broader export/backup workflows,
full backup/adoption, resource/crash tests and wider release/platform/security
acceptance. Local container acceptance covers Linux/arm64; it does not claim
Linux/amd64 CI or every Docker host has passed. No dependency/source check proves
the absence of all possible sensitive values. Review concrete staged content/history before publication.

Official implementation references:
[FastAPI security libraries](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/),
[Starlette middleware](https://www.starlette.io/middleware/),
[Docker build contexts](https://docs.docker.com/build/concepts/context/).
The project intentionally uses opaque sessions rather than the tutorial's JWT flow.
