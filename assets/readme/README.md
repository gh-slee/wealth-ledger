# README artwork and screenshots

| Asset | Provenance / captured task |
|---|---|
| `wealth-ledger-mark.svg` | Original project artwork under the project MIT license. |
| `report-preview.png` | The invented offline report from `examples/demo.py`. |
| `web-login.png` | Blank sign-in form; no entered credentials. |
| `web-overview.png` | Saved synthetic portfolio totals, source dates and account allocation. |
| `web-overview-dark.png` | The same synthetic overview with dark appearance selected. |
| `web-holdings.png` | Native CAD/USD securities and account filters. |
| `web-exposure.png` | Invented sector classifications and direct/ETF company rankings. |
| `web-history.png` | The fixture's single actual observation; no fabricated monthly points. |
| `web-bitcoin.png` | Invented BTC/LBTC quantities, costs and monthly purchase rates. |
| `web-imports.png` | Both public example CSVs selected locally, before upload/preview. |
| `web-records.png` | Unsaved invented BTC quantity, dated observation and synthetic evidence source. |
| `web-reports.png` | Saved report context, original downloads and grouped edition history. |
| `web-report-reader.png` | Scrolled saved report contents and original analysis tables. |
| `web-settings.png` | Default example settings; password-change fields remain blank. |

All Web screenshots come from `scripts/web_browser_fixture.py`, using public
`examples/demo.py` / `examples/data` inputs in a newly created temporary instance.
They contain no real user's accounts, balances, wallet addresses, prices, or broker
exports. Dates, values and company names are demonstration data, not current quotes.
The filled wallet form is not submitted and the selected CSVs are not uploaded or
confirmed by the screenshot script. The application UI is captured as rendered;
financial text, tables, warnings and charts are not replaced with a visual mockup.

Only these thirteen named PNG paths are allowlisted for publication; arbitrary
screenshots remain blocked. Inspect every newly generated image before staging.
The local capture receipt is evidence, not a substitute for visual privacy review.

## When to refresh screenshots

Refresh affected README screenshots and captions in the same change when a major
UI change makes the gallery inaccurate: page layouts, navigation, visible workflows,
charts, themes, or added/removed pages. Keep the gallery representative of the
current application. Backend-only changes and minor visual adjustments do not need
new captures unless they make an existing image or explanation misleading.

Use the isolated synthetic capture workflow below, never a personal instance or
real financial data. If page routes or states change, update the capture script
alongside the images. Review every regenerated PNG at full size, including light
and dark examples where affected; confirm mock data, blank credential fields and
accurate captions. Check README links and the explicit image publication allowlist,
then run the publication/privacy guards documented in
[the publishing guide](../../docs/publishing.md#local-review-before-publication).
Keep capture receipts private. A successful capture alone is not visual or privacy
approval, and image refreshes do not authorize deployment or financial data changes.

## Exported report preview

With the locked Python core dependencies installed, from the repository root:

```bash
python scripts/render_readme_preview.py
```

The renderer creates its own temporary synthetic demo, accepts no external portfolio
inputs, and performs no market/reference downloads. It does not read or modify real
financial state. Regenerate when the example/report design changes.

## Browser screenshots

Install Python Web test dependencies, Node 24 LTS (or 22.12+), and the locked frontend
packages. From the repository root, using a Python 3.12+ environment:

```bash
python -m pip install -r requirements-web-test.lock
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build
cd frontend
npx playwright install --only-shell chromium
cd ..
node frontend/scripts/capture-readme.mjs
```

Activate the Python environment first, or set `WEALTH_LEDGER_TEST_PYTHON` to its
executable. An already installed Chrome binary can be selected with
`WEALTH_LEDGER_BROWSER_CHANNEL=chrome`; Playwright uses a new disposable profile,
never a personal browser session. `PLAYWRIGHT_BROWSERS_PATH` can select a browser cache.

The capture script:

1. Refuses an occupied fixture port and takes no URL/portfolio/source-file arguments.
2. Starts a child fixture that creates a new instance in a system temporary directory.
3. Signs into the known synthetic portfolio and captures the blank sign-in screen after normal logout.
4. Checks the expected synthetic portfolio before each authenticated capture, fixes
   light/dark appearance and waits for the relevant data, charts and bundled fonts.
5. Selects only fixed public example CSV paths and fills only an unsaved invented
   wallet declaration. It performs no import or declaration confirmation.
6. Rejects entered password fields, unexpected origins, browser errors and external
   browser requests. Images show the page, not desktop/address-bar/profile contents.
7. Closes the browser and terminates the fixture afterward; its temporary data is removed.

The twelve Web images use a 1440x1200 viewport with reduced motion. The report-reader
image is a scrolled viewport; other images start at the page heading. Screenshots
show representative visible content, not every section of a long page. All existing
application locales and financial semantics remain unchanged.

Browser/fixture/file provenance is saved under ignored
`work/readme-capture/provenance.json`. The report cutoff stays the demonstration date;
the fixture's publication timestamp reflects the run. Pixel output can vary with
browser/platform/fonts. Verify all README image references, review each full-size PNG,
and rerun publication guards before staging. No existing personal instance, ledger,
latest pointer, source export, report history or Docker volume is used.

## Badges

The CI badge comes from this repository's GitHub Actions workflow and reports the
status of `main`. Other badges are static Shields.io labels for the documented stack,
license, and pre-release status; they do not claim package downloads, popularity,
coverage, or a published image. Badge requests occur when documentation is rendered;
the application has no runtime dependency on those image services.
