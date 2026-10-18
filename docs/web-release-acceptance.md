# Operations acceptance and upgrade runbook

This document scopes the self-hosted pre-release acceptance. It does not deploy an
instance, adopt a private ledger or publish an image. Follow [installation](web-operations.md),
[backups](web-backups.md) and [retained-source adoption](web-adoption.md).
A disposable synthetic service is test evidence, not a user's running instance.

## Platform scope and distribution

The application uses the same Python/SQLite runtime, Linux container filesystem and
Compose volume on every host. API and worker share one local private volume; no
broker credentials, host-specific portfolio defaults, Node server, local office
installation or runtime LLM is required.

| Target | Evidence and scope |
|---|---|
| Docker Desktop / Apple Silicon, Linux/arm64 guest | Local opt-in suite exercises native architecture, image privacy, owner setup, browser assets, stopped v1 metadata upgrade, hard-kill/restart, Compose imports/report jobs, retained-source adoption and empty-volume backup restoration. Rerun on the candidate being accepted. |
| Linux/amd64 Docker/Compose | CI runs the same suite and asserts `x86_64`; current-candidate green CI is required before closing WEB-007. Earlier merged CI is not proof of new changes. |
| Windows/macOS Docker hosts | Intended to run Linux containers. Windows-native container images are outside scope. Host-specific Desktop/WSL/filesystem acceptance remains unverified until actually run; host installation alone does not establish compatibility. |
| Other CPU architectures, NAS, rootless or network-mounted SQLite storage | Not accepted by the current evidence. Separate host/locking/storage testing is needed. |

WEB-008 tracks prebuilt Linux/amd64 + Linux/arm64 images and a pull-only Compose
recipe for Windows/macOS/Linux Docker hosts. Current Compose builds the audited
source context locally; `docker compose pull` is not a supported install yet.
A future manifest selects the guest CPU image; it does not remove host persistence,
permissions, disk, origin or restore requirements. No registry push/release workflow
exists in this change. Public distribution needs final-image dependency/OS/browser
license notices, SBOM/security review, provenance and explicit publication approval.

## Acceptance evidence map

Use temporary invented ledgers only. The following commands exist in this tree:

```bash
python -m pip install -r requirements-web-test.lock
PYTHONPATH=src python -m unittest discover -s tests -p 'test_web_operations.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_dependency_inventory.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
python scripts/dependency_inventory.py --require-declared
WEALTH_LEDGER_DOCKER_TEST=1 PYTHONPATH=src python -m unittest discover -s tests -p 'test_web_docker.py' -v
```

| Boundary | Executable evidence |
|---|---|
| Clean install, UID/read-only code, image privacy, restart, API/static assets | `test_web_docker.py`, `test_web.py` and Docker context tests |
| Upgrade v1 to v2, preserved auth/registry, backup, idempotent retry/future-version refusal | `test_web_operations.py` plus the stopped-container v1 fixture in `test_web_docker.py` |
| Concurrent upgrade/active work and interrupted maintenance | Real peer-process advisory lock and killed upgrade tests; no test-only runtime crash flags |
| Capacity failure | Injected ENOSPC at staged import, immutable evidence, upload, backup ZIP and restore writes; rows unchanged, partial files cleaned, safe retry |
| Hard process exits | Actual subprocess exits during schema transaction, backup and restore installation; Docker SIGKILL; earlier worker transaction/publication interruption tests |
| Full private backup to empty storage | `test_web_backups.py` and Compose different-volume restore, auth revocation and frozen report comparison |
| Existing CLI adoption | `test_web_adoption.py`, `test_web_legacy_adoption.py` and Compose copy/verify; original source retained, explicit legacy evidence, no reimport/revaluation |
| Three product locales | Existing catalog/report tests, offline demos and browser workflow; operating procedure below applies to each |
| Dependency evidence | `test_dependency_inventory.py`, exact lock versions, upstream declarations/files and bundled notice hashes |

These tests do not emulate kernel power loss, exhausted physical disks, every OOM
scenario, hostile hypervisors or every filesystem. ENOSPC injection verifies error
boundaries without filling a user's disk. Hard kills exercise process recovery,
not a promise against hardware corruption. Keep independent backups.

## Upgrade with a recoverable rollback

1. Read candidate changes and verify its CI. Resolve or review in-flight jobs first.
   Record the current source commit, engine version and immutable image ID. Preserve
   that image (a separate local tag or private image archive) before replacing its
   mutable tag. Backups require their matching application version to restore.
2. Create a full private backup using [the streaming recipe](web-backups.md), retaining
   the original volume. Verify it by restoring with that matching old image into a
   **different empty volume**; compare sign-in, portfolios, report dates, totals and
   frozen artifact downloads. A backup that has not restored is unproven.
3. Stop both services, leaving the volume intact: `docker compose stop web worker`.
   Keep the same Compose project name and persistent volume for an in-place upgrade.
