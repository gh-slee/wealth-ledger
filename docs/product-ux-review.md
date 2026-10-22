# Investment tracking product and UX review

Review baseline: merged `167884b`, 21 October 2026. This is a product assessment of
the implemented source, synthetic browser workflows and README gallery, not a claim
that the proposed features are shipped. Implementation acceptance is recorded in
each ticket. Public roadmap status and private deployment state are separate.

## Audience and product job

An individual or household self-hosts one instance, with independent portfolios,
then consolidates bank, brokerage and Bitcoin exports into a traceable investment
record. The product is a tracking and analysis workspace; trading execution,
custody, investment recommendations and jurisdiction-specific tax filing are
outside the current product boundary.

The main questions are: What do I own? At what date and with what evidence? What
changed? How much did I contribute? What can I safely do next? The default view
should answer these before exposing parser terminology, audit details or a large
set of advanced controls.

## Current state and evidence

| Area | Implemented | Remaining boundary / evidence |
|---|---|---|
| Identity and portfolios | Host-initialized owner, sign-in, isolated portfolios and settings | One owner per instance; no browser registration or household roles. `web/auth.py`, `App.tsx`. |
| First report | Default parser upload, mappings, preview/approval, jobs and publication | Previous empty state had one short upload link; context/reference choices need more explanation. `components/imports.tsx`. |
| Daily analysis | Overview, searchable/sortable holdings, history, BTC, classifications, ETF company rankings | Frozen saved editions, not live quotes. Display totals support CAD/USD/TWD; native securities remain CAD/USD. `components/analysis.tsx`. |
| Reports | Full saved analysis reader; ODS/Markdown/PDF and CSV/JSON/ZIP exports | Editions at one date are not separate observations. `report-reader.tsx`, `web/report_document.py`. |
| Financial evidence | BTC totals/events/openings, cash flows and coverage declarations | Bull funding origins/transfer matching and complete combined period returns remain incomplete. `financial.tsx`, `web-financial-records.md`. |
| Sources | Two real built-in v2 parsers; pinned external registry/SDK; installed synthetic third-parser acceptance | Not universal CSV support. No broker authentication, marketplace or automatic plugin installation. Some preview labels still need generic fallbacks (UX-P0-003). `source_builtin.py`, `source_registry.py`, browser parser publication tests. |
| Operations | Dedicated persistent volume, full private backup, empty-target restore, explicit legacy adoption | Prebuilt pull-only distribution and broader host acceptance remain WEB-008. Host commands are still required. |
| Presentation | Three locales, dark/light/system, keyboard paths, chart data tables, synthetic accessibility tests | Empty, loading and recovery experiences need further coverage. No full visual-system replacement is included in this first slice. |

Files above are under `src/wealth_ledger/`, `frontend/src/`, or `docs/` as applicable.
A checked roadmap item is not evidence that every possible broker or platform works.

## Page-by-page findings

| Page / journey | Finding | Follow-up |
|---|---|---|
| Sign-in and first portfolio | Anonymous startup can look like an expired session; portfolio loading can briefly resemble an empty account. Creating a ledger needs an explanation of what is created. | UX-P0-001 |
| Empty portfolio | A short upload CTA omits source requirements, baseline choice, reports and later contribution backfill. Absence of a report must not look like a zero balance. | UX-P0-001 |
| Overview | Evidence rail and saved-value wording are useful. Read-only actionable status should connect missing evidence to next steps without burying values under repeated warnings. | UX-P0-002, UX-P1-005 |
| Import and jobs | Exact confirmation and mapping guards exist. Technical terms, source context, price references and recovery states need staged explanations. | UX-P0-003 |
| Holdings and exposure | Useful sorting/filtering and whole-portfolio ETF look-through already exist. Currency treatment, drill-down and target/overlap views need consistent scope. | UX-P1-004, UX-P1-005 |
| History and reports | Frozen editions and grouped observations exist; value growth must remain distinct from returns. Add compatible range controls and eligibility explanations. | UX-P1-002, UX-P1-005 |
| Bitcoin and financial records | Quantity declarations, unknown costs and event links are implemented; users still need a cohesive activity/contribution view. | UX-P1-001, UX-P0-002 |
| Settings and operations | Language/cost policy/password settings exist; parser capabilities and backup/restore discoverability remain weak. | UX-P1-006, UX-P2-004 |

## Market reference, not a demand survey

Official product descriptions were reviewed on 21 October 2026:

