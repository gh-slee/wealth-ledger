# CI and end-to-end regression assessment (2026-11-10)

Read from `.github/workflows/ci.yml`, `frontend/playwright.config.ts`, the test
modules' environment gates, recent run history and the repository settings.
There is one workflow with seven jobs and no deployment or release automation.
Deployment is a manual operator action by design; publishing images is UX-P1-007.

## What works

- Seven jobs cover the core suite and report demos, Docker hardening and
  restore, the browser workflow, SDK packaging, and three PostgreSQL profiles.
- Actions are pinned by commit, permissions are read-only, credentials are not
  persisted, and every job has a timeout.
- Privacy and language guards run on every push.
- The browser job checks formatting, generated API types and 25 real workflow
  tests across locales, themes and a narrow viewport.
- The last four runs on `main` passed.

## Findings

| # | Finding | Evidence | Effect | Ticket |
|---|---|---|---|---|
| 1 | The real-SQL tests for the V2 import functions never run in CI | `tests/test_postgres_migration.py:230` gates 93 tests on `WEALTH_LEDGER_INGESTION_TEST`; the workflow never sets it | The MVP's most critical code can break and stay green | WL-P0-022 |
| 2 | A skipped gated suite is silently green | Tests use `skipUnless` on seven variables; no job checks its skip count | Finding 1 went unnoticed; it can recur | WL-P0-022 |
| 3 | No end-to-end test of V2 | All 25 browser tests use the SQLite fixture; V2 screen tickets use mocked APIs | Nothing proves browser, V2 API, PostgreSQL and worker work together | WL-P0-023 |
| 4 | The browser fixture is too uniform | One observation per portfolio; a chart defect with one data point passed unnoticed | Regressions in state-dependent views slip through | WL-P0-023 |
| 5 | Every pull-request commit runs the pipeline twice | Triggers are `push` and `pull_request` with no filter and no concurrency group; run history shows paired runs | Doubled load, worse with agents pushing work-in-progress commits | WL-P1-010 |
| 6 | The longest job is at its limit | `python-312-linux` took 24 min 10 s against a 25-minute timeout on the last `main` run | Timeouts as tests are added | WL-P1-010 |
| 7 | Ticket-only and docs-only changes run every job | No path conditions | About 25 minutes to change a ticket status | WL-P1-010 |
| 8 | A failed browser run keeps no report | The job prints error contexts only | Slow diagnosis, especially for agents that cannot run a browser locally | WL-P1-010 |
| 9 | `main` is not protected | GitHub API reports "Branch not protected" | Passing CI before merge is a convention | owner action, noted in WL-P1-010 |
| 10 | No vulnerability or static security scanning | The workflow inventories licences only | A vulnerable pin is not reported | WL-P2-009 |
| 11 | No Python lint or type check | Not in the workflow or lock files | Dense code grows unchecked | WL-P2-006 |

## Order

WL-P0-022 first: it is small, needs no decision, and should be merged before
WL-P0-007C, 007J and 007L change the import SQL. WL-P0-023 follows the first V2
screens. WL-P1-010 before many agents push at once. WL-P2-009 and WL-P2-006 later.

## Not verified

The workflow was read and its history inspected; no workflow change was tried.
The 93 gated tests were not run during this assessment.
