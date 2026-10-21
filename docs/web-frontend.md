# Browser workflow

The optional React application reads registered, frozen report payloads through the
same-origin FastAPI API. It never imports a ledger, fetches market quotes or
regenerates reports just because a page is opened. Node is a build/test dependency;
the production image serves static assets from Python and runs a separate Python
worker. There is no runtime LLM, browser broker login or frontend CDN.

## Run it

Docker builds the frontend automatically. Follow [Web operations](web-operations.md)
to prepare the audited image context, initialize a new dedicated instance and run
the API plus worker. Open the configured origin, normally `http://localhost:8000/`.
Do not mount a previous CLI workspace as the new Web instance; adoption remains a
separate, [copy-verified trusted-host procedure](web-adoption.md).

For native development, install Python Web dependencies and Node 24 LTS (or Node
22.12+), then from the repository root:

```bash
python -m pip install -r requirements-web-test.lock
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" init-owner
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" serve
# In another terminal, with the same dedicated instance:
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" worker
```

Use a new, empty dedicated directory for first initialization. An existing initialized
instance uses its original credentials; do not repeat initialization to reset it.
Without `frontend/dist/index.html`, the API still runs but has no browser shell.
Rebuild after frontend changes. For Vite hot reload, run `npm --prefix frontend run dev`;
keep the backend on port 8000 but configure its public origin as
`http://localhost:5173`, matching the browser. Vite preserves Host/Origin when proxying
`/api`; do not enable permissive CORS or disable the API's origin checks.

## Daily use

1. Sign in with the owner initialized on the host. Create or select an independent
   portfolio. New portfolios default to English and actual known BTC costs.
2. Open **Import & jobs**. Supply either Wealthsimple holdings CSV, Bull orders CSV,
   both, or an optional BTC quantity with an explicit observation timestamp and UTC
   offset. The BTC field means BTC units, never CAD/USD market value.
3. Parser mode is enabled by default. Select a saved source context explicitly or
   enter required alias/timezone values. Optionally supply verified FX/BTC-price JSON;
   public reference fetching requires an explicit checkbox. Missing opening quantity
   remains unknown; a first Bull CSV does not imply a zero opening. Native compatibility
   mode retains its explicit opening JSON requirement.
4. Upload and preview. Review identified sources, source dates, checks and blockers.
   The preview is offline: reference checks can remain pending. Nothing enters the
   financial ledger until **Confirm import & generate reports** and its dialog.
5. Leave the worker running. Queued/running/committed/published states distinguish
   data commit from report publication. Resolve blocked inputs with a new preview.
   A failed report can resume its saved operation; uncertain states require trusted
   local review. Never reimport to guess whether a previous commit happened.
6. For contributions, coverage, BTC openings/events or corrections, use [Financial records](web-financial-records.md). Preview, confirm and save data first; prepare a separate report when ready.
7. Select a report edition for analysis. Change CAD/USD/TWD presentation or
   interface language without changing the saved observation. Download original
   ODS, Markdown, PDF and evidence attachments from **Analysis reports**.

Changing future report language/cost policy in **Settings** does not rewrite old
reports. Interface language is independent of the saved report language. Downloads
remain in their original published language. Markdown refers to its chart files:
download those attachments too, or choose **Download report ZIP** to preserve relative links. **Export report data** offers CSV/JSON holdings, accounts, history, cash flows and monthly BTC data, with supported inclusive date ranges. See [exports and private backups](web-backups.md).

## Parser-based upload mode