4. Select/review the new source version. Prepare a fresh source-only build context;
   existing contexts are never overwritten. For example, after choosing a new suffix:

   ```bash
   python3 scripts/docker_context.py --output work/docker-context-upgrade-1
   WEALTH_LEDGER_BUILD_CONTEXT=./work/docker-context-upgrade-1 docker compose build web
   docker compose run --rm --no-deps -T web upgrade
   docker compose up -d
   docker compose ps
   ```

5. The host upgrade command uses an exclusive instance maintenance barrier, drains
   standard API/worker/CLI work and backs up v1 metadata privately before a single
   schema transaction. It changes only Web metadata, not financial databases or
   historical reports. Current schema v2 upgrades are idempotent; unknown future
   schemas fail closed. Services should remain stopped throughout version changes.
6. Verify health, sign-in, portfolio settings, source dates, totals, report history,
   downloads and pending-job reconciliation. Do not reimport or regenerate merely
   to test. Use a separate synthetic portfolio for any deliberate new job.
7. If the new version fails, stop it. Do not run old code against a newer volume or
   downgrade the schema. Start the retained old image with the verified pre-upgrade
   backup restored into a **new empty volume**. Keep the failed upgraded volume for
   review; changes made after the backup are not silently merged or discarded.

Native deployments use `python scripts/web.py --data-root <absolute-instance> upgrade`
with API/worker stopped, following the same matching-version backup and rollback
rules. Direct SQLite/file writers bypass application locks and must also be stopped.
No upgrade, Git command or context helper deletes an existing financial volume.

## Capacity and interruption handling

Default Compose gives **each** service a 1 GiB memory ceiling, 256 PID limit and
64 MiB `/tmp`; these are configured limits, not a measured minimum capacity or a
promise for large portfolios. `/data` persists all authoritative instance state.
Staging and backups can require multiple copies of data plus an archive; check free
space on both the volume and backup destination before upgrades/imports/adoption.
Use a durable source mount for large CLI adoption, not the small `/tmp`. The
source needs permission to create/open `work/update.guard`; financial source files
are not rewritten. A fully read-only source mount cannot acquire that guard.
One API, one worker and local SQLite storage are the supported topology; adding API
replicas does not increase acceptance. No automatic job replay after an uncertain commit.

| Failure | Next action |
|---|---|
| ENOSPC / memory/PID pressure | Stop submitting jobs, inspect host/container capacity, provide space/resources and review durable job state. Never delete source CSVs, financial databases, report history or stable guard files to clear space. |
| Caught upload/import copy error | No partial immutable evidence is published; stage/temporary files are cleaned. Preview again against the current fingerprint. A failed preview is not a financial observation. |
| Report failed after financial commit | Resume that saved operation/job as documented in [job recovery](web-imports.md); do not import the CSV again to obtain the report. |
| Unknown or `needs_review` operation | Review the saved operation and evidence offline. Do not guess whether to replay. |
| Killed backup/upgrade coordinator | Confirm it stopped, then use `maintenance-clear`. It refuses live lock holders and works for v1 metadata too. Retry upgrade/backup. A caught failure clears only its own barrier. |
| Killed backup partial ZIP/cache stage | Not a completed backup. After the coordinator has stopped, retain/review those private remnants; remove only identified disposable files offline if space requires it. No automatic sweeping of unknown work. |
| Restore killed during installation | Marker-last installation prevents serving incomplete content. Leave that target for review and retry the original archive into another empty target. Never initialize an owner over it. |

Use `docker compose logs --tail 100 web worker` and `docker compose ps` locally for
operations; review/redact any output before sharing. Do not post archives, source
CSVs, database files, adoption plans or private paths in issues.

## Operating the three product locales

Canonical developer/operations documentation remains English. Product UI and report
presentation support all three locales without changing financial values/identities:

| Locale | UI/report behavior | Operations to verify |
|---|---|---|
| `en-CA` | Default on a new portfolio | Sign in, select/create portfolio, imports preview/confirm, financial records, report download |
| `zh-TW` | Select in the UI; choose portfolio report locale in settings | Same steps; check source dates, gaps/unknowns and decimal amounts against frozen report |
| `zh-CN` | Select in the UI; choose portfolio report locale in settings | Same steps; check localized report selection/download and missing-edition behavior |

The UI language and a portfolio's saved report language are independent. Changing
settings does not translate an old report, import data or revalue history. Existing
frozen editions remain available; offline edition rendering uses saved inputs.
Server/host commands and stable error codes stay English; the UI translates codes.
Backup/restore and adoption preserve each portfolio's locale and cost-policy settings.
Use [browser guidance](web-frontend.md) and [locale contracts](i18n-plan.md) for details.

## Deployment decision

Close WEB-007 only after current-candidate native checks and actual Docker acceptance
pass, privacy/license findings are reviewed and merged CI is green. That establishes
readiness to **approve a deployment/adoption**, not an already deployed personal
instance. A user's host, persistent volume, matching-version backup/restore rehearsal,
explicit copy/verify plan and original workspace retention remain deployment-specific
checks. Prebuilt public images and untested host platforms remain WEB-008.
