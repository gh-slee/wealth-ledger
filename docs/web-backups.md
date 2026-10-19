# Web exports, private backups and restore

WEB-005 provides frozen report ZIPs, selected report-data exports, and trusted-host
full instance backup/restore. These are different scopes. These commands do not adopt a standalone CLI workspace. Use [copy-verified adoption](web-adoption.md) for that task and [financial declarations](web-financial-records.md) for manual records.

## Download a report or dataset

Sign in, select a portfolio, and open **Report library**. Each published edition has
**Download report ZIP**, **Export report data**, and individual artifact buttons.
The ZIP preserves report filenames and relative chart links. It contains only that
edition's registered bundle: ODS, Markdown, PDF, charts, JSON and applicable CSV
attachments. It does not include instance credentials or the complete ledger.
Every artifact must match its registered size/hash and frozen bundle manifest.
Unpublished, cross-portfolio, changed or incomplete bundles fail closed.

The data form exports CSV or JSON from the selected saved report:

| Dataset ID | Contents | Optional date range |
|---|---|---|
| `holdings` | Positions and native-currency cash rows | None; the report's valuation cutoff applies |
| `accounts` | Account totals and source observation fields | None; the report's valuation cutoff applies |
| `history` | Recorded observations already present in this report | Inclusive observation dates |
| `cash_flows` | Recorded flows present in this report | Inclusive flow dates |
| `btc_monthly` | Monthly purchases, funding and average purchase rates | Inclusive whole months |

Ranges do not query later reports, reconstruct missing observations, infer
contributions or select every ledger revision. Daily date boundaries use the
recorded report date in the project's Toronto timezone; BTC monthly boundaries
include the entire selected months. JSON contains scope, cutoff, verification basis, completeness,
range metadata and rows, preserving nulls and decimal strings. CSV repeats context
columns, uses UTF-8 BOM and leaves unknown values empty. Numeric values retain
precision; text beginning with spreadsheet formula syntax is prefixed with an
apostrophe. Prefer JSON when source text must remain verbatim. CSV exports do not
establish tax basis, contribution room or combined period performance.

Authenticated API equivalents:

- `GET /api/v1/portfolios/{portfolio_id}/reports/{report_id}/bundle.zip`
- `GET /api/v1/portfolios/{portfolio_id}/reports/{report_id}/export?dataset=holdings&format=csv`
- `GET /api/v1/portfolios/{portfolio_id}/reports/{report_id}/export?dataset=history&format=json&start=2024-01-01&end=2024-12-31`

Downloads are private/no-store. Viewing/exporting does not fetch market references,
import evidence, regenerate reports, or extend the login idle deadline. The browser
cancels and discards pending exports on portfolio/authentication changes. A report
ZIP is capped at 256 MiB of registered inputs and 2,000 files; each artifact retains
the existing 64 MiB limit. Dataset output is capped at 256 MiB. Larger reports need
individual downloads or a separately reviewed extension to these bounds.

## What a full private backup contains

The backup is a private ZIP with a versioned `backup-manifest.json` and `instance/`
content. It includes owner password hashes, session metadata and the CSRF key,
portfolio settings, all financial databases and revisions, original CSV/wallet/
official reference evidence, uploads, frozen report history, recovery operations,
Web metadata migrations/backups, and advisory queue notifications when present.
Replaceable instance-root `cache/`, known kernel-guard locations, the active update lock,
and SQLite WAL/SHM/journal sidecars are excluded. Committed WAL content is included
through SQLite's backup API, not by copying the live database file.

The manifest records format/schema/code compatibility, source runtime root, UTC
creation time, relative paths, sizes, SHA-256, database integrity/foreign-key results,
row counts and logical database fingerprints. Raw evidence and reports retain their
bytes; SQLite page layout may change during a consistent snapshot. The application
checks the serialized archive before publishing it atomically to a new filename.

**Backups contain financial data and authentication material and are not encrypted.**
Protect both the backup and host. Keep a separate protected/off-device copy. Do not
upload these ZIPs to GitHub, public issues or an AI service. Checksums detect damage;
they do not authenticate a backup supplied by another person. Restore only trusted
private backups. Repository Git-ignore and publication guards block ZIP files,
including `.zip.part`; they do not replace reviewing what you publish.

