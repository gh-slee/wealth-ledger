# Self-hosted web app: architecture and implementation contract

Status: **shared services and API import/report jobs implemented; full browser app
not available yet**. WEB-002 provides trusted-host owner setup, opaque sessions,
portfolio/settings APIs and registered artifact downloads. WEB-003 adds bounded
uploads, offline preview, explicit confirmation and isolated durable report jobs.
See the [implemented import/job protocol](web-imports.md). Image/Compose recipes
and runtime tests exist; Linux/arm64 image/restart and Compose replacement
acceptance passed locally, including the worker upload/report flow. Runnable native commands/endpoints are in [Web operations](web-operations.md). Other APIs/job/UI/
backup states below remain planned unless marked implemented. The normal financial
workflow remains the CLI. See [TODO](../TODO.md).

## Product and stack boundaries

Version one targets one host and one owner/household per instance with multiple
independent portfolios. The owner manages all portfolios. Portfolio data/settings
are isolated; fine-grained family-member permissions and multitenant SaaS are outside
this scope.

| Layer | Selected direction |
|---|---|
| Browser | React + TypeScript + Vite |
| UI | Tailwind CSS + shadcn/ui |
| Navigation and server state | React Router + TanStack Query |
| Tables and charts | TanStack Table + Apache ECharts |
| API | FastAPI + Pydantic + versioned OpenAPI contracts |
| Finance and reporting | Existing Python services shared by CLI and worker |
| Storage | SQLite plus immutable source/report files |
| Runtime | Docker Compose: web/API and one Python worker |
| Exports | ODS, Markdown, PDF, PNG, CSV and JSON |

Node tools are for development/image builds only. Python serves the API/static
frontend and background work in production. Runtime needs no LLM, Codex, Node server,
local LibreOffice or maintainer portfolio. Preserve en-CA/zh-TW/zh-CN.

Retain current Wealthsimple/Bull formats, CAD/USD securities, CAD/USD/TWD equivalents
and America/Toronto financial dates. The plugin SDK and additional currencies/regions
remain independent roadmap items; a Web UI does not implement them automatically.

## Shared services and private workspaces

**WEB-001 implemented:** daily CLI `--workspace`, `ApplicationService`, extracted
package publisher, bundled/private alias provenance and writable chart caches.
Synthetic tests cover isolation, recovery, copy equivalence and ODS/MD/PDF with an
OS-read-only code tree. No private ledger has been migrated. WEB-002 adds the
optional HTTP/auth/metadata foundation; jobs/UI and adoption remain later stages.

CLI and worker call Python application services independent of HTTP/React: detection,
preview, backup, locking, data submission, analysis, report validation/publication.
Extract the publisher from CLI and pass the workspace explicitly; do not rewrite
module-global PROJECT values or shell out to a CLI for each HTTP request.

- `code_root`: read-only code, fonts, locales, report resources and official registry.
- `workspace_root`: per-portfolio SQLite, original inputs, FX/BTC/ETF evidence,
  reports, backups, operations and local settings.
- Bundled company aliases/resources come from code_root. Private overrides require
  explicit schemas, versions, precedence and hashes.
- CLI supports explicit workspace selection and legacy checkout-local use. Daily
  commands, backup, operation inspection/resume and preview share the resolver.
- Invalid workspaces fail rather than silently choosing another ledger. Web accepts
  server-managed portfolio IDs, not arbitrary host paths.
- Chart/font caches are private writable resources. External workspaces must generate
  all three reports with a read-only code tree.

Target volume layout:

```text
/data/
  admin/app.sqlite3
  admin/queue.sqlite3
  secrets/
  uploads/<portfolio-id>/<upload-id>.csv
  portfolios/<portfolio-id>/
    config/local.toml
    data/db/portfolio.sqlite3
    data/raw/
    data/fx/
    data/prices/
    reports/
    backups/
    work/
  cache/
```

