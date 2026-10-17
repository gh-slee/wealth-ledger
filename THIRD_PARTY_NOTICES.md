# Third-party data and licenses

Project-authored code and documentation use the [MIT License](LICENSE). It does not
replace the terms for bundled fonts, dependencies or data downloaded at runtime.

## Fonts

`assets/fonts/NotoSansTC-Regular.ttf` is a static Regular derivative of the Noto
Sans TC variable font, instantiated at weight 400. It comes from Google Fonts/the
Noto project under SIL Open Font License 1.1. Copyright notices, reserved font names
and the full terms remain in [assets/fonts/OFL.txt](assets/fonts/OFL.txt); the project
MIT license does not replace them. ODS and PDF use the same font; ODS also embeds
its OFL document.

`assets/fonts/NotoSansSC-Regular.ttf` is the unmodified Noto Sans SC Regular,
Version 2.004-H2. Adobe's 2014-2021 copyright and SIL Open Font License 1.1 terms
remain in [OFL-SC.txt](assets/fonts/OFL-SC.txt). Asset version and SHA-256 are in
[the provenance record](assets/fonts/NotoSansSC-provenance.json). zh-CN reports use
this font and embed its corresponding license in ODS. The project MIT license
does not replace the font license.

## Python dependencies

Runtime packages are listed in `requirements.lock`, including Matplotlib,
ReportLab, pypdf, Pillow, tzdata, certifi and their dependencies. They are installed
through the package manager. The optional API lock adds FastAPI, Starlette,
Pydantic/pydantic-core, pwdlib/argon2-cffi, Uvicorn, Huey (MIT) and their dependencies;
`requirements-web-test.lock` additionally pins HTTPX/httpcore for tests. No JWT,
telemetry exporter, runtime AI or frontend CDN is enabled. These packages retain
their upstream licenses; their code is not relicensed under this project's
MIT license. Consult each installed distribution's metadata, LICENSE and upstream
documentation for its actual version and terms.

## Official ETF, FX and market data

Normal runs download data from providers' public sources into each user's private
data directory, recording retrieval/effective times and hashes. Public availability
does not imply permission to redistribute complete downloads. This repository does
not distribute downloaded official holdings, pricing evidence or private analysis
reports, nor grant redistribution rights to those data.

`tests/fixtures/fund_sources/` contains independently authored, minimal synthetic
format fixtures, not republished official responses. Field names, fund identifiers
and parser-required names test compatibility; companies, weights and dates are
invented and do not represent actual or current fund holdings. Format reference
URLs are listed in [the fixture guide](tests/fixtures/fund_sources/README.md).

## Synthetic demonstrations

The CSVs, FX rates, BTC prices, orders and ETF constituents in `examples/` are
invented test data. They contain no real user records and must not be used for
investment or tax calculations. Synthetic reports verify installation, execution
and output generation only.

## Browser dependencies and fonts

`frontend/package-lock.json` pins React/React DOM, Vite, TypeScript, Tailwind,
Radix, TanStack Query/Table, ECharts, Decimal.js, Lucide and development tools.
They retain their upstream licenses; the project MIT license does not relicense
them. Node/npm are build/test tools, absent from the final Python runtime image.
The local Button composition follows shadcn/ui; its MIT notice is retained in
[the component notice](frontend/public/licenses/shadcn-ui.txt).

Browser font subsets are bundled by npm, never fetched from a CDN at runtime:
Atkinson Hyperlegible (regular/bold) and IBM Plex Sans Condensed (semibold), each
under SIL OFL 1.1. Full notices are in
[Atkinson](frontend/public/licenses/atkinson-hyperlegible.txt) and
[IBM Plex](frontend/public/licenses/ibm-plex-sans-condensed.txt), also copied into
built assets under `/licenses/`. System fonts provide CJK browser fallback;
report fonts remain the separately bundled Noto assets described above.