## Create a backup: native host

Use Python 3.12+ with `requirements-web.lock`, from the source checkout. Choose an
existing private destination outside the instance and a new filename for every run:

```bash
umask 077
mkdir -p "$HOME/.local/share/wealth-ledger/private-backups"
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" backup \
  --output "$HOME/.local/share/wealth-ledger/private-backups/instance-backup.zip"
```

The command automatically enters maintenance: new HTTP requests return `503`
`maintenance`; new worker claims and standard portfolio CLI writes stop entering.
Existing activity drains before the exclusive snapshot barrier is acquired. The
same barrier is shared by the API, isolated jobs and standard CLI portfolio locks.
Unknown legacy portfolio update locks refuse backup and require local review; they
are never silently removed or bypassed.
The default drain timeout is 30 seconds; `--timeout 120` allows a longer report job,
up to 300 seconds. A timeout refuses the backup and releases its own maintenance
marker. Do not bypass the normal locks or directly write database/evidence files.
Huey notifications are advisory; the durable jobs and core operation markers remain
authoritative. A queue database snapshot is individually consistent.

A successful command prints only status, counts, archive size/SHA-256 and encryption
status. Existing destination files are never overwritten. There is no automatic
backup schedule or retention deletion. Deleting the source volume is not required.

## Create a backup: Docker

Use the same application image as the running instance. `--stdout` streams a completed
ZIP through the trusted host, avoiding a bind mount or Docker-socket access in the
application. `-T` disables terminal transformations of binary output. Save a private
partial file; publish the completed file only if the command succeeds:

```bash
(
  set -euC
  umask 077
  mkdir -p "$HOME/.local/share/wealth-ledger/private-backups"
  backup_file="$HOME/.local/share/wealth-ledger/private-backups/instance-backup.zip"
  test ! -e "$backup_file"
  docker compose run --rm --no-deps -T web backup --stdout > "$backup_file.part"
  ln "$backup_file.part" "$backup_file"
  rm "$backup_file.part"
)
```

The binary stream goes to stdout; the status receipt goes to stderr. If the command
fails, do not rename/use the partial file as a completed backup. Inspect the error
and choose a new name after resolving it. ZIP construction uses private instance
cache space; allow free disk space for staging and the archive. An interrupted host
stream does not change the original ledgers or retained reports.

## Restore: a new empty instance only

Restore first with the **matching application source/image version** used to make
the backup. Version one requires the recorded engine fingerprint and Web schema;
it refuses unknown formats, versions or code. Keep the source commit or immutable
Docker image ID alongside the protected backup before upgrading; the engine hash
is a compatibility check, not a downloadable application version. Restore with the old version before
a separately supported upgrade. This command does not migrate a legacy CLI workspace.

Native example, using a new empty directory and the private backup:

```bash
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/restored-instance" restore \
  --archive "$HOME/.local/share/wealth-ledger/private-backups/instance-backup.zip"
```

Docker example, using a **new, unused Compose project name** to obtain a separate
named volume while leaving the original instance intact:

```bash
docker compose --project-name wealth-ledger-restore-check run --rm --no-deps -T web restore --stdin \
  < "$HOME/.local/share/wealth-ledger/private-backups/instance-backup.zip"
```

Do not initialize an owner in the restore target first. A nonempty target is refused,
including an initialized instance. The restore command validates member paths,
duplicates/case conflicts, types, counts, expanded sizes, hashes, database logical
values/foreign keys, registries, archived sources and report pointers in a private
staging directory. It rejects traversal, arbitrary symlinks, changed bytes and
undeclared members; it never uses unrestricted `extractall`. Only the validated
relative `reports/latest` directory link is reconstructed. A caught failure cleans
only newly staged/installed target content and preserves the original instance and
backup. The instance marker is installed last; a process crash before that point
leaves an incomplete target that must not be served. Retry into another empty target.