Owner/session/portfolio registry/upload/job/artifact metadata use separate app.sqlite3;
Web migrations do not run against the financial DB. Huey uses queue.sqlite3. These
are files, not three database services. The existing core manages each ledger.
SQLite requires a same-host local volume; NFS, multi-host sharing and horizontal
scaling are not supported claims.

## Authentication and authorization

Use an owner password and **server-side opaque session**.

- Initialize the owner through a trusted host/container CLI. No public registration
  or unauthenticated instance-claim page.
- Use Argon2id through a maintained password library; save only hashes and never
  log/return passwords.
- Session IDs are sufficiently long random values. Store token hashes/expiry in
  the DB. Cookies use HttpOnly/SameSite=Lax and Secure for HTTPS.
- Default idle limit: 30 minutes; absolute limit: 12 hours. Progress polling does
  not extend idle time. Rotate on login; revoke on logout/password change/host reset.
- React/API share an origin. Mutations use appropriate methods, CSRF tokens and
  Origin checks. SameSite is not the only protection.
- Include login/logout in CSRF/origin validation. Login throttling must not trust
  unverified forwarded IP headers.
- Initial scope needs no JWT/refresh-token service, external identity provider or
  email service. Host CLI password reset revokes existing sessions.
- Every portfolio API, source download, JSON/chart/report/ZIP requires authentication
  and portfolio ownership checks. Artifact IDs do not grant access.
- No credentials/persistent financial cache in browser localStorage. TanStack Query
  keys include portfolio/report IDs; logout clears/aborts cached requests, and
  switching portfolios must not display the prior portfolio's data.

Web passwords do not encrypt storage: SQLite remains unencrypted. Implement auth
with maintained components, explicit expiry and security tests. FastAPI's JWT
example does not prescribe this project's session policy.

## Upload, preview and submission

1. After login, select a portfolio and upload either supported CSV or one of each,
   or provide an optional explicitly dated BTC total. Bull opening declarations and
   reference JSON have explicit upload kinds; cash-flow forms remain WEB-006.
2. Stream to isolated upload storage. Original filenames are metadata; server-generated
   IDs determine paths. Limits: 10 MiB per CSV, 25 MiB per batch, 64 KiB per reference
   JSON. API and worker both validate size, encoding and row limits.
3. Detect by content and reject unknown/ambiguous formats. No ZIP/executable uploads
   or parser installation from CSV URLs.
4. Run the existing offline preview in the worker. Show duplicates/revisions, source
   dates/carried data, account scope, BTC gaps and pending references. Preview never
   writes the financial ledger/formal operation or downloads quotes/official holdings.
5. Confirmation binds upload hashes, request digest and ledger input fingerprint.
   Changed ledger inputs invalidate preview. Missing references may be pending;
   blocked requests cannot commit.
6. Formal jobs validate, lock, back up and call shared services. Update the latest
   successful pointer only after generating and validating the complete report bundle.

Show source-uploaded, data-committed and report-published states separately. Missing
CSVs do not prove zero activity; preserve irregular/carried-source semantics. First
Bull import never assumes zero opening, and new CSVs never recalculate a saved opening/balance.

Introduce Web forms for BTC balances/events, contributions, coverage and openings
in stages; the CLI remains available. Event attribution uses balance IDs, with
expected revision/reason for corrections/voids. Do not auto-classify gaps as fees/contributions.

## Background jobs and recovery

Start with **Huey + SQLite storage**, a separate worker process and one execution
process per instance. Two services, with no mandatory Redis. Persisted app.sqlite3
job state is the user-visible record; the queue is neither ledger nor completion proof.

Save portfolio ID, upload hashes, versioned request, idempotency key, core operation
ID, fixed execution/valuation context, status and artifact IDs. Reject the same key
with different requests. Queue messages carry only internal job IDs; external requests
cannot supply serialized tasks, pickle, callables or shell commands.

- Persist job/core-operation linkage before commit-capable execution. Reconcile
  interruptions across DB/queue boundaries; three SQLite files have no shared transaction.
- Main states: `queued -> running -> data_committed -> published`; preview has separate
  states. Also support `blocked`, `failed`, `report_failed`, `interrupted`, `needs_review`.
