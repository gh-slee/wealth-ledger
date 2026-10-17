# Web imports, durable jobs and recovery

The API can import Wealthsimple holdings CSVs, Bull Bitcoin orders CSVs, or both,
and an optional explicitly dated BTC total. It reuses the financial CLI core and
produces ODS, Markdown and PDF reports without an LLM or LibreOffice. React pages
are WEB-004 work. This is an API workflow, not a ready browser dashboard.

Follow [Web operations](web-operations.md) for installation, owner authentication,
CSRF, public origin, Docker context and private storage. Use synthetic files first.
Existing CLI portfolios are never automatically adopted; copy/verify/switch is
WEB-006. No Web instance defaults to a maintainer's ledger.

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
docker compose run --rm -it web init-owner
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
the existing CLI; advanced Web forms remain WEB-006.

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
metadata registration. Browser report libraries/ZIPs/full backup are later stages.

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
"acknowledge discrepancy and force retry" endpoint. Advanced repair/adoption tooling
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

Complete consistent backup/restore, stronger retention UI, resource/crash testing
across additional hosts/platforms and private legacy adoption remain separate work.

Implementation references: [Huey API](https://huey.readthedocs.io/en/stable/api.html)
and [consumer guide](https://huey.readthedocs.io/en/stable/guide.html). Queue storage
and consumer APIs come from Huey; ledger recovery follows the contracts above.
