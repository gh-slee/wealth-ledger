# Wealth Ledger roadmap

This tracks product capabilities and public-source preparation, not authorization to
implement every item. Select work from the current task. Finance, imports, downloads
and reporting remain reusable Python code. The optional browser frontend uses
TypeScript/JavaScript, with Node for builds only. Production needs no LLM, agent,
Codex or local LibreOffice. See the [manual](docs/user-manual.md) and
[development rules](AGENTS.md).

## Available capabilities

- [x] Wealthsimple CSV detection, archiving, deduplication, append-only revisions and SQLite history.
- [x] Formal monthly/temporary snapshots, irregular submissions and missing-month handling without fabricated observations.
- [x] Separate CAD/USD and account holdings, plus CAD/USD/TWD equivalent totals.
- [x] Unified cash-flow CSV, coverage declarations, transfer matching and eligible brokerage period analysis.
- [x] Bull CAD Funding/Buy orders, original BTC/LBTC deliveries and combined valuation.
- [x] Monthly quantity-weighted CAD/BTC purchase rates; effective fixed opening distinct from original assumptions.
- [x] Optional BTC total, stable balance/event IDs, interval differences, later explanations, source deduplication and append-only revisions/voids.
- [x] Isolated batch data submission, operation inspection, fixed-cutoff recovery and stale-operation protection.
- [x] Python-only ODS/Markdown/PDF/PNG, embedded images, three-locale bundled fonts, formula caches and publication checks.
- [x] Latest official ETF constituents, recursive company exposure, rankings 1-20, coverage and complete audit exports.
- [x] Official GICS, country/market and region analysis, effective dates and non-company/unclassified reconciliation.
- [x] **FUT-001 Offline import preview**: optional `--dry-run`/`--json`; no real data, quote, backup, operation or report changes. Missing references remain pending; normal update defaults are unchanged.

## Self-hosted web app (browser/API/worker workflow implemented)

React/TypeScript/Vite, FastAPI, a Python worker, SQLite and Docker Compose; one
owner/household instance with independent portfolios. Auth, jobs, backup/adoption
and acceptance contracts are in [the design](docs/self-hosted-webapp.md). Preserve
the CLI, history, three locales and ODS/Markdown/PDF. The optional native API is
runnable; the browser workflow reads frozen reports and drives confirmed jobs.

