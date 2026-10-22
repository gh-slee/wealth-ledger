<p align="center">
  <img src="assets/readme/wealth-ledger-mark.svg" width="76" height="76" alt="Wealth Ledger icon">
</p>

<h1 align="center">Wealth Ledger</h1>

<p align="center">
  <strong>Your financial CSVs. One investment ledger. Your own server.</strong><br>
  Bring bank, brokerage, and Bitcoin platform exports into a shared tracking and reporting workflow as source support grows.
</p>

<p align="center">
  <a href="https://github.com/gh-slee/wealth-ledger/actions/workflows/ci.yml"><img src="https://github.com/gh-slee/wealth-ledger/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status on main"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/Frontend-React%20%2B%20TypeScript-149ECA?style=flat-square&amp;logo=react&amp;logoColor=white" alt="React and TypeScript frontend"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.12 or newer"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/Deploy-Docker%20Compose-2496ED?style=flat-square&amp;logo=docker&amp;logoColor=white" alt="Docker Compose deployment"></a>
  <a href="#tech-stack"><img src="https://img.shields.io/badge/Storage-SQLite-003B57?style=flat-square&amp;logo=sqlite&amp;logoColor=white" alt="SQLite storage"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-208C8A?style=flat-square" alt="MIT license"></a>
  <a href="#project-status"><img src="https://img.shields.io/badge/Status-Pre--release-D3973F?style=flat-square" alt="Pre-release"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#sources-and-parser-plugins">Sources &amp; plugins</a> ·
  <a href="#screenshots">Screenshots</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

Wealth Ledger is an **open-source, self-hosted investment ledger** for tracking assets, contributions, and history across financial data sources. Its direction is a shared application for **bank, brokerage, Bitcoin broker, and exchange CSV exports**, with source-specific formats handled by reusable parser plugins as that architecture is completed.

Review supported inputs in an offline preview, confirm the import, and browse frozen portfolio analysis. Export **ODS, Markdown, PDF, PNG charts, and audit CSV/JSON** from the same data. One owner or household can keep multiple independent portfolios in an instance, through a React/TypeScript interface or the supported **Python CLI**. Both use the same Python financial core.

