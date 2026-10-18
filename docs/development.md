# Development and maintenance

This document covers implementation procedures. Shared agent guidance lives in
[AGENTS.md](../AGENTS.md); installation and contribution expectations live in
[CONTRIBUTING.md](../CONTRIBUTING.md). Read the topic contract needed by the task,
not every document before each edit. Private instructions and session state use
[the ignored override](agent-development.md), separate from public roadmap facts.

## Stack and reproducible environment

The implemented application is Python 3.12+, SQLite, Matplotlib, ReportLab and
standard ODF generation. Source-checkout installation uses `requirements.lock`;
there is no supported Python wheel yet. The optional FastAPI API and Python
worker have [operating guidance](web-operations.md). The React/TypeScript/Vite
frontend builds from a pinned npm lock; see [browser development](web-frontend.md)
for actual build, generated-type and synthetic browser-test commands.
Do not add runtime AI or local-office dependencies. See CONTRIBUTING for venv setup.

Full tests and a focused module, from the repository root:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_publication.py' -v
```

Use the selected venv's Python. Tests create isolated synthetic projects and Git
repositories; they must not read personal portfolios or require live issuer pages.
Inject prices/FX/official-format fixtures rather than relying on current websites.
Documentation work must not create financial snapshots or report revisions.

## Continuous integration and report verification

[CI](../.github/workflows/ci.yml) runs on push, pull request and manual dispatch with
Linux/Python 3.12, read-only repository permissions and locked dependencies. Its
checks are:

```bash
python scripts/check_language.py
python scripts/check_publication.py --worktree
python scripts/check_publication.py --staged
PYTHONPATH=src python -m unittest discover -s tests -v
python examples/demo.py --output work/demo-default
python examples/demo.py --output work/demo-proxy --btc-cost-policy bull_average_proxy
python examples/demo.py --output work/demo-tc --locale zh-TW
python examples/demo.py --output work/demo-sc --locale zh-CN
```

These commands use only synthetic/public-format inputs. Run relevant focused tests
while iterating and the full suite before publication. For financial/report changes,
verify affected identities, formula/cache agreement, three-currency totals, unknown
semantics and presentation checks. Visually inspect affected ODS/PDF/charts when
layout changes. Do not run unrelated real imports or broaden checks without reason.
Report observed results, environment and remaining gaps; past CI is not proof of
new uncommitted work. CI runs after upload and cannot prevent an initial leak.

## Financial and import contracts

See [core API](core-api.md), [BTC reconciliation](btc-reconciliation-plan.md) and
[user manual](user-manual.md) when changing these areas:

- Decimal/satoshi precision and unknown/valid-zero distinctions are mandatory.
  Preserve source bytes/checksums, stable identities, immutable history and append-only
  corrections. Do not use reverse fake transactions for transcription fixes.
- `scripts/update.py` supports either CSV, both, optional BTC quantity, or no input.
  Preserve source dates, partial/carried coverage and real observation times.
  Scope expansion is not growth; missing files/months do not establish no activity.
- `--dry-run` is offline and uses a disposable project: no real DB, caches, backups,
  operations, analysis runs or latest-pointer changes. Simulation IDs/results must
  not be mistaken for committed evidence.
- Contributions require cash-flow evidence and explicit coverage, not holdings or
  purchase spend. Bull Funding and Buy reuse one cash amount; transfers between
  tracked accounts cancel at the portfolio boundary.
- Preserve BTC/LBTC delivery types while presenting 1:1 BTC equivalents. Opening
  declarations, orders, observations and events remain separate. A pre-Bull opening
  declaration is fixed from explicit attribution, not recomputed by each import.
- Balance/events use stable IDs, unique source references, revision/void reasons
  and validated intervals. An observation anchors later known changes; prior events
  already included are not deducted twice. Matching later totals do not erase old
  unexplained gaps or prove independent quantity verification. Never guess fees.
- `actual_only` is the public default. The opt-in Bull average proxy is completed
  CAD purchase spend / delivered BTC+LBTC; estimated cost is current quantity times
  that average. A balance/event does not change the average; completed buys can.
  It cannot fill actual cost/contribution fields or settle reconciliation gaps.
  No purchases means no average; zero holdings with an average means zero estimated
  cost/P&L and a non-applicable rate. Quantity, policy and fee coverage are independent.
- Mutations retain backup, project lock and atomic data submission. Report publication
  is separate from commit; resume fixed saved inputs/cutoffs after failures.

## Analysis, reporting and localization

Use [report spec](report-spec.md), [ODS implementation](workbook.md) and
[i18n contract](i18n-plan.md) for the area affected:

- Official ETF adapters fetch latest published issuer data through code and retain
  effective/fetch dates, raw evidence, SHA-256 and parser versions. Unsupported or
  failed coverage stays unresolved; old caches cannot imply fresh verification.
- Preserve company/ADR/share-class identity, recursion and unresolved/rounding audit.
  Top-20 weights use all noncash investments including BTC as denominator, without
  normalizing partial coverage. Sector needs explicit official GICS; retain other
  issuer taxonomies separately. Country needs official classification, not guesses
  from MIC/currency/ISIN. Region grouping is not revenue geography.
- CAD/USD/TWD are alternative equivalents. Freeze historical references. Replaying
  `--lookthrough-run-id` requires the same financial fingerprint and no new input.
- Formats share one payload/templates. ODS writes standard ODF, formulas, numeric
  caches, embedded PNG charts and licensed fonts; do not replace this with unverified
  native charts or require development readers at runtime. Effective state appears
  in normal reports; superseded assumptions go to audit attachments/history.
- New ledgers default to en-CA; legacy ledgers preserve zh-TW. Use context-scoped
  catalogs/formatting, stable sheet IDs and generated quoted references. No process-global
  locale or automatic translation of source/user names, notes or references.
- New keys require all three catalogs with identical named parameters. Financial
  payloads/history/identities must not change with language. Use
  `scripts/render_report.py` for offline language editions, not an update.

## Public source and maintenance

Source adapters require minimal synthetic format/error fixtures and documented
support; the [plugin SDK](source-adapters.md) remains planned. Use English in all
canonical documentation and generic examples; preserve product localization.
Keep TODO and affected contracts aligned with actual behavior. Personal balances,
source filenames, verification history and preferences are not public documentation.

Before publication follow [publishing.md](publishing.md): explicit staging, review,
full tests and index/reachable-history audit. A local tool authorization does not
replace owner consent. No automatic merge, force push or release. Ordinary financial
commands never commit or upload data.

## Repository language policy

Canonical public Markdown, code identifiers, comments/docstrings and generic examples
use English. Contributor conversation preferences live only in ignored private
guidance and do not select documentation language. Supported product locales remain
en-CA/zh-TW/zh-CN; retain source text, UTF-8/locale fixtures and closed legacy message
compatibility rather than rewriting financial identities or saved payloads.

Run `python scripts/check_language.py` before publication. CI executes the same
standard-library check. It inspects allowlisted public Markdown and Python comments,
docstrings and identifiers for CJK text. Private instructions/data are outside its
read scope. Explicit exception categories are:

- Catalog/registry/legacy JSON in src/wealth_ledger/locales/.
- Intentional runtime localized labels, closed legacy compatibility strings and
  Unicode/localization test values inside Python string literals.
- Original source/user content and generated localized reports, which are not
  canonical Markdown source documents.

The checker does not rewrite content or call an LLM. It detects a bounded CJK
regression, not every non-English language or incorrect translation. It does not
validate arbitrary runtime string wording; existing catalog/locale tests enforce
that contract. Publication checks still reject unknown public paths. Add no broad
Markdown exceptions to hide untranslated documents. Review prose manually, verify
commands/anchors and retain original license terms/attribution. Exit 0 means passed,
1 violations, 2 unable to complete. Tests use isolated synthetic files.

## Workspace and parser contract acceptance

WEB-001 uses `workspace.py`, `application.py` and `publishing.py`; services must not
import scripts or mutate global project paths. Every daily mutation, preview and
recovery command must honor the same explicit workspace. Test only disposable
synthetic ledgers. `tests/test_workspaces.py` exercises two portfolios, all daily
query commands, lock/backup isolation, operation retry, aliases and a copied
installation whose code/files are chmod read-only. Its child process renders all
three report formats with frozen synthetic analysis and verifies untouched source
ledger/code hashes. Root-run CI cannot prove permission denial; the non-root local
run additionally asserts an attempted code write raises PermissionError.

`tests/test_source_protocol.py` checks SRC-001 version/identity/coverage/revision,
unknown values, Decimal/time/precision, cancellation and detection ambiguity.
This is a structural contract, not an external plugin loader or stateful economic
validator. `tests/test_source_registry.py` checks the independent SRC-002A registry,
metadata-only discovery, exact enablement, real temporary entry-point loading,
identity/provider collisions, compatibility and redacted/deterministic detection.
This does not establish production import integration or financial completeness.
Keep SRC-002B/SRC-003/SRC-004 pending until their acceptance gates pass.
Run these focused files with the same unittest discovery command and `-p` before
the complete suite. See [core API](core-api.md) and [source adapters](source-adapters.md).

## Web API and container checks

Install `requirements-web-test.lock` for optional Web tests. Standard discovery
runs authentication, CSRF/Host/Origin, expiry/revocation, persistent throttling,
metadata/settings, artifact ownership/path/hash checks, native HTTP restart and
Docker-context privacy. It skips the opt-in Docker runtime test. CI installs these
optional dependencies and runs a separate Linux Docker job. Container runtime
acceptance is pending until actually executed; Compose config validation is not
an image/startup test. See [the Web guide](web-operations.md).

The API factory requires a trusted-host initialized dedicated instance outside the
code tree. Metadata migrations touch only `admin/app.sqlite3`, never a financial
DB. No HTTP owner claim, arbitrary host paths, public static financial data or
implicit legacy adoption. API error handling redacts Pydantic input details.
Publication inspection recognizes only AST-verified `SecretStr = Field` declarations
with bounded numeric length metadata; literal/default password values remain blocked.
Image contexts use `scripts/docker_context.py`, explicit COPY and deny-by-default
`.dockerignore`; never build/publish from an unreviewed private workspace.


## Upload/job development

Install `requirements-web-test.lock` for the optional Huey/SQLite worker. The
[import/job guide](web-imports.md) documents implemented API and recovery states.
Focused acceptance:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_web_imports.py' -v
```