- [x] **WEB-000 Stack and scope design**: shared Python core, private workspaces, React SPA, storage/containers, server-side sessions, Huey/SQLite jobs and backup contracts.
- [x] **WEB-001 Private workspaces and shared services**: separate code/workspace roots; all daily CLI operations, resources/caches/backups/locks/recovery; read-only code-root acceptance.
- [x] **WEB-002 Auth/API/Docker foundation**: owner CLI, Argon2id/opaque sessions, CSRF/origin/host/limits, versioned metadata, portfolios/settings, artifact registry and image/Compose. Synthetic native HTTP/security/restart, context privacy, Linux/arm64 container restart and Compose health/container-replacement acceptance passed locally. Broader platform/release acceptance remains WEB-007. See [Web operations](docs/web-operations.md).
- [x] **WEB-003 Upload/preview/background jobs**: bounded raw uploads, offline preview/explicit confirmation, JSON-ID Huey/SQLite notifications, isolated workers, durable job/operation linkage, atomic financial commit markers, idempotency, stale-preview rejection, report/artifact recovery and protected three-format downloads. Synthetic transaction/process interruption and Compose worker/replacement acceptance passed locally; uncertain states require review. See [imports/jobs](docs/web-imports.md).
- [x] **WEB-004 Browser analysis/report library**: React/TypeScript/Vite, three locales/currencies, tables/ECharts, frozen publications/source dates/gaps/unknowns, imports/jobs/settings/downloads and portfolio-scoped in-memory caches. See [browser workflow](docs/web-frontend.md); wider release acceptance remains WEB-007.
- [x] **WEB-005 Exports and backup/restore**: owner-scoped frozen report ZIPs and CSV/JSON datasets/ranges; maintenance/drain barriers, private versioned full backups, SQLite snapshots/evidence/logical checks, empty-target restore and session/recovery handling. See [exports and backups](docs/web-backups.md); broad platform/resource acceptance remains WEB-007.
- [x] **WEB-006 Advanced forms and existing-ledger adoption**: worker-based offline declaration previews/confirmation, BTC openings/balances/events/revisions, brokerage cash-flow CSV/forms/coverage, saved-data reports and trusted-host plan/copy/verify/switch. Synthetic source preservation, IDs/rows/evidence/frozen-report equality, interrupted-copy recovery and Docker adoption/empty-volume restore passed locally. See [forms](docs/web-financial-records.md) and [adoption](docs/web-adoption.md); actual private migration remains explicit.
- [x] **WEB-007 Release/operations acceptance**: exclusive metadata upgrades, atomic capacity-failure cleanup, abrupt-exit/retry tests, offline dependency-license inventory and [upgrade/rollback/platform guidance](docs/web-release-acceptance.md). Synthetic local acceptance, Linux/arm64 Docker Desktop and merged Linux/amd64 CI passed. This establishes readiness to review deployment/adoption, not an already migrated or running private instance.
- [ ] **WEB-008 Prebuilt multi-architecture distribution**: public GHCR Linux/amd64 and Linux/arm64 images, digest/version-pinned pull-only Compose, explicit image publication approval, final-image/browser/OS notices and SBOM/vulnerability review, provenance/signatures, clean pull/install/upgrade/restore tests and documented Docker Desktop macOS/Windows plus Linux host matrix. Keep local source builds available; no source checkout, host Python or npm required for end users. Do not claim arbitrary CPUs, Windows-native containers, NAS or rootless hosts are accepted without evidence.

- [x] **WEB-009 Recognized legacy publication adoption**: implemented and verified locally with explicit pre-checksum acceptance, preserved report bytes/dates, separate migration-time evidence, three-locale UI notices and bound downloads/exports/backup restore. Candidate CI/review and merge remain required before relying on it for deployment. See [legacy report adoption](docs/web-legacy-reports.md).

This track does not complete the source-plugin SDK, new currencies or combined
performance automatically. Keep each stage planned until accepted; actual private
migration is a separate explicit operation.

## Daily operations and analysis

| ID | Status | Scope |
|---|---|---|
| FUT-002 | Not implemented | Unified read-only status: latest successful report, source dates/carried data, BTC gaps, unclassified funding, coverage gaps and pending/failed jobs; deterministic next steps without observations or quote queries |
| FUT-003 | Not implemented | Date/range exports for assets, purchases, contributions and balances, plus a local report index; retain revisions/unknowns and distinguish different tracking scopes |
| FUT-004 | Not implemented | ETF shared-company/weighted overlap: define denominators/formulas, reuse official evidence/identities and disclose dates, parsing coverage and unknown weights |
| FUT-005 | Not implemented | Separate quantity, market-price and FX effects on value; define interaction allocation and identify splits/scope/mixed dates/missing quotes; quantity effects are not contributions |

WEB-007 operations acceptance is verified and merged. WEB-009 legacy compatibility is the active local candidate; WEB-008 remains the separate pull-only distribution track. Actual deployment/adoption remains an explicit operator action. WEB-006 is implemented and verified locally; it does not itself authorize deployment or private migration. FUT-002 remains an optional convenience feature. Bull funding-source classification
and transfer matching is next on the cash-flow track. Unfinished items do not block
currently supported updates.

## Internationalization (implemented and public)

Supported locales: `en-CA`, `zh-TW`, `zh-CN`. New installations default to English;
existing projects preserve Traditional Chinese. See [the locale guide](docs/i18n-plan.md)
for CLI/configuration and offline editions. Canonical documentation is English;
translated documentation and additional locales are separate work.