- If data committed but reporting failed, resume the saved operation/cutoff without
  reimporting or creating a balance at the current time.
- If core published before Web state updated, verify operation/artifact manifests
  and reconcile success without generating another edition.
- Unprovable commit state becomes needs_review with bounded recovery procedures;
  never guess success/failure and rerun automatically.
- Restart reconciles app jobs/core operations/queue. Missing queue notifications may
  be resent; queue retries alone do not establish exactly-once execution.
- Serialize writes per portfolio. CLI/worker share same-host OS advisory locks or
  verifiable owner tokens across containers. PIDs are diagnostic, not lock-removal proof.
- Render in process isolation to prevent Matplotlib/locale state contamination.
  More workers require renewed lock/resource/execution-limit acceptance.
- Poll progress initially; no WebSocket requirement. Cancellation applies only at
  safe boundaries and never reverses committed data.

Async request handling is allowed. FastAPI BackgroundTasks or a thread pool cannot
replace durable jobs/recovery contracts.

## Pages, queries and exports

- Dashboard, holdings/accounts, sources/dates, company/sector/country exposure,
  history, BTC/flows, jobs, report library and settings.
- Read-only pages/charts use a selected published frozen payload. Viewing creates
  no valuation, observation, official download or report. Retain the old published
  edition and show pending when a new commit has not produced reports.
- Financial amounts/quantities/ratios travel as Decimal strings; unknown is null.
  The frontend formats/sorts/plots; float conversion is limited to chart coordinates,
  never the financial source of truth.
- Preserve incomplete/carried-source flags and actual dates. Missing months are not
  fake observations; asset changes are not flow-adjusted returns.
- Handle XSS/formula injection in custom ECharts tooltip HTML, Markdown previews and
  CSV exports. Original CSV downloads retain original bytes and identify raw evidence.
- Resolve artifacts through a report registry with bounded relative paths and
  manifest/checksum checks. Reject traversal, cross-portfolio access and unexpected
  symlinks. No private files under public static/media routes.
- Preserve ODS/MD/PDF formulas/caches/fonts/charts/validation. Expose existing detailed
  CSV/JSON, position/history/flow exports and selected report ZIPs with auditable scope/unknowns.
- Web locales share IDs/terms; source names/references/machine keys remain verbatim.
  Retain existing precision, timing, cost and completeness policies.

Target namespace: `/api/v1`, grouped by auth, portfolios, uploads/previews, jobs,
reports/artifacts, balances/events, flows and settings. Fix schemas/errors/generated
TS clients with tests at each stage; unavailable URLs are not operating instructions.

## Persistence, backup and restore

A named volume preserves all `/data` through ordinary image/container replacement.
Persistence is not off-device backup. Explain volume deletion and never present
commands that delete data as routine upgrades.

Full instance backups include Web/financial databases, original CSV/reference
evidence, all report history/settings, necessary secrets/version metadata, uploads
and recoverable job links. Backups containing keys/password hashes are private,
separate from shareable report/data exports.

1. Enter maintenance mode, block Web/CLI writes/new worker claims and drain running
   jobs to safe boundaries.
2. Acquire instance/portfolio locks. Use SQLite backup API for consistent snapshots,
   and copy immutable evidence/reports rather than live DB files.
3. Record schema/code versions, relative paths, per-file SHA-256, DB integrity/foreign-key
   checks, logical ledger fingerprints and backup scope.
4. Finish atomically and validate before leaving maintenance. Save/download to a
   separate destination; retention must not automatically delete original evidence.
5. Restore into a new empty volume/directory after validating archive paths, sizes,
   hashes, versions and relationships; never overwrite an active ledger.
6. Revoke restored sessions and reconcile/recover jobs without reimporting committed
   inputs. Keep backup financial content intact; record auth revocation separately.

Version one uses explicit manual backup; scheduling is separate. SQLite remains
unencrypted; disk/backup protection is the deployer's responsibility.

## Adopt an existing CLI ledger