These tests use only temporary synthetic instances and real subprocess exits around transaction/report boundaries. The
opt-in Docker suite additionally uploads public invented fixtures through Compose,
waits for worker reports and verifies persistence after replacing both services.

Do not introduce runtime test-only crash flags, serialized callables or owner data.
Never unlink stable `update.guard`, per-job or worker advisory guard files. A process
ID is diagnostic only; keep unknown legacy lock handling conservative. Preserve
financial commit markers, fixed job/operation linkage, checksummed report recovery
and idempotent atomic artifact registration when changing worker behavior.


## Financial declaration and adoption acceptance

WEB-006 reuses core import/wallet validators through isolated worker simulations and
confirmed data-only operations. `tests/test_web_financial.py` checks offline read-only
previews, explicit openings/revisions, balance attribution, idempotency, cash-flow FX/
coverage, scope/CSRF and transaction-interruption recovery. A completion marker must
commit with financial rows; uncertain operations must not be automatically replayed.
The browser workflow exercises real preview/confirmation, mobile layout, automated
WCAG and frozen-report isolation. Keep generated API types and three locales aligned.

`tests/test_web_adoption.py` uses invented CLI copies to verify schemas/logical values,
original bytes/IDs/settings/reports, source preservation, rollback, stale-plan and
host-path/lock/symlink rejection, and a subsequent private backup/restore. Opt-in
Docker acceptance additionally adopts an invented stopped CLI copy inside disposable
containers and checks the adopted reports survive empty-volume restoration. Never
mount a maintainer's real workspace for these tests. See [declarations](web-financial-records.md)
and [trusted-host adoption](web-adoption.md) for supported scope and remaining limits.

## Operations and dependency acceptance

See [the upgrade/resource/platform matrix](web-release-acceptance.md). Focused
`test_web_operations.py` uses ENOSPC injection and actual subprocess exits, preserving
source/evidence and checking retry or fail-closed behavior. `test_dependency_inventory.py`
checks exact pins, missing licenses, deterministic metadata and npm optional scope.
Run `python scripts/dependency_inventory.py --require-declared` in the locked Web
venv; CI also inventories the test lock. No network/financial workspace is consulted.
Docker CI asserts Linux/x86_64; local acceptance records the actual guest architecture.
A synthetic v1 schema fixture verifies migration mechanics, not an untested historical
image upgrade or every host OS. Public prebuilt image distribution remains separate.

## Legacy publication acceptance

[Legacy report adoption](web-legacy-reports.md) is explicit and records separate
migration-time evidence. Preserve strict modern manifest verification and all original
bytes. Synthetic old-format fixtures must be authored independently, never copied
from a personal report. Run `test_web_legacy_adoption.py`, browser workflows and the
opt-in Docker suite for changes to receipt/download/restore behavior. Source format
recognition does not establish historical authenticity. Never repair a source manifest
to make migration pass.