- [x] **I18N-001 Contracts/identities**: configuration precedence, stable message/sheet/category IDs, historical compatibility and unchanged financial fingerprints.
- [x] **I18N-002 Catalogs/formatting**: three JSON catalogs/registry, named parameters, Decimal/date formatting, version/completeness checks; no runtime LLM.
- [x] **I18N-003 ODS/MD/PDF/charts**: shared locale context, cross-sheet formulas, bundled fonts/layout and consistent unknown/zero semantics.
- [x] **I18N-004 Daily CLI/offline editions**: locale options, help/errors/previews, frozen operation locale and output without financial changes.
- [x] **I18N-005 Regressions/contributor tools**: matching amounts/formulas, missing/mixed-language/broken-reference rejection, additional-language guidance and planned plugin namespaces (SDK not implemented).
- [x] **I18N-006 Docs/public manifest**: README/manual/API/report/development contracts, reviewed JSON/font/doc paths and public manifests; preserve first-publication approval requirements.
- [ ] **I18N-007 More locales/translated documentation**: candidates fr-CA/ja-JP; verify formatting/fonts/terms/licenses and maintain complete translated README/manual editions separately.

## Extensible source adapters (contract/registry implemented; integration planned)

Product direction: one application for bank, brokerage, Bitcoin broker and exchange
exports through source-parser plugins. Wealthsimple and Bull Bitcoin are the first
built-in importers. Current support is format-specific, not universal CSV support.

- [x] **SRC-001 Versioned adapter/external parser protocol**: canonical `holdings`, `cash_flows`, `crypto_transactions`; source/account namespaces, stable IDs, time/currency, revisions/voids/coverage and ambiguous detection.
- [ ] **SRC-002 Registration/discovery/compatibility**: trusted Python parsers enabled explicitly or through versioned package entry points; reject duplicate adapter IDs/conflicting provider metadata, unknown API versions and ambiguous formats without changes to core ledger/reports.
- [x] **SRC-002A Independent registry library**: explicit exact distribution/version/entry-point enablement, metadata-only discovery, same-provider multiple formats, adapter/provider collision checks, API compatibility, deterministic detection/explicit selection and redacted failures. Existing CLI/Web imports are unchanged.
- [ ] **SRC-002B Source plans/configuration fingerprints**: shared CLI/Web selection, host configuration, input/mapping/catalog/plugin code and dependency digests, stale-preview rejection and bounded execution; protocol-v1 records remain unbookable through plugins.
- [ ] **SRC-003 Example plugin/contract test toolkit**: synthetic fixtures, detector/normalizer/validator examples and offline deduplication/revision/transfer/scope/privacy tests; author/install/enable instructions.
- [ ] **SRC-004 Existing-adapter migration/new sources**: move Wealthsimple/Bull to the versioned registry, prove ledger/CLI compatibility, then add banks, brokers and exchanges.

SRC-001 provides `wealth_ledger.source_protocol` dataclasses, pure adapter Protocol,
structural validation, auditable detection resolution and lossless evidence JSON.
SRC-002A adds the independent `wealth_ledger.source_registry` library for explicitly
enabled trusted loading/detection. It is not called by production import paths and
does not book records. SRC-002 remains open until SRC-002B integration is verified;
SRC-003-004 remain planned. Existing importers remain unchanged.

Current CSV support is Wealthsimple/Bull only. The official ETF registry is separate
from a general source-plugin system. Bank records can establish boundary cash flows
without adding bank cash to investment assets. External plugins run as trusted,
user-installed Python; never execute code from a CSV/network automatically or use
an LLM to generate/select parsers at runtime. See [adapter design](docs/source-adapters.md);
no SDK/install command is available yet.

