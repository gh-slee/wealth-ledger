# README artwork and screenshots

| Asset | Provenance |
|---|---|
| `wealth-ledger-mark.svg` | Original project artwork under the project MIT license. |
| `report-preview.png` | The invented offline report from `examples/demo.py`. |
| `web-overview.png` | The disposable synthetic browser fixture, overview page. |
| `web-exposure.png` | The same fixture, sector classification and company rankings. |

These images contain no real user's accounts, balances, wallet addresses, prices,
or broker exports. Their dates and values are invented demonstration inputs, not
current market data. Only the three named PNG paths are allowlisted for publication;
arbitrary screenshots remain blocked. Inspect newly generated images before staging.

## Exported report preview

With the locked Python core dependencies installed, from the repository root:

```bash
python scripts/render_readme_preview.py
```

The renderer creates its own temporary synthetic demo, accepts no external portfolio
inputs, and performs no market/reference downloads. It does not read or modify real
financial state. Regenerate when the example/report design changes.

## Browser screenshots

Install Python Web test dependencies, Node 24 LTS, and the locked frontend packages.
From the repository root, using a Python 3.12+ environment:

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
`WEALTH_LEDGER_BROWSER_CHANNEL=chrome`; Playwright uses a disposable profile, not a
personal browser session. `PLAYWRIGHT_BROWSERS_PATH` can select a local browser cache.

The capture script starts `scripts/web_browser_fixture.py`, which creates a new
instance in a system temporary directory and seeds only the public synthetic demo.
It refuses an occupied fixture port, takes no URL/portfolio/source-file arguments,
checks the synthetic portfolio/value, and captures pages only after login. Fixture
services are terminated afterward. Browser/fixture provenance is saved under ignored
`work/readme-capture/provenance.json`; publication images contain only the page,
without desktop, address bar, credentials, or browser-profile content.

The report cutoff remains the demonstration date; the fixture's publication timestamp
reflects the capture run. Pixel output can vary with browser/platform/fonts. Capture
preserves reduced-motion settings and bundled fonts; check both images visually and
rerun the publication guard before staging. No existing personal instance, ledger,
latest pointer, source export, or report history is used.

## Badges

The CI badge comes from this repository's GitHub Actions workflow and reports the
status of `main`. Other badges are static Shields.io labels for the documented stack,
license, and pre-release status; they do not claim package downloads, popularity,
coverage, or a published image. Badge requests occur when documentation is rendered;
the application has no runtime dependency on those image services.
