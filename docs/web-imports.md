# Web imports, durable jobs and recovery

The API can import Wealthsimple holdings CSVs, Bull Bitcoin orders CSVs, or both,
and an optional explicitly dated BTC total. It reuses the financial CLI core and
produces ODS, Markdown and PDF reports without an LLM or LibreOffice. The React
workflow is described in [the browser guide](web-frontend.md); this document
specifies its API protocol and recovery behavior.

Follow [Web operations](web-operations.md) for installation, owner authentication,
CSRF, public origin, Docker context and private storage. Use synthetic files first.
Existing CLI portfolios are never automatically adopted; use the explicit [copy/verify/switch host commands](web-adoption.md). No Web instance defaults to a maintainer's ledger.

## Independent parser source plans

An advanced, nonbooking API path accepts `source_csv` uploads and queues
`POST /source-plans` jobs using trusted host parser configuration. It shares the
CLI source-plan runner and environment/config/input digests. It is separate from
financial `/previews`: source plans cannot confirm, resume financially or generate
reports. See [source-plan configuration, API and revalidation](source-adapters.md#nonbooking-source-plans-src-002b).
No browser source-plan form or plugin installation/enable endpoint exists yet.

## Start the two services

Install `requirements-web.lock`, initialize the owner once, then run these in
separate host processes with the same explicit dedicated root:

```bash
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" serve
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" worker
```

For a prepared Docker context/initialized volume:

```bash
docker compose build
docker compose run --rm web init-owner
docker compose up -d
```

Compose uses one versioned local image for `web` and `worker`. Only the API binds
a loopback port. Both use UID 10001, read-only code and `/data`; no host checkout
or Docker socket is mounted. Start exactly one worker per instance, on one host
with local filesystems supporting SQLite and advisory locks. Network filesystems
or multiple hosts are not supported by this acceptance scope.

`worker --once` reconciles interrupted jobs, sends missing notifications and drains
currently queued work before exiting. It is useful for controlled host operation
and tests; the normal service continually checks persisted jobs every five seconds.
An unavailable worker leaves jobs queued. API polling never performs financial work
or extends session idle time.

## Upload and preview

All URLs below have prefix `/api/v1/portfolios/{portfolio_id}` and require the owner
session. Mutations also need exact `Origin` and `X-CSRF-Token`.

| Method/path | Request and result |
|---|---|
| `POST /uploads?kind=csv&filename=export.csv` | Raw bytes, not multipart/base64; returns a server upload ID/hash |
| `GET /uploads` | Latest 100 evidence metadata records |
| `GET /uploads/{upload_id}` | Hash-verified original-byte attachment |
| `POST /previews` | JSON input below plus `Idempotency-Key`; returns queued preview job |
| `GET /jobs` | Latest 100 preview/update jobs |
| `GET /jobs/{job_id}` | State, safe error code and completed result |
| `POST /jobs` | `{"preview_id":"..."}` plus `Idempotency-Key`; confirms formal work |
| `POST /jobs/{job_id}/cancel` | Only queued work; committed data is never reversed |
| `POST /jobs/{job_id}/resume` | Only proven committed/report-failed work; same operation/time |

Upload `Content-Type` is `application/octet-stream`, `text/csv` or `application/json`.
`kind` is `csv`, `fx`, `price` or `opening`; references contain JSON objects. Server
IDs determine paths, while original filenames are metadata. ZIPs, executable files,
unknown/ambiguous CSV headers, invalid UTF-8/NUL and excessive rows are rejected.
Identical kind/bytes in the same portfolio reuse an existing upload record.

Limits are 10 MiB/CSV, 64 KiB/reference, 25 MiB/batch, five files/batch, 50,000 CSV
rows and 256 columns. Supply at most one CSV per supported provider and one JSON
per reference kind. API and worker validate content/hash/limits. A portfolio retains
at most 1,000 uploads/512 MiB; reaching that quota requires trusted local review.
Automatic retention/deletion is not implemented. A disconnected upload can leave
an orphan `.part` after a host crash; it is never an import candidate.

Preview request example (all other options are optional):

```json
{
  "upload_ids": ["SERVER_CSV_ID", "SERVER_FX_ID"],
  "kind": "monthly"
}
```

Optional fields: `btc_balance` as a nonnegative decimal string with satoshi
precision, `btc_balance_as_of` as an explicit timestamp with offset,
`btc_balance_source`, `as_of` for an explicit valuation cutoff, and
`wealthsimple_only`. Numeric JSON BTC values and scientific notation are rejected.
A dated total alone is allowed without CSVs:

```json
{
  "upload_ids": [],
  "btc_balance": "0.01234567",
  "btc_balance_as_of": "2024-02-01T18:00:00-05:00",
  "as_of": "2024-02-01T18:00:00-05:00"
}
```

That total establishes a quantity observation, not acquisition cost or a
contribution. Gaps remain unresolved until supported events are entered through
the existing CLI or [financial declaration forms](web-financial-records.md).

Bull's first import requires an explicit opening declaration. Upload a user-reviewed
`opening` JSON using the schema in [the manual](user-manual.md); the tool never
assumes zero opening from a CSV. `fx` and `price` use the existing verified reference
schemas. Missing offline references may leave a preview ready with
`pending_reference`; formal confirmation may fetch official references using the
existing deterministic code. Viewing/previewing never downloads them.

Use a new 8-128 character ASCII `Idempotency-Key` for each distinct preview or
confirmation. Exact retries return the same job even after completion. Reusing a
key with a different request returns 409. Keys are portfolio scoped. Store returned
job IDs; do not invent core operation IDs or task names.

## Confirmation and reports

Wait for preview `ready`, inspect `result.sources`, actual source/cutoff dates,
`source_usage`, BTC gaps, unknowns, blockers and pending checks, then explicitly
confirm its ID. A `blocked` or expired preview cannot commit. Preview expiry is
24 hours from submission; rerun if the information is no longer current.

Confirmation binds immutable upload hashes, canonical request, application code/
locale signature, frozen execution time and ledger/config/reference/latest-report
fingerprint. Ledger/settings changes require a new preview. The worker rechecks
inside the shared portfolio lock before financial mutation. A redeploy invalidates
unexecuted previews rather than silently applying new code to an old confirmation.

One unresolved formal update per portfolio is allowed; preview jobs can still be
created. Instance active-job capacity is 20. No source CSV means no evidence about
new transactions: existing irregular/carried-source rules remain in effect. New
files never recalculate saved BTC openings or observations. Holdings changes and
purchase spending are not contributions.

Formal flow is `queued -> running -> data_committed -> published`. A published
job returns `report_id`, `artifact_ids`, valuation cutoff and snapshot ID. Use the
existing scoped `GET /artifacts` and `GET /artifacts/{artifact_id}` for original
ODS/MD/PDF, charts, manifests and detailed CSV/JSON. Downloads are private attachments,
not static HTML/Markdown execution. All report bytes are verified before atomic
metadata registration. The [report library](web-analysis-reports.md), scoped ZIP exports and
[complete backups](web-backups.md) use this published registry.

## Queue and process boundaries

`admin/app.sqlite3` is the authoritative user-visible job record; `admin/queue.sqlite3`
is only Huey notification storage. JSON notifications contain a version, notification
UUID and internal job ID. No pickle, browser-supplied task names, callables, shell
commands or financial payloads are accepted by the queue serializer.

A single consumer invokes each job in a fresh subprocess to isolate rendering and
locale state. A stable worker kernel guard prevents a second instance consumer.
Per-job guards prevent recovery from racing an orphaned child. CLI and worker
share `work/update.guard`; never unlink stable guard files. PIDs cannot establish
cross-container ownership. Unknown older `work/update.lock` formats fail closed;
stop all writers and inspect them locally rather than clearing by PID alone.

Lost/duplicate notifications are expected across separate SQLite transactions.
The worker resends missing/stale notifications; job claim and fixed core operation
IDs prevent repeated execution. Core financial rows and their `data_committed`
marker now commit in the same transaction. Web/queue/financial databases are not
presented as one distributed transaction or an exactly-once queue.

## Interruption and error handling

| State/evidence | Action |
|---|---|
| Preview `blocked` | Correct input/references, upload if needed, submit a fresh preview/key |
| `stale_preview` or `stale_engine` | Run a new preview against current inputs/code |
| Queued notification lost | Worker scan resends it; no manual reimport |
| Worker interrupted with proven committed inputs | Requeue the same operation for report-only recovery |
| `report_failed` | Inspect trusted local operation; `POST /jobs/{id}/resume` resumes saved references/cutoff |
| Complete report exists before core/Web state catches up | Verify bundle hashes/linkage and recover pointer/registry without another edition |
| Unproven commit state / `needs_review` | Stop automatic retries; follow the local review procedure below |
| Running/committed work cancellation | Rejected; cancellation never undoes a financial transaction |

For `needs_review`, stop the instance worker and other writers. Preserve a copy of
the complete instance and inspect the job's `core_operation_id` using the existing
CLI operation listing/show commands against that portfolio's explicit `--workspace`.
Check operation status, financial input fingerprint and any report manifest/bytes.
Do not edit SQLite status columns, delete guards or rerun an import to guess the
outcome. If evidence cannot prove a safe transition, retain `needs_review` and use
a synthetic reproduction for a maintainer review. This version has no general
"acknowledge discrepancy and force retry" endpoint. Advanced repair tooling
remains future work.

Only non-sensitive error codes are returned for execution failures. Core operation
records/failed build directories remain private trusted-host diagnostics. Never
attach real exports, raw metadata DBs or report logs to public issues.

## Metadata upgrades and maintenance

For an existing API v1 instance, stop Web and worker processes, keep a complete
private backup, install the new image/dependencies, then run:

```bash
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" upgrade
```

Or, after rebuilding the inspected Docker context, with services stopped:

```bash
docker compose run --rm web upgrade
docker compose up -d
```

Schema v2 migration makes a private SQLite v1 metadata backup under `admin/backups/`
and adds upload/job records. It does not migrate any financial ledger. Startup
fails closed on older/future incompatible metadata until the trusted host command
is used. Never downgrade DB files into older images. Compose replacement retains
private volume state; `down --volumes` deletes it and is not an upgrade procedure.

[Complete consistent backup/restore](web-backups.md) and [copy-verified CLI adoption](web-adoption.md)
are implemented. Stronger retention UI and resource/crash testing across additional
hosts/platforms remain separate work. Actual private migration is an explicit operator action.

Implementation references: [Huey API](https://huey.readthedocs.io/en/stable/api.html)
and [consumer guide](https://huey.readthedocs.io/en/stable/guide.html). Queue storage
and consumer APIs come from Huey; ledger recovery follows the contracts above.

## Explicit-context parser previews

`POST /api/v1/portfolios/{portfolio_id}/source-context-plans` accepts owner-scoped
`source_csv` upload IDs, one `contexts` object per input, optional `selections` and
`previous_plan_id`. See [the closed context schema](source-ingestion.md#explicit-context-previews-src-004b1).
It queues an ordinary `source_plan` job with no financial operation ID. The API pins
portfolio state, upload hashes, engine, trusted host configuration and environment;
the worker invokes the same fresh-child v2 runner as the CLI. Auth/CSRF, idempotency,
portfolio isolation, expiration and restore invalidation match other source plans.
There is no browser form or confirm/financial-resume route. A ready result always
has `ingestible: false`, `booking_blocker: production_v2_pipeline_pending`.
The ordinary holdings/order import routes retain their behavior.

## Opt-in data-only source submission

B2 adds `POST /source-ingestion-previews` and `POST /source-ingestions` beneath the
same portfolio prefix. They are separate from nonbooking source plans and normal
report-producing updates. A preview accepts source uploads, explicit contexts and
reviewed bindings. Missing bindings return mapping suggestions, not permission to
book. Exact `approval_sha256` and `acknowledge_no_reports: true` confirm a frozen
source batch; no parser runs during confirmation. The isolated job becomes
`recorded`, never `published`. Fixed operation IDs, input/configuration/environment
checks, one-preview/one-operation and financial-job mutual exclusion prevent replay.
Inactive `/source-ingestions/{job_id}/recover` is receipt-only; `/discard` only
abandons a never-started or matching proven-failed job, preserving its audit rows.
Unknown starts cannot be discarded or automatically repeated. Full schemas,
24-hour expiry, restore invalidation and CLI equivalents are in the [B2 guide](source-ingestion.md#frozen-submission-and-recovery-src-004b2).
There is no new browser form and no native daily-workflow cutover in B2.

## Opt-in source report publication (SRC-004C3C2A)

This API connects the frozen C3C1 core to the existing isolated Web jobs, report
library, artifact downloads and exports. It does not switch ordinary `/previews`
or automatically reinterpret old financial inputs. The regular upload form defaults to the automatic parser entry documented below;
the native `/previews` contract remains a separate compatibility API. No plugin installation/enable endpoint or runtime LLM is involved.

Upload bounded `source_csv` evidence first. `POST /source-report-previews` accepts:

```json
{
  "upload_ids": ["SERVER_SOURCE_CSV_ID"],
  "contexts": [{
    "evidence_at": "2024-02-01T12:00:00+00:00",
    "source_reference": "synthetic-reviewed-export"
  }],
  "bindings": [{
    "provider": "synthetic",
    "source_account_id": "demo-account",
    "target_kind": "new"
  }],
  "valuation": {
    "as_of": "2024-03-01T00:00:00Z",
    "period_start": "2024-01-01T00:00:00Z",
    "generated_at": "2024-03-01T00:00:00Z",
    "report_locale": "en-CA",
    "fx": {
      "usd_cad": "1.5", "usd_twd": "30",
      "usd_cad_date": "2024-02-29", "usd_twd_date": "2024-02-29",
      "usd_cad_source": "synthetic-fixed", "usd_twd_source": "synthetic-fixed"
    }
  }
}
```

The invented adapter above requires separate trusted-host installation/enablement;
see [the SDK](parser-sdk.md). `contexts`, optional `selections` and `bindings` use
[B2's closed schemas](source-ingestion.md#frozen-submission-and-recovery-src-004b2).
Valuation uses [C3C1's exact reference contract](source-projections.md#frozen-source-report-publication-src-004c3c1).
Money/reference quantities are strings. The usual 16 KiB JSON body limit applies.
`btc_price`, `kind` and `btc_cost_policy` are optional valuation fields. Missing
prices stay unknown; preview never fetches references. With no new CSV, omit
`upload_ids`, `contexts`, `bindings` and `selections` and provide only `valuation`.
This reads saved facts; it does not prove that no new transactions occurred.
BTC totals/events/contribution evidence use the existing financial forms first.

The queued job has `kind: preview`. A ready `result.status: mapping_required`
contains suggestions but is **not confirmable**; submit a new reviewed preview
with explicit bindings. A ready `awaiting_confirmation` result contains account
review, observed CAD/USD/TWD totals, pending checks and `approval_sha256`.
Review those limits and then send `POST /source-reports`:

```json
{"preview_id":"SERVER_PREVIEW_ID","approval_sha256":"EXACT_REVIEWED_SHA256"}
```

Both requests require a scoped owner session, Origin/CSRF and an idempotency key.
The ordinary `/jobs` confirmation rejects a source preview without exact approval.
One preview maps to one `update` job and fixed operation, including retries with a
new request key. Existing financial work shares the mutual-exclusion/capacity rules.
The existing Import & jobs screen shows prepared source mappings/subtotals and
submits the exact digest; it cannot yet create/edit those explicit source requests.

Before commit the worker rechecks expiration, original frozen evidence, financial
state/settings, parser configuration, engine/environment and localization. After a
proven commit it uses report-only recovery, without old CSV/preview/configuration
or a parser. The normal job resume endpoint and startup reconciliation retain that
boundary. An unproven start becomes `needs_review`; no automatic reimport is used.
A published core bundle interrupted before registry delivery is verified and
registered once, without another report or a rollback of a newer latest pointer.

Source publications appear in the ordinary library and selected-report API with
`source_basis`; see [the read/export contract](web-frontend.md#frozen-source-report-views).
Full backups retain archives, jobs, artifacts and original report bytes. Restore
expires unstarted source confirmations because their approval was workspace bound;
proven committed/published operations may finish report-only recovery. No restore
replays an old source parser or revalues history. This synthetic acceptance does
not establish a migrated personal instance or complete daily cutover.


## Automatic source import previews

`POST /api/v1/portfolios/{id}/source-import-previews` prepares the regular browser's
default parser mode. It shares the upload/owner/CSRF/idempotency/worker limits above.
Allowed uploads are `source_csv` plus at most one `fx` and one `price`; their combined
count is at most five. Context options correspond to CSV order, excluding reference
uploads. Missing mappings/references are ready review results, not confirmations.
Only `awaiting_confirmation` with its exact digest can use `/source-reports`.

See the [automatic import contract and CLI examples](source-projections.md#automatic-import-entry-src-004c3c2b)
for default dates, stable aliases, account choices, optional totals and reference
policies. `saved_only` is offline. Explicit `fetch_public` may write date-bound private
reference caches before approval; it never books financial facts. A newly prepared
preview records the resulting fingerprint. Existing explicit-context source-report
API and native import API behavior are retained. Settings/config/environment changes
invalidate approval; report-only recovery never reruns a parser or balance insertion.


Saved contexts are read-only `GET /source-import-contexts` results from verified
committed evidence, scoped by owner/portfolio. Per-file context options may select a
`profile_id`, or manual host settings, plus explicit revision/scope parents. Invalid
archives return `source_integrity`, never a guessed setting. See [default workflow](source-projections.md#default-daily-workflow).
Canonical investment IDs are also valid in financial cash-flow/coverage declarations;
the original native account ID contract remains accepted. They use the same staged
preview/confirm/record protocol and require a separate report publication afterward.

## Browser stage and approval guidance

The regular browser organizes inputs, saved preview review and formal outcomes as
three visible stages. Advanced compatibility/correction controls remain available
through disclosures. Missing references link to their corrective form options.
Editing the draft invalidates the selected approval in the current tab; stale
server approval cannot be reused. Same-request network retries retain request
identity, while proven committed reports use explicit report-only resume. Unknown
outcomes require trusted-host review, never a generic reimport. The browser does
not persist unsent financial drafts in local storage. See
[the detailed browser procedure](web-frontend.md#staged-import-review-and-recovery).
Backend approval, expiry, isolation and receipt-recovery contracts above are unchanged.