Use **copy, verify, switch**, retaining the source.

- Stop source writes; create a DB backup through a read-only connection. Copy raw
  evidence, historical reports, configuration and recovery files.
- Preserve account/snapshot/order/balance/event/source IDs, revisions, original bytes/
  hashes, frozen FX/prices, opening quantities, reports, locale and cost policy.
- Compare schemas, rows, relationships and logical fingerprints. SQLite backup bytes
  may differ, so a file hash alone cannot establish financial equality.
- Retain original paths in audit metadata. Use separate validated relative runtime
  mappings in the new workspace, without rewriting manifests or accepting browser host paths.
- Reconcile unfinished submissions first. Proven committed operations resume reporting
  with saved context; uncertain interruptions remain needs_review.
- No CSV reimports, historical recalculation, new baselines or contributions. Failed
  switching leaves the old CLI workspace usable. Real private adoption is explicit.

## Docker and publication

- Use one versioned image with separate web/worker commands. A multi-stage frontend
  build produces static assets for the Python runtime.
- Non-root runtime, read-only code and explicit writable temp/cache locations;
  never mount the Docker socket.
- Bind loopback by default. Define HTTPS/reverse-proxy/trusted-host/cookie contracts.
  Secrets live in private files/volumes, not images, source or Vite environment values.
- Bundle fonts/components/charts; no third-party CDN/telemetry. Use existing official
  ETF/quote/FX registries without sending private accounts/amounts as request payloads.
- `.dockerignore` plus explicit Dockerfile COPY allowlists exclude databases, raw
  inputs, private reports/backups/settings/credentials, .git and work files.
- Clean public/synthetic CI validates image contents and restart persistence. Public
  images require appropriate tests/authorization; never build arbitrary context
  from a maintainer's full private checkout.
- Use reviewed/tested feature branches and PRs, privacy/history checks and no automatic
  merge. README keeps Web functionality explicitly planned until implemented.

## Staged implementation and acceptance

| ID | Deliverable | Acceptance |
|---|---|---|
| WEB-001 (implemented) | Workspace resolver/shared service | External daily CLI workspace, legacy compatibility, isolated ledgers, three formats with read-only code, logically identical synthetic adoption |
| WEB-002 (foundation accepted locally) | FastAPI/auth/metadata/Compose | Login/logout/revocation/CSRF/throttling/portfolio/path tests, no unauthenticated owner claim, persistent settings |
| WEB-003 (accepted locally) | Upload/preview/Huey/recovery | No duplicate submission, stale preview rejection, kill/restart at commit boundaries, report-only recovery, uncertain state fails closed |
| WEB-004 | React analysis/report library | Three currencies/locales, gaps/unknown/carried flags, cache clearing on switch/logout, desktop/mobile/keyboard/tooltip acceptance |
| WEB-005 | Exports/consistent backup/restore | Three formats match payload; protected downloads; raw evidence/logical finances preserved after empty-volume restore |
| WEB-006 | Advanced forms/adoption | BTC opening/balance/event IDs, attribution/revisions/voids, flows/coverage and CLI/workspace interoperability |
| WEB-007 | Release/operations | Clean install/upgrade/restart/off-device restore, image privacy, platform smoke tests, locked dependencies/licenses and complete guide |

Use independent PRs/acceptance per stage, not one blanket completion. Preserve CLI
tests and financial invariants. All screenshots, CI, demos and benchmarks use
synthetic data; real personal ledgers are not fixtures.

## Official references

- [FastAPI password hashing](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/): maintained libraries; the JWT example does not override the server-side-session decision.
- [Huey guide](https://huey.readthedocs.io/en/stable/guide.html): SQLite storage/consumer/tasks; recovery additionally follows this design's job/operation contract.
- [SQLite backup API](https://www.sqlite.org/backup.html): consistent DB copies.
- [Docker volumes](https://docs.docker.com/engine/storage/volumes/): persistent storage outside containers.
- [React Router SPA](https://reactrouter.com/how-to/spa), [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview): routing/server state.