The [implementation blueprint](docs/source-adapters.md#implementation-blueprint-planned-src-002-through-src-004) now specifies module boundaries, trusted-host loading, CLI/Web preview fingerprints, protocol-v2 completeness gaps, preserved identity bindings and phased acceptance. SRC-002A is now implemented and verified independently; source-plan fingerprints and generic ingestion remain unimplemented. Full decoupling requires the remaining integration and migration acceptance gates.

## Cash flows and additional data

- [ ] **Bull funding origins/transfer matching**: distinguish external bank contributions from tracked-account transfers, connect the flow ledger and avoid Funding/Buy/transfer double counting.
- [ ] **Combined portfolio period performance**: securities+BTC growth, Modified Dietz and XIRR require compatible sources, valuations, fees, transfers and complete flow coverage; currently disabled.
- [ ] **Native Wealthsimple activity conversion**: automate the currently manual unified-flow mapping under the adapter contract.
- [ ] **Flow revisions/voids and formal restore command**: retain audits without reverse fake transactions; SQLite backups exist, a formal restore CLI does not.
- [ ] **Independent BTC verification/scope changes/actual cost allocation**: quantity reconciliation exists; on-chain verification, explicit scope changes and acquisition/disposal costs need additional models/policies.
- [ ] **Other broker/bank/exchange adapters**: require sanitized format samples/official field descriptions and tests for IDs, fees, types and cross-source transfers; never claim unfinished support.

## Public-source preparation

- [x] **DEV-002 English public documentation**: canonical manuals/contracts/policies/examples in English, preserved locale resources and a bounded code-only CJK regression check in CI.
- [x] **DEV-001 Shared rules/private discovery**: concise AGENTS.md, topic development docs, ignored AGENTS.override.md, staged/history rejection tests and fresh-session checks; see [agent setup](docs/agent-development.md).
- [x] Generic public contracts/synthetic examples separated from private history and settings.
- [x] Public allowlist, index/push checks, clean source copies and synthetic acceptance independent of personal ledgers.
- [x] Public `actual_only` default, explicit `bull_average_proxy` configuration and regression checks.
- [x] MIT/font notices, CI and feature-branch/PR tooling connected to the public GitHub repository.
- [x] Fresh locked dependency install from official PyPI and offline tests/reports on macOS/Python 3.12.
- [x] Initial GitHub Linux/Python 3.12 acceptance: 263 tests, offline default/proxy and three-locale reports ([CI record](https://github.com/gh-slee/wealth-ledger/actions/runs/38828304491)).
- [ ] Additional platform acceptance; macOS/Linux success is not all-platform acceptance.
- [x] First public [gh-slee/wealth-ledger](https://github.com/gh-slee/wealth-ledger) push after manifest/history review and explicit approval.

Follow [publication procedures](docs/publishing.md); do not label unverified work as
published. Daily financial imports never commit or push source code.

## Other candidates

- [ ] Dividends, income, fees and realized P&L after complete transaction/income/fee sources.
- [ ] Target-allocation gaps using explicit user targets.
- [ ] Benchmarking, volatility and drawdown with compatible valuations, flows and return policies.
- [ ] Tax contributions/inception backfill under separate historical/tax models; investment flows are not CRA room.
- [ ] Optional Python scheduling/folder watch without inferring completeness or uploading private data.
- [ ] Private off-device/off-disk backups; same-disk SQLite copies are not complete backups.

## Data users may need to supply

- Deposits, withdrawals, transfers and coverage declarations; missing files do not establish zero flows.
- Earlier acquisition dates, actual costs and contribution evidence; holdings/BTC quantities cannot reconstruct historical spending.
- Optional dated BTC+LBTC totals for all tracked wallets and known fees/events; both CSVs and a balance are not required together each time.
- Bull funding origins; unknown origins are not automatically external portfolio contributions.

Known holdings can still be updated with incomplete data. Keep related analysis
marked incomplete; an average-cost proxy cannot establish actual historical cost
or clear unexplained differences.