- [Sharesight features](https://www.sharesight.com/features/): cross-asset performance,
  currency effects, dividends, allocation and reporting.
- [Portfolio Performance dashboard manual](https://help.portfolio-performance.info/en/reference/view/reports/performance/dashboard/):
  portfolio value, contributions, money/time-weighted returns, target allocations,
  earnings and risk views, with data requirements for risk calculations.
- [Ghostfolio official repository](https://github.com/ghostfolio/ghostfolio#features):
  multiple accounts, transaction import/export, performance, charts, dark mode and
  mobile-focused usage.

These establish recurring feature categories across comparable products. They are
not measured customer-request counts or proof of a market-wide popularity ranking.
Priorities below are product judgment for this evidence-first tracker. Features
requiring complete transactions, costs, prices or flows must expose missing evidence
instead of guessing values to match a competitor's screen.

## Priority and sequencing

P0 means a first-use or trustworthy-update blocker for this UX program, not an
unverified security incident. P1 supplies core analytical and operating capabilities;
P2 is a later extension with additional data, design or operational dependencies.
Tickets are separately scoped; a roadmap entry does not itself ship a feature.

| ID | Priority | Ticket | Status |
|---|---|---|---|
| UX-P0-001 | P0 | [First-use and empty-state guidance](ux-p0-001-first-run.md) | Verified locally; not merged |
| UX-P0-002 | P0 | [Evidence status and next actions](ux-p0-002-status.md) | Planned |
| UX-P0-003 | P0 | [Understandable import and recovery](ux-p0-003-imports.md) | Planned |
| UX-P1-001 | P1 | [Activity, contributions and transfers](ux-p1-001-activity.md) | Planned |
| UX-P1-002 | P1 | [Eligible performance and attribution](ux-p1-002-performance.md) | Planned |
| UX-P1-003 | P1 | [Income, fees and corporate actions](ux-p1-003-income.md) | Planned |
| UX-P1-004 | P1 | [Targets and ETF overlap](ux-p1-004-allocation.md) | Planned |
| UX-P1-005 | P1 | [Analysis workbench and drill-down](ux-p1-005-analysis.md) | Planned |
| UX-P1-006 | P1 | [Source capabilities and extension UX](ux-p1-006-sources.md) | Planned |
| UX-P1-007 | P1 | [Pull-only self-host installation](ux-p1-007-distribution.md) | Planned / WEB-008 |
| UX-P2-001 | P2 | [Benchmarks and risk](ux-p2-001-risk.md) | Planned |
| UX-P2-002 | P2 | [Goals and scenarios](ux-p2-002-goals.md) | Planned |
| UX-P2-003 | P2 | [Mobile and balance privacy](ux-p2-003-mobile.md) | Planned |
| UX-P2-004 | P2 | [Operations and account security UX](ux-p2-004-operations.md) | Planned |
| UX-P2-005 | P2 | [Cost and tax evidence exports](ux-p2-005-tax-evidence.md) | Planned |

Review/merge the locally verified P0-001 slice, then implement P0-002 and P0-003 before expanding analytical scope.
Performance depends on contribution/transfer and valuation evidence; income and
corporate-action models need their own contracts. Track distributions through
WEB-008 rather than pretending a currently available public image exists.

## Design direction for incremental delivery

Keep the clear investment workbench: summary first, layered analysis and details on
demand. Retain existing accessible fonts (IBM Plex Sans Condensed headings, Atkinson
Hyperlegible body and tabular numeric alignment) and semantic tokens. Light tokens
are navy `#193b51`, teal `#157f7a`, muted `#526c7c`, canvas `#eef3f6`, paper `#fcfdfe`
and amber `#965422`; use existing dark counterparts rather than literal light colors.
The signature is the evidence-date rail connecting each amount to its observation.
Use step numbers only for the actual prepare/review/confirm sequence. Do not add a
marketing hero, trading-terminal density, decorative gradients or investment advice.

First-use layout:

```text
Portfolio / Overview
No published report
Start with your first observation
  1 Choose available evidence
  2 Preview dates and account destinations
  3 Confirm, then read and download
[Add your first observation]
[What should I prepare?] expandable requirements
Contributions: explain later evidence and links to records/settings
```

The first slice intentionally improves the empty journey rather than replacing all
nine screens. Review mobile, keyboard, screen-reader names, dark mode, all locales,
no-report versus loading/error and populated-portfolio regressions. New screenshots
must use the isolated synthetic fixture and follow the gallery maintenance policy.
There is no runtime AI, live revaluation on page load or private data migration.

## Starting from scratch and source plugins

Use [the first-use guide](getting-started.md) for installation, first observation,
contributions and irregular updates. Use [the adapter contract](source-adapters.md)
and [SDK guide](parser-sdk.md) for exact plugin boundaries. Do not install Python
from an uploaded CSV, silently enable a detector or translate a v1 batch into a
bookable v2 batch. New real formats require sanitized samples and acceptance tests.

## Optional design-tool workflow

Future UI tasks prefer the reviewed [Impeccable workflow](ui-design-workflow.md)
when available. The earlier assessment and P0-001 implementation used separate
frontend-design guidance; this integration does not retroactively reattribute them
or replace the established visual system. Ticket priority and finance safeguards
remain unchanged.
