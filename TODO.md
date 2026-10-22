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
- [x] **FUT-001 Offline import preview**: optional `--dry-run`/`--json`; no real data, quote, backup, operation or report changes. Missing references remain pending; default parser preparation requires separate exact confirmation. Explicit native compatibility retains the original offline preview.

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

- [x] **WEB-009 Recognized legacy publication adoption**: implemented and verified locally with explicit pre-checksum acceptance, preserved report bytes/dates, separate migration-time evidence, three-locale UI notices and bound downloads/exports/backup restore. The implementation is merged; any deployment still needs its own fixed-version acceptance. See [legacy report adoption](docs/web-legacy-reports.md).

- [x] **WEB-010 Full Web report reading**: implemented and merged; complete saved sections/tables/charts, same-edition downloads, date/scope-grouped history, stable edition links and contextual grouped checks. See [report reading](docs/web-analysis-reports.md). Deployment remains a separate reviewed operation.
- [x] **WEB-011 Appearance modes**: implemented and merged; system/light/dark controls, semantic surfaces and interactive-chart colors, nonfinancial preference storage, three locales and browser/accessibility checks. Saved artifacts retain original styling; no rebuilt production deployment is claimed.
- [x] **UX-001 Product/UX assessment and prioritized implementation plan**: evidence-based page/journey review, first-use and plugin explanation, comparable-product references and fifteen P0/P1/P2 tickets with acceptance criteria; see [review and ticket index](docs/product-ux-review.md). This does not mark the whole redesign or all proposed features complete.

### Prioritized product and UX delivery

P0 is the first-use/trustworthy-update gate for this program. P1 adds core analytics
and operation capabilities; P2 adds optional/dependent extensions. Each row links to
its own problem, scope, dependencies, acceptance criteria and validation record.

| ID | Priority | Status | Ticket |
|---|---|---|---|
| UX-P0-001 | P0 | Verified locally; not merged | [First-use guidance](docs/ux-p0-001-first-run.md) |
| UX-P0-002 | P0 | Design proposed; implementation pending | [Evidence status and next actions / FUT-002](docs/ux-p0-002-status.md) |
| UX-P0-003 | P0 | Planned | [Understandable import/recovery](docs/ux-p0-003-imports.md) |
| UX-P1-001 | P1 | Planned | [Activity, contributions, transfers](docs/ux-p1-001-activity.md) |
| UX-P1-002 | P1 | Planned | [Eligible returns and attribution](docs/ux-p1-002-performance.md) |
| UX-P1-003 | P1 | Planned | [Income, fees, corporate actions](docs/ux-p1-003-income.md) |
| UX-P1-004 | P1 | Planned | [Targets and ETF overlap / FUT-004](docs/ux-p1-004-allocation.md) |
| UX-P1-005 | P1 | Planned | [Analysis workbench/drill-down](docs/ux-p1-005-analysis.md) |
| UX-P1-006 | P1 | Planned | [Source capabilities and extensions](docs/ux-p1-006-sources.md) |
| UX-P1-007 | P1 | Planned | [Pull-only distribution / WEB-008](docs/ux-p1-007-distribution.md) |
| UX-P2-001 | P2 | Planned | [Benchmarks/risk](docs/ux-p2-001-risk.md) |
| UX-P2-002 | P2 | Planned | [Goals/scenarios](docs/ux-p2-002-goals.md) |
| UX-P2-003 | P2 | Planned | [Mobile/balance privacy](docs/ux-p2-003-mobile.md) |
| UX-P2-004 | P2 | Planned | [Operations/account security UX](docs/ux-p2-004-operations.md) |
| UX-P2-005 | P2 | Planned | [Cost/tax evidence exports](docs/ux-p2-005-tax-evidence.md) |

Sequence: review/merge the locally verified P0-001 slice, then implement P0-002 and P0-003. Cross-linked existing
roadmap items are the same work, not duplicate implementations. Do not implement
financial-return features before their evidence/flow/valuation prerequisites.


