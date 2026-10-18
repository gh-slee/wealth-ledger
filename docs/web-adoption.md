# Adopt an existing CLI workspace

WEB-006 provides trusted-host **copy, verify, switch** commands for a stopped CLI
workspace. They create a new independent portfolio inside an initialized Web instance.
They do not move/delete the source, reimport CSVs, recalculate prices, generate new
historical observations, or regenerate reports. There is no HTTP host-path/adoption
endpoint. Actual private adoption is an explicit operator action, separate from
installing this code or running synthetic tests.

## Before starting

- Retain the original workspace and a protected independent backup. Choose the
  correct source explicitly; there is no personal-ledger default.
- Stop all source writers/scheduled imports. Both commands acquire the same source
  kernel guard as the CLI. An existing update lock requires host review; the commands
  do not break it. A stable `work/update.guard` may be created/retained; financial
  source files are not rewritten.
- Finish or review unresolved CLI operations first. Data-committed/report-failed
  operations must resume their saved report context on the original workspace;
  uncertain interruptions need investigation, not CSV reimport.
- Initialize the Web owner in a separate dedicated instance, with the matching
  source checkout/image version and locked Python Web dependencies installed.
- Verify the original evidence and complete checksummed report bundles are present.
  Missing/changed evidence, invalid SQLite integrity/foreign keys, unsupported files,
  unexpected symlinks and incomplete report manifests fail closed.
- The plan is private, unencrypted and contains original paths, inventory/checksums
  and database row counts. Legacy acceptance additionally records current-byte
verification evidence, not original historical publication proof. Keep the plan
outside both state directories, protect it with
  file permissions and never attach it to GitHub. Publication guards reject its
  format marker even under a normally public filename.

The adoption service accepts the current CLI financial state format, validated using its existing
read-only queries and bundle contracts. It is not a general migration from arbitrary
older schemas. Keep the original version available if preflight identifies an
unsupported historical layout; do not edit historical database rows or manifests to
make validation pass. Recognized pre-checksum report manifests require an explicit
`--allow-legacy-reports` preview and separate migration-time evidence; see
[legacy report adoption](web-legacy-reports.md). The default still requires modern
checksummed publications.

## Native host commands

Run from the repository root, using Python 3.12+ with `requirements-web.lock` installed.
Substitute your own dedicated paths; these examples contain no existing user data:

```bash
umask 077
mkdir -p "$HOME/.local/state/wealth-ledger/adoption"
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" adopt-preview \
  --workspace "$HOME/.local/share/wealth-ledger/cli-workspace" \
  --name "Investment ledger" \
  --output "$HOME/.local/state/wealth-ledger/adoption/cli.adoption.json"
```

The preview checks the stopped source and writes a new private mode-600 plan. It
returns `portfolio_id`, file/report counts and `plan_sha256`. Review the plan locally
and check the source, destination, intended financial configuration, reports and
excluded scope. The digest is of canonical plan content; it is not the raw file
hash from `shasum`. Existing plan files are never overwritten.

Confirm exactly that reviewed digest:

```bash
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" adopt-confirm \
  --plan "$HOME/.local/state/wealth-ledger/adoption/cli.adoption.json" \
  --plan-sha256 '<plan_sha256 returned by adopt-preview>'
```

The target and source must be separate, non-nested directories. The source and
code must still match the plan. Any changes after preview require a new plan with
a new filename. Confirmation temporarily enters Web maintenance, drains activity,
reacquires the source guard, verifies the plan, stages a private copy and atomically
registers the new portfolio/report index. Existing Web portfolios are not overwritten.

## What is retained and verified

| Scope | Treatment |
|---|---|
| `data/` | All original CSV/wallet/official reference/FX/price evidence and financial state; active SQLite database uses the backup API |
| `reports/` | All frozen report bytes, manifests, chart paths, original report metadata and the validated relative latest link/pointer |
| `backups/` | Existing retained private database backups |
| Financial configuration | `local.toml`, `bull-opening.json`, `company-aliases.json`, `company-aliases.override.json` when present |
| Financial IDs and revisions | Unchanged account, source, snapshot, order, balance, event and operation identities; logical schema/rows/relationships compared |
| Web index | New portfolio/report/artifact IDs reference verified frozen bytes; original core operation linkage is recorded separately |
| Original runtime paths | Preserved in private adoption metadata; historical database rows/manifests are not rewritten |

Code, agent instructions, publication authorization and other configuration are not
copied. Replaceable `work/` cache/builds and runtime locks are excluded. There must be
no unfinished operations relying on those builds. Committed WAL content is included
through SQLite snapshots, while active WAL/SHM/journal sidecar files are excluded.
Source CSV/evidence bytes and all report bytes are hash-checked. SQLite schema,
row counts, logical values, integrity and foreign keys are compared because backup
page layout/file hashes can differ without changing financial values.

Bounds match the current backup envelope: 100,000 files/directories/links, 8 GiB of
selected source files, 2 GiB per file, and 16 MiB for the saved plan. Historical Web
artifacts additionally require a supported media type and at most 64 MiB each.
The only supported source symlink is a validated relative `reports/latest` link.
Missing work/configuration/evidence or unsupported names require local review.

## Verify, then switch daily use

1. Inspect the returned new portfolio ID. Sign in and select it; check all expected
   report editions, latest cutoff, holdings/accounts, original ODS/MD/PDF downloads,
   language and BTC cost policy.
2. Confirm balances/events/revisions, contribution records and coverage in
   **Financial records**. Adoption itself creates none of these.
3. Take a [full private Web backup](web-backups.md), retain the matching code/image,
   and verify an empty-target restore before treating the destination as primary.
4. Switch future imports to the new Web portfolio, keeping the original CLI workspace
   as a retained source. Do not continue independent daily writes to both copies:
   they are separate ledgers, not synchronized replicas.

The shared CLI can explicitly select the new portfolio directory with `--workspace`
when trusted host access is needed. Its ordinary lock/maintenance barrier coordinates
with Web jobs. Do not mount the original CLI directory as the Web instance `/data`.
For Docker, either run these trusted-host commands with deliberate source/plan mounts
and suitable UID permissions (use a durable source mount, not the default 64 MiB
`/tmp` for a complete portfolio copy), or adopt in a temporary native instance then use a
matching-version full backup/restore to populate a new Docker volume. The latter
preserves the verified portfolio/evidence/index and revokes restored sessions. Keep
the native/source instances until destination verification is complete. See the
[Docker restore commands](web-backups.md); no local LibreOffice is needed.

## Failure and recovery

- Before installation: a failed copy/verification leaves the original source and
  existing Web portfolios intact; no new portfolio is registered.
- A caught installation/metadata failure rolls back the new target only when the
  registry proves it was not committed. A committed registry and files are retained
  if completion is uncertain.
- A process crash may leave private staging, an installing receipt or maintenance
  marker. Stop/review the coordinator; use `maintenance-clear` only after proving no
  active holder. Retry **the same plan and digest**. A verified unregistered exact
  copy can be recovered; unexpected local content is preserved for host review.
- A repeated confirmed plan returns `already_adopted`, not another portfolio. Keep
  its source/plan until the initial switch and recovery checks are complete.
- Never delete an unfamiliar target/lock, invent missing financial records, overwrite
  a modified copy, or edit a manifest to bypass a mismatch.

Private receipts are under `admin/adoptions/` inside the instance and are included
in full backups. They are not public developer notes. See [Web operations](web-operations.md)
and [the design](self-hosted-webapp.md) for wider deployment/acceptance limits.