Restore revokes all saved sessions and clears login budgets. Existing username and
password hash are retained: sign in again with the same owner password. Old financial and nonbooking source-plan previews
expire; generate a new preview. Private `admin/source-parsers.json`, source uploads
and plan receipts are preserved, but restore does not install/load plugin packages.
Use a verified matching environment and create a fresh plan before parser work. Queued confirmed work retains its stable IDs, and
interrupted jobs are reconciled from durable core markers on worker startup. A
proven committed operation resumes reporting; uncertain work stays `needs_review`.
There is no automatic CSV reimport or financial recalculation during restoration.
Historical financial rows/manifests remain unchanged. A private restore receipt
records runtime-root mappings for old publication paths and auth revocation.

To inspect the native restored instance, start its API/worker using the new
`--data-root` in [Web operations](web-operations.md). For the Docker example, stop
the old project's services before starting the restore project's services if both
use the default host port; keep both named volumes. Run `docker compose --project-name
wealth-ledger-restore-check up -d` only after resolving that port ownership. Verify
sign-in, portfolios, source dates, holdings, totals and historical report downloads
before choosing which instance to use. Container replacement alone is not this
restore test. Never delete the original volume as a routine step.

## Interrupted maintenance and limits

If a backup or metadata-upgrade process is killed, its durable maintenance marker intentionally blocks
new work. After verifying the backup coordinator stopped, use the trusted host:

```bash
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" maintenance-clear
# Or, for the existing Docker instance:
docker compose run --rm --no-deps -T web maintenance-clear
```

The command requires both coordinator and activity barriers to be free; it cannot
clear an active backup or bypass running work. It removes only the maintenance
marker, not financial records, archives, reports or unknown legacy update locks.
An initialization/upgrade/password-reset command also honors maintenance.

Version-one bounds: 100,000 files/directories/links, 8 GiB total expanded file content, 2 GiB per file,
16 MiB manifest and a 300-second maximum drain timeout. Capacity/crash acceptance
and the upgrade/rollback runbook are documented in [operations acceptance](web-release-acceptance.md).
Broader host distribution and Windows-specific restore/symlink acceptance remain
separate platform gates under WEB-008. There is no automatic encryption, scheduling or remote storage.

Implementation references: [SQLite backup API](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)
and [ZIP extraction warnings](https://docs.python.org/3.12/library/zipfile.html#zipfile.ZipFile.extractall).

Upgrade/rollback order, resource failures and current platform acceptance are in
[the operations runbook](web-release-acceptance.md). Interrupted upgrade cleanup
validates the instance identity without requiring the newer schema; it does not
upgrade or rewrite financial data merely to clear the maintenance barrier.

Recognized older publications can be adopted explicitly with separate
[migration-time evidence](web-legacy-reports.md). Legacy ZIPs add a verification
attachment while preserving the original manifest/report bytes. Full backup/restore
retains and checks the private receipt and its binding to report/artifact registrations.

## Canonical source-v2 foundation

[SRC-004A](source-ingestion.md) uses additional tables in each portfolio's existing
SQLite database and hashed CSV/JSON/binding evidence in `data/raw/source-v2/`.
Backup and CLI adoption validate decoded facts/scopes/effects against these archives.
Restore retains them without loading/installing a parser. Current report projection
gates remain in force; frozen historical publications still work. Synthetic native
and Docker acceptance include a full backup to an empty instance/volume.

## Frozen source submissions

Full backups also preserve `admin/source-submissions` bundles and canonical source
facts/operation receipts. Restore expires source-ingestion previews and marks pending
source confirmations `needs_review`, so an old workspace-bound approval never runs
automatically at a new root. Already recorded source jobs retain their receipts;
receipt recovery strictly verifies archived canonical evidence without plugins.
Unstarted or matching failed jobs may be explicitly discarded in job metadata;
financial audit rows and frozen evidence remain. Ambiguous/committed operations
cannot be discarded as unstarted. Native and Docker acceptance cover real isolated
API confirmation followed by full backup and fresh empty-volume restore. See the
[submission recovery contract](source-ingestion.md#frozen-submission-and-recovery-src-004b2).

CLI frozen-preview writes against a Web-managed portfolio also enter the instance
activity barrier before parsing or saving metadata. Active backup/upgrade maintenance
blocks them, preventing a partially saved bundle from entering a full snapshot.