**Available today:** built-in importers for Wealthsimple holdings and Bull Bitcoin orders, plus normalized cash-flow CSVs and optional dated BTC quantities. The default v2 parser workflow supports approved imports and reports from trusted enabled plugins. Additional real institutions require implemented format adapters; arbitrary CSVs are not accepted. See [sources and parser plugins](#sources-and-parser-plugins) for the expansion plan.

**Pre-release:** the browser import/analysis/report workflow is implemented and tested with synthetic fixtures. Full private backup/restore and report/data exports are implemented; financial declaration forms and trusted-host, copy-verified adoption of existing CLI data are implemented. See [project status](#project-status).

## Features

| | What you can do |
|---|---|
| 🗂️ **Independent portfolios** | Sign in to your instance and keep separate ledgers, settings, source evidence, and reports. |
| 📥 **Preview before importing** | Provide supported source exports independently or together, or a dated BTC quantity. Review source dates and checks, then explicitly confirm the background job. |
| 💱 **Three valuation currencies** | View CAD/USD/TWD equivalents, with account filters and separate native CAD/USD securities. |
| 📊 **Interactive analysis** | Explore holdings, account allocation, recorded value history, BTC purchases, and sector/country/region exposure. |
| 🔎 **ETF company exposure** | Rank the top 20 companies across direct stocks and supported ETF constituents; retain effective dates and unresolved coverage. |
| 🧾 **Traceable history** | Preserve original evidence and append-only revisions. Irregular submissions use actual observation dates, without inventing missing month-end balances. |
| 📄 **Portable reports** | Download formula-based ODS spreadsheets, Markdown, PDF, chart images, and applicable audit attachments. |
| 🌐 **Three languages** | Use English, Traditional Chinese, or Simplified Chinese for the interface and report presentation. |

## Sources and parser plugins

The shared application owns history, validation, valuation and reports; trusted
parser plugins own institution-specific export formats. Versioned contracts,
explicit registration, an installable SDK, isolated parsing and frozen confirmation
are implemented. The built-ins cover the two formats below; an independent synthetic
plugin verifies the extension path without pretending to support another institution.

The default [parser-based import entry](docs/source-projections.md#automatic-import-entry-src-004c3c2b)
now connects the regular CLI and browser upload form to account-mapping review,
exact approval, source-aware analysis and ODS/Markdown/PDF exports. Either CSV, both,
optional BTC totals and saved-data valuations share one preparation core. Explicit native compatibility routes remain available; personal migration and
publication/deployment are separate operator steps.

| Source or input | Current support |
|---|---|
| Wealthsimple | Built-in holdings CSV importer for documented export formats. |
| Bull Bitcoin | Built-in order CSV importer for documented funding and purchase records. |
| Normalized cash-flow CSV | Shared contribution/withdrawal/transfer input for tracked accounts; native bank activity must currently be mapped to this format. |
| Dated BTC quantity | Optional total-balance observation, independent of either source CSV. |
| Other banks, brokers, Bitcoin platforms, and exchanges | Planned parser plugins; arbitrary source CSVs are not accepted today. |

Plugins must declare export versions, record types and completeness. Arbitrary CSVs
are not accepted automatically, and bank cash-flow records do not establish bank
asset balances. Parsing, financial processing and official ETF downloads run entirely
in code, with no runtime LLM calls.

To contribute a source, read the [adapter contract](docs/source-adapters.md),
[SDK build/install guide](docs/parser-sdk.md), [roadmap](TODO.md) and
[contribution guide](CONTRIBUTING.md). Financial booking uses the v2 contract and
explicit approval; v1 source plans remain nonbooking. Never upload real financial
exports to public issues.

## Quick start

### Self-host with Docker Compose

Prerequisites: **Git**, **Python 3.12+** for the source-context helper, and **Docker with Compose v2**. The helper uses Python's standard library; it does not require the financial dependencies. Docker builds the frontend and installs the server dependencies inside the image.

```bash
git clone https://github.com/gh-slee/wealth-ledger.git
cd wealth-ledger

# Prepare a source-only build context; private workspaces are excluded.
python3 scripts/docker_context.py --output work/docker-context

docker compose build web
docker compose run --rm web init-owner
docker compose up -d
```

Open **[http://localhost:8000](http://localhost:8000)**. Sign in as `owner` using the password you set on the host, create a portfolio, and open **Import & jobs**. New instances start with no financial history or personal accounts. Try the [invented example files](examples/README.md) first.

The `web` and `worker` services share the private `wealth-data` named volume. Initialize the owner once. `docker compose down` retains the volume; deleting the volume removes its data. The sample deployment binds to loopback. For HTTPS, remote access, upgrades, fresh rebuild contexts, and password resets, follow [Web operations](docs/web-operations.md) and the [upgrade/rollback runbook](docs/web-release-acceptance.md).

Prebuilt multi-architecture images and a pull-only Compose recipe are planned. Current installation builds locally. The platform/evidence matrix is in [operations acceptance](docs/web-release-acceptance.md); Windows and macOS hosts use Linux containers.

**Existing CLI users:** keep your current workspace. Pointing the Web app at an old ledger is not a supported migration. Use the explicit [copy-verified adoption commands](docs/web-adoption.md), preserving the original workspace. Recognized older reports require an explicit [legacy acceptance preview](docs/web-legacy-reports.md); their separate migration-time evidence does not replace missing historical publication checksums.

<details>
<summary><strong>Use the Python CLI or try an offline report demo</strong></summary>

From the cloned repository, install the core dependencies with Python 3.12+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python examples/demo.py --output work/demo
```

Open `work/demo/portfolio.ods`, `work/demo/report.md`, or `work/demo/report.pdf`. The demo creates its own temporary synthetic ledger and performs no market/reference downloads. Choose a new output directory for each run.

On Windows, use `.venv\Scripts\python.exe` instead of Unix activation. Broader Windows acceptance remains pending. See the [example guide](examples/README.md) and [user manual](docs/user-manual.md) for supported inputs, private `--workspace` directories, opening declarations, contributions, BTC events, and recovery.

</details>

### Your first import

1. Create or select an independent portfolio.
2. Supply a Wealthsimple holdings CSV, a Bull Bitcoin order CSV, both, or an optional **BTC quantity with its observation time**. A BTC quantity is not its CAD/USD market value.
3. Review the preview and any missing references. Choose a saved source context or enter the required host settings, then review account mappings. Unknown opening quantities remain unknown; see the [browser guide](docs/web-frontend.md).
4. Confirm the import and leave the worker running. Once published, open the analysis pages or **Analysis reports**. Read the full saved report with charts and tables, then download PDF, ODS, Markdown or a complete ZIP from the same page. System, light and dark themes are available.

Use **Financial records** for cash-flow coverage, contributions and BTC openings/balances/events, including append-only corrections. The same operations remain available in the CLI. Holdings changes and purchase spending do not establish contributions. See [financial declarations](docs/web-financial-records.md).

## Screenshots

The following are actual application screens from a **disposable synthetic portfolio**,
using only the [public example data](examples/README.md). Accounts, amounts, holdings,
prices and dates are invented. These are saved demonstration reports, not live quotes
or a maintainer's financial data. Screenshots show the current UI; a broader design
review remains separate planned work.

### Portfolio overview

<p align="center">
  <img src="assets/readme/web-overview.png" width="1200" alt="Synthetic portfolio overview with a saved CAD value, source dates, account allocation and recorded observation chart">
</p>

**Example:** inspect a saved CA$1,930.00 portfolio across four accounts, switch the
display currency between CAD/USD/TWD, and compare the valuation cutoff with each
source's date. Opening the overview does not refresh prices or create an observation.

Expand a page below to see its screen and an example task:

<details>
<summary><strong>Sign in — access your own instance</strong></summary>

<img src="assets/readme/web-login.png" width="1200" alt="Wealth Ledger sign-in page with blank username and password inputs">

Sign in with the account created on your host. Each instance has one owner or
household and can contain independent portfolios. The screenshot contains no entered
credentials; the demonstration account is used only in the disposable fixture.

</details>

<details>
<summary><strong>Holdings — compare accounts and native currencies</strong></summary>

<img src="assets/readme/web-holdings.png" width="1200" alt="Synthetic holdings table with account and CAD/USD filters, quantities, costs and saved valuations">

**Example:** filter the invented TFSA, RRSP or non-registered holdings, then compare
CAD and USD securities. The CAD-valued BTC proxy is kept outside this native-currency
securities table and appears on the Bitcoin page.

</details>

<details>
<summary><strong>Exposure — inspect company concentration and ETF holdings</strong></summary>

<img src="assets/readme/web-exposure.png" width="1200" alt="Synthetic sector allocation, classification coverage and ranked company exposure through direct stocks and ETFs">

**Example:** inspect sector/country/region allocation and the top-20 company ranking,
including direct stocks and ETF constituents. Whole-portfolio weights include cash;
effective dates, unresolved constituents and classification coverage remain visible.

</details>

<details>
<summary><strong>History — track actual recorded observations</strong></summary>

<img src="assets/readme/web-history.png" width="1200" alt="Synthetic history page showing one recorded observation and its exact table values">

This example has **one observation**, so the chart shows one point. More dated inputs
build the timeline; the app does not fabricate missing month-end balances. Multiple
report editions at one cutoff do not become additional financial observations.
Value changes alone are not contribution-adjusted investment returns.

</details>

<details>
<summary><strong>Bitcoin &amp; flows — review purchases, quantities and funding</strong></summary>

<img src="assets/readme/web-bitcoin.png" width="1200" alt="Synthetic Bitcoin page with BTC equivalent quantities, known costs and monthly purchase-rate table">

**Example:** review BTC/LBTC quantities, saved valuations and monthly quantity-weighted
CAD/BTC purchase rates. Purchase spending and funding remain distinct from proven
external contributions; unknown wallet fees, acquisition costs and cash-flow coverage
are disclosed rather than filled with zero.

</details>

<details>
<summary><strong>Import &amp; jobs — preview supported CSVs before confirmation</strong></summary>

<img src="assets/readme/web-imports.png" width="1200" alt="Synthetic import form with the public Wealthsimple holdings and Bull Bitcoin order examples selected">

**Example:** select `examples/data/wealthsimple-holdings.csv` and
`examples/data/bull-orders.csv`, or provide either independently. Review detected
sources, account mappings and checks before confirming. The screenshot shows selected
sample files **before upload/preview**; no import is confirmed by the capture script.
See [the browser workflow](docs/web-frontend.md) for saved contexts, reference inputs
and job recovery.

</details>

<details>
<summary><strong>Financial records — enter contributions and BTC declarations</strong></summary>

<img src="assets/readme/web-records.png" width="1200" alt="Financial records form filled with an unsaved invented BTC total, observation timestamp and synthetic evidence source">

**Example:** enter an invented `0.00950000 BTC` total with the explicit timestamp
`2024-02-02T12:00:00-05:00` and a source reference. This is an **unsaved form example**,
not a wallet confirmation. The same page supports contributions, coverage, openings,
fees/events and append-only corrections through preview and confirmation. Saving a
record and generating a report are separate actions.

</details>

<details>
<summary><strong>Analysis reports — read the full report and download the same edition</strong></summary>

<img src="assets/readme/web-reports.png" width="1200" alt="Analysis reports page with original PDF, ODS and Markdown downloads, report context and grouped history">

<img src="assets/readme/web-report-reader.png" width="1200" alt="Saved report reader with a section contents rail and the original analysis tables from the synthetic edition">

**Example:** read saved sections and charts, filter/sort report tables, and download
PDF, ODS, Markdown, a complete report ZIP or frozen CSV/JSON datasets. History groups
editions by date and scope. The reader preserves the original report's language and
assumptions; viewing or exporting does not regenerate the report.

</details>

<details>
<summary><strong>Settings — choose future report language and cost policy</strong></summary>

<img src="assets/readme/web-settings.png" width="1200" alt="Synthetic portfolio settings showing future report language and actual known BTC cost policy, with blank password-change fields">

**Example:** choose the language for future reports and an explicit BTC cost policy.
Changing settings does not rewrite old report editions. Interface language and
system/light/dark appearance are separate controls. Password fields are blank in
this screenshot.

</details>

<details>
<summary><strong>Dark mode — use system, light or dark appearance</strong></summary>

<img src="assets/readme/web-overview-dark.png" width="1200" alt="The same invented portfolio overview in dark mode with theme-aware chart axes and tables">

The browser stores only the nonfinancial appearance preference. Original downloadable
reports and saved PNG charts keep their publication styling.

</details>

[Reproduce and review these synthetic screenshots](assets/readme/README.md).

## Architecture

```mermaid
flowchart TB
    Browser["React + TypeScript UI"] <-->|"Sessions and CSRF"| API["FastAPI"]
    API -->|"Confirmed updates"| Jobs["Huey / SQLite jobs"]
    Jobs --> Worker["Isolated Python worker"]
    Worker --> Core["Shared Python financial core"]
    CLI["Python CLI"] --> Core
    References["Official ETF / FX / BTC references"] --> Core
    subgraph Private["Private portfolio workspace"]
        Ledger["SQLite + original source evidence"]
        Reports["Frozen reports + analysis attachments"]
    end
    Core --> Ledger
    Core --> Reports
    API -->|"Verified reads and downloads"| Reports
```

The browser reads **published observations**. Opening a page does not fetch market quotes, revalue history, or regenerate reports. Formal analysis uses the latest published data from supported official issuers and retains effective/retrieval dates, hashes, and classification coverage. Historical FX and BTC prices remain frozen.

Docker uses a Node build stage for static frontend assets. The final image runs Python API/worker processes and serves those assets. Financial features require no LLM, Codex, or local LibreOffice. [Architecture and contracts](docs/self-hosted-webapp.md).

## Tech stack

| Layer | Technology |
|---|---|
| **Browser UI** | React, TypeScript, Vite, Tailwind CSS, local shadcn/Radix components, Lucide icons |
| **Navigation and data views** | React Router, TanStack Query, TanStack Table, ECharts SVG charts |
| **API and authentication** | FastAPI, Pydantic, Uvicorn, Argon2id password hashes, opaque server-side sessions |
| **Background jobs** | Huey with SQLite notifications and isolated Python execution |
| **Storage and arithmetic** | SQLite / Python `sqlite3`, `decimal.Decimal`, satoshi precision; Decimal.js for browser display/sorting |
| **Report generation** | Matplotlib, ReportLab, pypdf, direct ODF/XML packaging, bundled Noto fonts |
| **Deployment** | Docker multi-stage build, Docker Compose, persistent private volume |
| **Verification** | Python `unittest`, Vitest, Playwright, accessibility checks, formula/cache validation, GitHub Actions |

Pinned dependencies live in [requirements.lock](requirements.lock), [requirements-web.lock](requirements-web.lock), and [frontend/package-lock.json](frontend/package-lock.json). Node is a build/test dependency, not a production server. [Third-party notices](THIRD_PARTY_NOTICES.md).

## Reports

| Output | Purpose |
|---|---|
| `portfolio.ods` | Formula-based spreadsheet tables, cached results, embedded chart images, and font licensing. |
| `report.md` | Readable analysis and tables with relative chart links; download the chart attachments too. |
| `report.pdf` | Portable fixed-layout analysis with embedded fonts and charts. |
| `charts/` | PNG figures from the same report run. |
| Report ZIP / CSV / JSON exports | Complete registered edition with relative chart links, or selected frozen datasets with supported date ranges. |
| JSON and CSV attachments | Frozen financial payload, source evidence, applicable company/classification detail, and BTC reconciliation/cost audits. |

Reports cover account/native-currency holdings, CAD/USD/TWD totals, concentration, ETF company exposure, classifications, BTC accumulation and purchase rates, recorded history, cash-flow coverage, and quality findings. [Report specification](docs/report-spec.md) · [ODS implementation](docs/workbook.md) · [Exports and private backups](docs/web-backups.md).

Successful updates preserve report editions. Unknown values stay distinct from zero. Unrealized P/L is not a period return; combined brokerage-plus-BTC Modified Dietz/XIRR remains disabled until the necessary flow, scope, and valuation coverage exists. The default cost policy uses actual known costs; a Bull average-cost estimate is an explicit opt-in, not reconstructed acquisition history.

<details>
<summary><strong>Exported report preview</strong></summary>

<img src="assets/readme/report-preview.png" width="1120" alt="Synthetic exported report with CAD/USD/TWD totals, company rankings, and sector allocation">

All values and ETF constituents in this preview are invented. ODS charts are embedded images; editing cells does not redraw them or write back to SQLite. Regenerate a report for consistent outputs.

</details>

## Languages

**English (`en-CA`)**, **Traditional Chinese (`zh-TW`)**, and **Simplified Chinese (`zh-CN`)** are supported. New installations default to English. Interface language is independent of the language of a saved report; changing settings for future reports does not rewrite previous editions. Dates use `America/Toronto`.

Canonical developer documentation is English. See [localization](docs/i18n-plan.md) for CLI settings, unchanged source names, and offline language editions.

## Data and privacy

Uploads go to **your own instance**. Its private volume holds the instance metadata, uploads, keys, portfolio ledgers, preserved source evidence, and reports. The application does not publish financial files to GitHub or send them to an AI service. Normal analysis jobs retrieve public reference data.

Login protects the application; **SQLite files and backups are not encrypted by this tool**. Protect the host and complete private volume. Use the [full private backup/restore commands](docs/web-backups.md) and keep a protected off-device copy; container replacement and same-disk database copies are not complete backups. [Security policy](SECURITY.md) · [Web operations](docs/web-operations.md).

The CLI also supports explicit private workspaces outside the source checkout. Financial directories and local settings are Git-ignored, with additional publication/image allowlists for contributors. Public examples and screenshots are synthetic. Do not attach real exports, databases, or reports to public issues. [Publication safeguards](docs/publishing.md).

## Project status

**Pre-release, with an implemented browser/API/worker workflow and a supported CLI.** CI exercises synthetic core/API/report tests, frontend builds and generated API types, unit/browser workflows, offline reports in three languages, and Docker install/metadata-upgrade/crash/restart/adoption/restore checks. See [the CI workflow](.github/workflows/ci.yml) and [acceptance matrix](docs/web-release-acceptance.md). Use the candidate version’s actual results; automated checks do not mean a personal instance has been deployed or migrated.

| Capability | Status |
|---|---|
| Browser login, independent portfolios, import previews/jobs, frozen analysis, registered report downloads | Implemented |
| CLI/Web contributions/coverage, BTC balances/events/revisions, report recovery | Implemented: [financial declarations](docs/web-financial-records.md) |
| Frozen CSV/JSON datasets, report ZIPs, full consistent backup/empty-instance restore | Implemented: [WEB-005 guide](docs/web-backups.md) |
| Copy-verified adoption of existing CLI workspaces | Implemented: [trusted-host adoption](docs/web-adoption.md) and opt-in [legacy report evidence](docs/web-legacy-reports.md); actual private migration is explicit |
| Extensible financial CSV sources | Two real built-ins; installable SDK/trusted registry, v1 nonbooking previews and default v2 CLI/browser approved reports implemented. Personal adoption and additional real formats remain: [SRC-004](TODO.md) |
| Operations acceptance | Verified: Linux/amd64 CI and Linux/arm64 Docker Desktop, with upgrade/capacity/interruption tests and [rollback/platform guidance](docs/web-release-acceptance.md). Deployment/adoption remains an explicit operator action. |
| Pull-only prebuilt images for Docker hosts | Planned: WEB-008, Linux/amd64 + Linux/arm64; current setup builds from source |
| Additional locales | Planned: I18N-007 |

Current imports support the documented Wealthsimple holdings and Bull Bitcoin order formats. The tool does not trade, log into broker/wallet accounts, independently verify on-chain ownership, or calculate tax ACB/CRA contribution room. [Roadmap and acceptance facts](TODO.md) · [Supported inputs and financial boundaries](docs/user-manual.md).

## Documentation

| Guide | Read it for… |
|---|---|
| [Report reading](docs/web-analysis-reports.md) · [Browser workflow](docs/web-frontend.md) · [Web operations](docs/web-operations.md) | Sign-in, uploads, analysis, exports, installation, HTTPS, and host commands. |
| [User manual](docs/user-manual.md) · [Examples](examples/README.md) | CLI/private workspaces, source setup, contributions, balances, and recovery. |
| [Exports and private backups](docs/web-backups.md) · [Operations acceptance](docs/web-release-acceptance.md) | Report ZIPs, CSV/JSON ranges, consistent backups, empty-instance restore, upgrades, rollback, resources and platform evidence. |
| [Reports](docs/report-spec.md) · [ODS](docs/workbook.md) | Interpretation, formulas, charts, evidence, and validation. |
| [Core API](docs/core-api.md) · [BTC reconciliation](docs/btc-reconciliation-plan.md) | Data contracts, stable references, unknown costs, and later explanations. |
| [Financial declarations](docs/web-financial-records.md) · [CLI adoption](docs/web-adoption.md) | Save contributions/BTC revisions and verify a retained-source migration. |
| [Source adapters](docs/source-adapters.md) · [Languages](docs/i18n-plan.md) | Extensibility contracts, planned plugin support, and localization. |
| [Contributing](CONTRIBUTING.md) · [Development](docs/development.md) · [Agent setup](docs/agent-development.md) | Reproducible development, checks, shared instructions, and private guidance. |

For help, [open an issue](https://github.com/gh-slee/wealth-ledger/issues) with a minimal **synthetic** reproduction. See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Development

Development setup and detailed maintenance procedures live in [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/development.md](docs/development.md). Application features remain deterministic code and run independently of development agents. Shared project instructions live in [AGENTS.md](AGENTS.md).

## License

Code and canonical documentation are [MIT licensed](LICENSE). Bundled fonts and dependencies retain their own licenses; downloaded official data retains its provider's rights. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Project artwork and screenshot provenance are documented in [assets/readme/README.md](assets/readme/README.md).