In **Import & jobs**, **Use parser plugins** is enabled by default.
The regular form accepts either/both CSVs, a dated BTC total, or saved facts. Fill
stable per-file aliases when needed; review/edit every account destination and
choose **Preview reviewed mappings** before exact confirmation. Missing references
remain pending unless supplied or explicitly fetched. This mode does not require a
native Bull opening JSON and never invents a zero opening. Uncheck parser mode only for the retained native compatibility path; it cannot
render canonical facts. Choose a saved context per CSV to reuse verified confirmed
settings. The advanced correction field accepts explicit revision/scope parent JSON. See [the shared entry contract](source-projections.md#automatic-import-entry-src-004c3c2b)
for dates, references, supported overrides and remaining cutover boundaries.

## Analysis semantics

- The evidence rail distinguishes valuation cutoff, holdings snapshot, latest
  completed order and optional wallet observation. An order date is not a wallet
  confirmation. Carried/mixed/missing sources and partial scope remain visible.
- Charts use only actual saved observations. Missing months are not interpolated
  observations. Value growth includes contributions/withdrawals and is not a return.
- Money and quantities stay decimal strings; Decimal is used for formatting and
  sorting. Only chart coordinates use JavaScript numbers. Unknown is an em dash,
  distinct from zero. Exact data is available in tables/downloads.
- Holdings can be filtered by account and native CAD/USD currency. The CAD-valued
  BTC proxy is excluded from the native security table and shown separately.
- The company table ranks 1–20 using whole-portfolio weights, including cash.
  Sector/country/region views use the frozen official classifications and show
  effective dates and coverage; unresolved portions remain visible.
- Bull funding is unclassified funding until its origin is supplied. Purchase spend
  is not a second contribution. Cash-flow coverage/BTC event forms share the CLI validators; [their manual](web-financial-records.md) explains saved-data report generation. [Verified CLI adoption](web-adoption.md) is a separate host operation.

## Sessions and privacy

The browser keeps financial queries and CSRF tokens only in memory. The only persisted
browser preference is the nonfinancial appearance enum; see [report reading and
themes](web-analysis-reports.md). Logout,
password changes, authentication expiry and portfolio switches clear/cancel queries;
query keys include portfolio, report and locale. There is no persisted query cache,
service worker or localStorage finance data. Session cookies are HTTP-only; HTTPS
is required away from loopback. Background polling never renews idle sessions;
only deliberate interactions do. A password change revokes every session.

Only public built assets are served anonymously. Financial APIs/downloads require
owner authentication and portfolio scoping. Published data JSON must match its
registered size/hash. Static routes reject private files, source maps and symlinks;
API paths never fall back to the SPA. ECharts uses SVG and rich-text tooltips rather
than source-controlled HTML. Source/user strings render as escaped React text.
No frontend asset bundle contains portfolio data or secrets.

## Validation and API types

```bash
npm --prefix frontend run format:check
npm --prefix frontend run check:source
npm --prefix frontend test
npm --prefix frontend run build
python scripts/export_web_schema.py --output work/web-schema.json
frontend/node_modules/.bin/openapi-typescript work/web-schema.json -o work/web-schema.d.ts
# Compare work/web-schema.d.ts with frontend/src/lib/schema.d.ts.
cd frontend
npx playwright install chromium
npm run test:e2e
```

The browser fixture creates a new temporary instance outside the checkout, seeds
invented reports and starts an isolated API/worker. It never reads real financial
state. `WEALTH_LEDGER_TEST_PYTHON` can select an installed Python environment;
`WEALTH_LEDGER_BROWSER_CHANNEL=chrome` can use a separately installed Chrome binary
with a disposable profile. Neither is a production dependency. Test outputs stay
under ignored `frontend/test-results/`. CI also installs Chromium system dependencies.

Tests cover exact decimal/null handling, locale parity, frozen API reads, hashes,
portfolio authorization, static boundaries, browser charts, locale/currency changes,
mobile layout, accessibility, downloads, cache isolation and actual worker imports.
Broader platform/release testing remains WEB-007; native and Docker acceptance are
bounded evidence rather than a claim of universal deployment compatibility.

## Stack references

[React](https://react.dev/), [Vite](https://vite.dev/guide/),
[TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview),
[TanStack Table](https://tanstack.com/table/v8/docs/introduction),
[shadcn/ui](https://ui.shadcn.com/docs/installation/manual), and
[ECharts accessibility](https://echarts.apache.org/handbook/en/best-practices/aria/).
The lockfile pins actual versions. Font and component licenses are retained in
`frontend/public/licenses/` and the production image; see
[third-party notices](../THIRD_PARTY_NOTICES.md).

## Legacy publication evidence

Explicitly adopted pre-checksum reports show a migration verification notice in
analysis and the report library, localized in all three UI languages. Their historical
report-generation time remains the published-time display; migration time is separate.
The notice does not claim original publication checksums or historical authenticity.
Legacy ZIP downloads preserve all original bytes and add a separate verification
attachment. See [legacy report adoption](web-legacy-reports.md).

## Frozen source report views

Source-report API jobs now publish into the same selected-report library and
artifact/ZIP routes. The normal upload form uses the shared default parser preparation;
advanced clients may also use [the explicit-context API](web-imports.md#opt-in-source-report-publication-src-004c3c2a).
Import & jobs displays their mappings/observed subtotals, hides confirmation for
`mapping_required`, and sends the exact digest when confirming a prepared source
report. Automatic contexts, editable mappings and explicit saved-context reuse are implemented.

The read DTO adds optional `source_basis` (model, saved valuation ID/revision,
comparable scope ID and unknown full contributions/returns). Holdings retain
provider, original source/revision/observation IDs and observation dates. History
contains actual same-scope dates/revisions only. Source dates distinguish holdings,
latest recorded purchases and actual wallet observations; the report cutoff is
not substituted for a source balance date. Generic provider IDs remain their own
labels. The overview explicitly labels valued observed rows as partial scope.

BTC views retain unknown quantities/costs/actual full gains and separate opt-in
proxy estimates. Monthly purchase spend/rates are not contributions; complete
contribution and cumulative wallet quantities are null when unproven. Canonical
cash-flow records keep direction/classification and only original CAD or explicit
historical CAD values; they are not converted using today's report FX.

CSV/JSON exports include `source_basis` and preserve decimal strings/blank unknowns.
ZIPs and ODS/Markdown/PDF downloads remain the original checksummed artifacts.
Viewing/changing interface language/exporting never imports or reprices data.
Browser acceptance uses a separate invented source portfolio, including generic
provider labels, Traditional Chinese scope text and original ODS downloads.

## Full report reading and themes

[Analysis reports](web-analysis-reports.md) reads verified saved Markdown sections and
registered charts alongside same-edition PDF/ODS/Markdown/ZIP downloads. Its history
groups editions by valuation instant and scope, with earlier editions expandable.
Controls support three locales and system/light/dark appearance; original documents
and files retain their publication language and styling.