This track does not complete the source-plugin SDK, new currencies or combined
performance automatically. Keep each stage planned until accepted; actual private
migration is a separate explicit operation.

## Daily operations and analysis

| ID | Status | Scope |
|---|---|---|
| FUT-002 | Not implemented | Unified read-only status: latest successful report, source dates/carried data, BTC gaps, unclassified funding, coverage gaps and pending/failed jobs; deterministic next steps without observations or quote queries |
| FUT-003 | Partially implemented | Web frozen CSV/JSON datasets and supported date ranges exist (WEB-005); broader unified CLI/range exports and a local report index remain. Preserve revisions/unknowns and tracking scopes; see UX-P1-005 |
| FUT-004 | Not implemented | ETF shared-company/weighted overlap: define denominators/formulas, reuse official evidence/identities and disclose dates, parsing coverage and unknown weights |
| FUT-005 | Not implemented | Separate quantity, market-price and FX effects on value; define interaction allocation and identify splits/scope/mixed dates/missing quotes; quantity effects are not contributions |

WEB-007 operations acceptance is verified and merged. The source-plugin daily workflow and legacy compatibility are implemented and merged; WEB-008 remains the separate pull-only distribution track. Actual deployment/adoption remains an explicit operator action. WEB-006 is implemented and verified locally; it does not itself authorize deployment or private migration. FUT-002 remains an optional convenience feature. Bull funding-source classification
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
- [x] **I18N-005 Regressions/contributor tools**: matching amounts/formulas, missing/mixed-language/broken-reference rejection, additional-language guidance and planned plugin message namespaces (not part of the parser SDK).
- [x] **I18N-006 Docs/public manifest**: README/manual/API/report/development contracts, reviewed JSON/font/doc paths and public manifests; preserve first-publication approval requirements.
- [ ] **I18N-007 More locales/translated documentation**: candidates fr-CA/ja-JP; verify formatting/fonts/terms/licenses and maintain complete translated README/manual editions separately.

## Extensible source adapters (default v2 integration implemented)

Product direction: one application for bank, brokerage, Bitcoin broker and exchange
exports through source-parser plugins. Wealthsimple and Bull Bitcoin are the first
built-in importers. Current support is format-specific, not universal CSV support.

