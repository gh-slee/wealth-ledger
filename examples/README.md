# Synthetic examples and offline demo

This directory contains invented data that can be shared and tested publicly.
CSVs, account IDs, orders, prices, FX and ETF constituents are not financial records.

## Files

| File | Purpose |
|---|---|
| `data/wealthsimple-holdings.csv` | Simulated CAD/USD securities and cash in TFSA, RRSP and Non-registered accounts |
| `data/bull-orders.csv` | One CAD Funding and completed BTC/LBTC purchases, without real wallet addresses |
| `data/fx.json` | Invented CAD/USD/TWD FX matching the demo valuation date |
| `data/btc-price.json` | Invented completed one-minute BTC-USD candle at the cutoff, not official pricing |
| `templates/cash_flows.csv` | Empty contribution/transfer field template |
| `templates/btc_events.csv` | Empty BTC fee/income/outflow event field template |
| `../config/bull-opening.example.json` | Explicit invented Bull zero-opening declaration; adapt it to your own history before using real CSVs |

## Generate ODS, Markdown and PDF

Install the locked dependencies as described in the main README. From the repository root:

```bash
python examples/demo.py --output work/demo
```

Outputs include `portfolio.ods`, `report.md`, `report.pdf`, PNG charts, CSV analysis
supplements and `demo-manifest.json`. ODS/PDF use bundled fonts and require no
LibreOffice, LLM or other local application. Markdown chart links are relative;
keep the output directory together when sharing it.

The demo creates an isolated SQLite database in a system temporary directory and
removes it on exit; only synthetic reports are copied to the chosen output. It
never reads the real DB, `config/local.toml` or existing reports, queries the network
or modifies `reports/latest.json`. An existing output directory is rejected; choose
a new path rather than overwriting it.

Code supplies invented ETF companies/allocations, marked `synthetic_demo` in saved
evidence. These are not official holdings. This is separate from the public-data
workflow in `scripts/update.py` and cannot verify that issuer websites remain reachable.

## BTC cost policy

New ledgers default to `actual_only`: a later Bull average is not automatically
applied to an opening quantity with unknown cost. Known Bull purchase spend is shown.

To exercise the optional whole-quantity Bull average proxy:

```bash
python examples/demo.py --output work/demo-proxy --btc-cost-policy bull_average_proxy
```

This affects report estimates, not actual recorded costs. See the
[user manual](../docs/user-manual.md) for production CLI and local configuration.

## Use your own data

Keep demonstrations separate from real ledgers. Do not import demo CSVs into your
daily ledger and then replace them with real data: history is append-only. First
Bull import requires an explicit opening declaration; missing history does not
justify inventing a zero opening.

Templates contain field names only. Store filled personal versions in `data/` or a
private input directory and never commit them back to `examples/`. The manual covers
normal updates, balance observations and contributions.

## Report languages

The demo defaults to English (`en-CA`). Select `--locale zh-TW` or `--locale zh-CN`
with a new output path for each run:

```bash
python examples/demo.py --output work/demo-tc --locale zh-TW
python examples/demo.py --output work/demo-sc --locale zh-CN
```

Each run uses an isolated synthetic ledger, bundled fonts and offline references.
Source names and machine exports remain unchanged. Saved demo data/manifest also
support an offline alternate-language edition through `scripts/render_report.py`;
the results remain synthetic demonstrations.

## Independent parser package

See [parser-plugin](parser-plugin/README.md) and [the SDK guide](../docs/parser-sdk.md)
for trusted versioned parser authoring and isolated nonbooking acceptance.