- [x] **SRC-001 Versioned adapter/external parser protocol**: canonical `holdings`, `cash_flows`, `crypto_transactions`; source/account namespaces, stable IDs, time/currency, revisions/voids/coverage and ambiguous detection.
- [x] **SRC-002 Registration/discovery/compatibility (nonbooking parser path)**: trusted Python parsers enabled explicitly or through versioned package entry points; reject duplicate adapter IDs/conflicting provider metadata, unknown API versions and ambiguous formats without changes to core ledger/reports.
- [x] **SRC-002A Independent registry library**: explicit exact distribution/version/entry-point enablement, metadata-only discovery, same-provider multiple formats, adapter/provider collision checks, API compatibility, deterministic detection/explicit selection and redacted failures. Existing CLI/Web imports are unchanged.
- [x] **SRC-002B Nonbooking source plans/configuration fingerprints**: shared CLI/API runner, strict trusted-host configuration, input/mapping/catalog/normalized digests, actual runtime/core/site-file hashes, fresh child/timeout, stale-plan rejection and API/worker environment checks. Owner-scoped source_csv/source_plan jobs cannot confirm/resume financially and expire on restore. Protocol-v1 records remain unbookable; the separate v2 workflow supplies financial publication; SRC-003 supplies the SDK.
- [x] **SRC-003 Installable core/example plugin/contract toolkit**: audited core wheel/sdist with fonts/locales/aliases, installed nonbooking CLI, shared contract assertions and independent synthetic plugin; overlap/revision/transfer/scope/privacy fixtures, native/derived-image instructions and isolated install/CLI/API-worker/three-locale report acceptance. This does not implement stateful ingestion.
- [x] **SRC-004 Existing-adapter migration/extension pipeline**: Wealthsimple/Bull use the versioned registry through default CLI/browser preparation, exact approval and source-neutral reports. Original native IDs/history and explicit compatibility paths remain. Additional real banks, brokers and exchanges still require specified, sanitized formats and parser acceptance; no universal CSV support is implied.
- [x] **SRC-004A Canonical ingestion foundation**: immutable host context and lossless v2 records, additive portfolio-scoped bindings/append-only facts/scopes/effects, strict archived replay, state/code revalidation, atomic operation receipts, backup/empty restore and explicit report-projection phase gate. This low-level API remains data-only; use the separate default publication workflow for daily reports.
- [x] **SRC-004B Built-in/production pipeline migration**: pure Wealthsimple/Bull v2 parsers, isolated context-aware plans, compatible central submission with frozen evidence, portfolio mappings and CLI/Web confirmation/recovery parity; keep original IDs/history.
- [x] **SRC-004B1 Pure built-ins/context previews**: one byte-only grammar per current format shared with legacy imports, explicit v2 built-in registrations, isolated context-aware CLI/API previews, strict frozen normalization and legacy ID/financial-field parity. These explicit developer preview commands remain nonbooking; the separate default workflow handles publication.
- [x] **SRC-004B2 Opt-in canonical submission/recovery**: frozen raw/normalized evidence, explicit portfolio mapping review and exact approval, CLI/owner-only isolated API confirmation, atomic receipt-only recovery, completed native-order compatibility and restore invalidation. This is data-only with an explicit no-report acknowledgement; daily report publication uses the separate C3C2 approval workflow.
- [x] **SRC-004C Source-neutral projections/extension acceptance**: replace provider dispatch across valuation/history/report projections, preserve unknown/completeness semantics and verify a synthetic third provider through real imports/reports without new provider branches. Real additional institutions need a specified/sanitized format.
- [x] **SRC-004C1 Read-only source-neutral model**: internal verified position/coverage, native CAD/USD and explicit CAD/USD/TWD display conversion, classified recorded cash flows and BTC/LBTC movement/purchase projections; deterministic no-parser/no-write model. Legacy merge, full balances, performance and report publication remain gated. See [projection semantics](docs/source-projections.md).
- [x] **SRC-004C2 Read-only legacy/wallet/history integration**: explicit identity/signature overlap proofs, preserved unmatched legacy history and original IDs, shared pure wallet reconciliation, unchanged opening/anchor/event links, opt-in Bull-cohort cost proxy, explicit reference-price valuation and declaration-covered account cash-flow dates with historical FX. Full-portfolio returns remain unknown without complete evidence; later C3 work connects declarations/publication. See [compatibility contract](docs/source-projections.md#legacy-and-wallet-compatibility-src-004c2).
- [x] **SRC-004C3 Daily workflow/publication acceptance**: connect source-neutral projections to CLI/Web valuation/recovery and three-locale ODS/Markdown/PDF/charts, prove a synthetic third parser through actual reports, and verify backup/empty restore. Default routing is implemented; native-only renderers retain their canonical-data omission guard.
- [x] **SRC-004C3A Source-aware BTC declarations**: CLI/Web balance expectations, interval links and queries use verified compatible sources; source-neutral fixed openings freeze deduplicated acquisition/event references, retain revisions and unknown costs, and detect later backfill without rebasing. These declaration commands remain data-only; publication is separate. See [declaration boundary](docs/source-projections.md#source-aware-btc-declarations-src-004c3a).
- [x] **SRC-004C3B Report payload and valuation core**: trusted-core payloads from verified saved native/canonical CSV facts, explicit FX/BTC quotes, append-only derived valuation editions, receipt-only recovery and three-locale ODS/Markdown/PDF/charts. Preserve dates/IDs/unknowns and observed-subtotal scope; full backup/empty-volume restore retains editions. C3C supplies ordinary routing/publication; see [the core contract](docs/source-projections.md#source-report-payloads-and-frozen-valuations-src-004c3b).
- [x] **SRC-004C3C Complete daily cutover acceptance**: shared CLI/Web ordinary import/mapping/confirmation/publication/recovery, synthetic third parser through actual reports, full backup/empty restore and original frozen-history preservation are verified locally. Native compatibility cannot bypass canonical-data guards.
- [x] **SRC-004C3C1 Frozen source report publication/advanced CLI**: explicit-context/mapping/reference approval, atomic facts/derived valuation/frozen ETF analysis, checksummed three-format publication and receipt-only retry; installed synthetic v2 third-parser acceptance and backup/empty restore. Advanced explicit-context entry remains available alongside the default preparation workflow.
- [x] **SRC-004C3C2 Ordinary CLI/Web cutover**: connect automatic source identification/context defaults and explicit mapping review to regular upload/preview/confirm/jobs; optional BTC-only/either-source/both-source/saved-data flows, source-aware browser read/export views, recovery and full browser/container/history preservation acceptance. Explicit saved-context selection, revision parents and dated source-account contribution/coverage declarations are implemented; native guards remain necessary.
- [x] **SRC-004C3C2A Source Web publication/read/export**: explicit source-report API previews/exact approval use isolated existing jobs, immutable publications and ordinary report library/downloads; source-aware read/export DTOs preserve provenance, observed-subtotal scope and unknowns. Browser job review/confirms exact digests; interrupted registry publication and full empty restore have synthetic acceptance. The default browser form now uses the separate automatic preparation entry.
- [x] **SRC-004C3C2B Automatic CLI/Web entry**: shared isolated source detection/frozen host defaults, editable account mappings in regular upload forms, optional BTC-only/either/both/saved inputs, explicit reference policies, exact approval and receipt-only recovery. The regular CLI/browser now default to this path; explicit native compatibility keeps its guard; see [usage and boundaries](docs/source-projections.md#automatic-import-entry-src-004c3c2b).
  Default workflow acceptance covers explicit saved contexts/corrections, native/mixed source history, installed third-parser reports, three-locale browser exports and full empty-volume restore including canonical manual cash flows. The cutover is merged; fixed-version deployment/adoption acceptance remains separate. No personal migration or additional real institution is implied. See [daily usage](docs/source-projections.md#default-daily-workflow).


The implemented pipeline uses versioned protocol/registry discovery, isolated
trusted parsing, explicit host context and portfolio bindings, frozen exact approval,
append-only facts, source-neutral valuation and immutable three-format reports.
V1 source-plan commands and low-level data-only ingestion remain nonbooking/no-report
interfaces; use [the default daily workflow](docs/source-projections.md#default-daily-workflow)
for financial imports and reports. Original native history, report bytes and IDs are
preserved; native-only projections reject canonical facts instead of omitting them.

Current real CSV support is Wealthsimple/Bull only. The independently installed
synthetic plugin proves extension through CLI/API/worker/reports, not a third real
institution. Official ETF reference adapters are a separate system. Bank records
can establish boundary cash flows without establishing bank asset balances.
External plugins run as trusted, user-installed Python; never execute code from an
upload/network automatically or use an LLM to generate/select parsers at runtime.
See [adapter design](docs/source-adapters.md), [SDK/install acceptance](docs/parser-sdk.md)
and [the original implementation blueprint](docs/source-adapters.md#implementation-blueprint-planned-src-002-through-src-004).

The existing parser cutover is implemented and merged. Further source-capability UX
is tracked by UX-P1-006; new real institutions require format-specific fixtures and
tests. Deployment/adoption requires a fixed reviewed version and separate operator evidence.
Pull-only multi-architecture distribution remains WEB-008; no image release is implied.

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
