# Portable ODS workbook

Each formal import produces `portfolio.ods`. Broker-only reports contain nine sheets:
overview, currency holdings, account holdings, portfolio analysis, chart analysis,
history, cash flows, position data, and FX/notes. Combined securities/BTC reports add
BTC tracking and BTC reconciliation, for eleven sheets. Display names are localized.

Raw holdings/frozen FX supply calculations. Portfolio/accounts show CAD/USD/TWD
equivalents; security cost/unrealized P&L stay in native currency. Currency/account
tables include native-security subtotals; cash is in the overview. DB account labels
distinguish separate accounts of the same type.

FX, account totals, security aggregation, weighted average cost, unrealized return,
concentration and weight matrices use cell formulas. History uses saved period
values, unaffected by editing current FX. SQLite remains the authoritative ledger;
manual workbook scenarios do not write back.

Eight chart categories cover account values, trading currencies, security rankings,
security/account distribution, native P&L, native return, instrument types and account
weight heatmaps. A second distinct-date observation enables historical values.
Embed same-run PNGs at original aspect ratios instead of hand-written native charts
with reader-dependent rendering. Native CAD/USD P&L use separate panels. Cell heatmaps
use conditional styles. Trading currency is not underlying ETF country/currency risk.

With only one observation, show the baseline without a fabricated growth curve.
Missing flows mean missing data, not no contributions. Preserve anomalous CAD cash
book values as quality findings; value cash by native market value and exclude it
from cost/P&L analysis.

The ODS packager writes OpenDocument 1.2 with Python's standard library; Matplotlib
creates PNGs. It requires no LibreOffice, Node, Codex cache or platform executable.
ODS readers are only needed to open/inspect/recalculate formulas. Every formula
includes a numeric cache calculated from the same inputs. PNGs live in `Pictures/`,
so the workbook is self-contained. P&L/return charts retain negative ranges.

Charts are static images without editable series or live redraw after cell edits.
`scripts/update.py` regenerates reports/charts from the ledger. Formulas/manual
scenarios remain available; original CSV/SQLite remain authoritative.

## Python interface

```python
from pathlib import Path
from wealth_ledger.workbook import build_workbook, verify_workbook

result = build_workbook(payload, Path("portfolio.ods"), chart_images=report_result["charts"])
checks = verify_workbook(Path("portfolio.ods"), payload["totals"]["total_cad"])
```

`report_result` comes from `reporting.generate_reports()`; `charts` maps names to PNG
paths. Without `chart_images`, Python regenerates charts from current data rather
than reusing stale files or blank placeholders. This API consumes report JSON;
it does not import CSV/write SQLite. Formal changes use the update CLI.

Export checks cover totals, instrument sums, ZIP packaging, formula caches, image/
manifest relationships, aspect/placement, parseable XML and byte-identical same-run
PNGs. Development uses official OASIS ODF 1.2 Relax NG schemas for sheets, styles,
settings and package manifests. Reader-specific display/recalculation still needs
acceptance in that reader. See [OASIS OpenDocument 1.2](https://docs.oasis-open.org/office/v1.2/os/OpenDocument-v1.2-os.html).

Editing current raw market value/FX supports scenarios. Market value and unrealized
P&L are source observations; editing quantity/price alone does not rewrite those two
source fields. A new CSV rebuilds complete holdings/analysis images.

ODS embeds the selected font/license, with Latin/Asian styles. Chart counts depend
on actual inputs/history, not a fixed personal report. Crypto adds BTC tracking and
two BTC charts; CRYPTO enters totals/instrument types but not native CAD/USD security
tables. Reader font support varies; rasterized PNG labels are unaffected.

## ETF company exposure supplements

Portfolio analysis retains security rankings/matrices and adds Top 20 companies:
rank 1-20, company, direct/ETF indirect CAD, total CAD/USD/TWD and three denominator
weights. Saved constituent coefficients/paths, fund coverage and official sources
remain visible. Company amounts reference position-data CAD formulas. The principal
denominator is noncash investments; the equity denominator uses resolved ETF company
weights/direct stocks. Use disclosed weights without automatic rescaling.

Sources/order are frozen. Workbook edits do not redownload official holdings or
redraw PNGs; run a formal update. Chart analysis adds `12_company_exposure` with
stacked direct/ETF weights. Image/font/cache/ODF checks continue; incomplete/unresolved
sources and frozen replay are explicit, never silently zero.

## Sector, country and region supplements

Portfolio analysis includes complete GICS, official country/market and region tables:
CAD/USD/TWD, weights against all noncash investments/resolved company equities,
saved classification coverage/effective-date range, root-position coverage and audit
coefficients. ODS keeps all countries; MD/PDF's Top 15 summary does not truncate it.

Classification coefficients multiply root position-data CAD values, aggregate by
dimension/category with `SUMIFS`, then convert to USD/TWD. Merge the same MIC/Symbol
across trading currencies before computing root coefficients to avoid duplicate
weights. Equity denominators include unclassified equities. Investment denominators
exclude account cash but retain BTC, ETF cash and unknowns. Non-company equity
weights are not applicable. Coefficients/dates/coverage are frozen inputs; amounts/
principal weights are formulas. Manual changes do not update saved coverage/order/images.

Charts add `13_sector_exposure`, `14_country_exposure`, `15_region_exposure`.
Actual formula/chart counts depend on history, policy and observations; consult the
manifest. Preserve tiny negative rounding adjustments and separate unclassified,
non-company net amounts and unknowns. `classification-detail.csv` traces original/
borrowed classifications; `allocation-exposure.csv` contains complete three-currency
allocations. Older saved analysis without classification gets no fabricated tables/charts.

## Backfilled BTC opening and unknown actual costs

Without observations, CRYPTO quantity/value includes fixed opening, completed Bull
purchases and known net events. Otherwise use the latest applicable balance plus
later events. If opening actual cost is unknown, position-data/portfolio actual
complete cost, average cost, P&L/rate remain unknown text without formulas. Explicit
`bull_average_proxy` adds separate proxy formulas in BTC tracking. `SUMIFS` ignoring
text must not create false zero cost. Values/weights/FX keep their formulas.

BTC tracking shows known Bull spend, raw BTC/LBTC deliveries, backfilled equivalent
opening, declared total/reference buys, declaration date, cutoff, source and SHA-256.
Original Bull opening assumptions go to `btc-opening-audit.json`, marked as excluding
the backfill, rather than the everyday main table. Monthly accumulation charts show
real purchases, not invented acquisition months. Opening revisions create a separate
comparison scope; one new-scope observation cannot create a history curve.

## BTC reconciliation sheet

Keep BTC tracking and other sheets. Quantities use eight-decimal `btc_quantity`;
remaining-gap formulas reference each row's reported/expected quantities. Unknown
expectations are text, not zero. First-recorded/latest recalculated results and event
sources/references are saved generation-time inputs, not editable ledger entries.

With observations, chart analysis embeds `16_btc_wallet_reconciliation`, matching
MD/PDF inputs. Without observations, create no chart or point. Zero holdings retain
crypto/account identity with non-applicable zero-denominator weights/rates. Unknown
wallet/opening actual costs must override position/analysis formulas; None must not
be cleaned into zero cost or fake profit.

## Monthly BTC average purchase price

BTC tracking adds column J, average CAD/BTC, using same-row CAD spend D / delivered
BTC equivalent G. `IF` produces n.a. for zero G. Keep raw BTC/LBTC/cumulative quantities;
show purchase price with two currency decimals. Workbook scenarios do not redraw
static charts or write SQLite.

With backfill, rows 32-39 show effective pre-Bull BTC+LBTC opening, unknown actual
cost/contributions and declaration date, rather than old zero assumptions. Original
assumptions/reasons remain in each `btc-opening-audit.json`. Without backfill, the
applicable original declaration remains visible. Known Bull spend cannot replace
unknown pre-CSV cost; unknown costs are never zero.

## Effective-state and missing-data presentation

With explicit `bull_average_proxy`, the main BTC table labels whole-holding estimated
cost/P&L/rate as Bull average estimates. C31=C18/C29 (no buys: n.a.); C9=C8*C31;
C15=C12-C9; C16=C15/C9 (non-positive estimated cost: n.a.). Without an average, show
not calculable/reason; with an average and zero holdings, estimated cost/P&L are zero.
B9/B15/B16 must label both estimation and method. Row 20 explains coverage of opening/
unexplained differences, not actual complete cost. Preserve monthly heading row 43,
data from row 44.

C18 stays known Bull purchase spend, separate from whole-holding estimates. The
opening table keeps actual cost/contributions not supplied. Without observations,
reconciliation shows not calculated/reason; known zero gaps remain numeric. Actual
unknown cost/average/P&L in position/analysis tables has no numeric value/formula.
`btc-cost-estimate.json` stores estimates without altering financial payload/flows/history.

Before latest publication, `report_checks` reads ODS and text reports against the
payload. Missing/inconsistent fields block latest. Formula-cache/three-currency
checks remain. This is Python, not office software or runtime LLM validation.

Row 21 uses `wallet_reports.quantity_basis_label` for reported baseline, subsequent
estimate, formal observation and later-event estimates. Use `wrapped_body` for long
labels. Row 24 separates event/fee coverage: supplied records only; never estimate
or deduct unknown fees. Rows 43/44 remain fixed. Three-format checks enforce these
labels/policies without creating balances or changing financial payloads.

Default `actual_only` produces no Bull proxy values/formulas. Actual known costs
remain available; unknowns retain reasons. The opt-in report-layer proxy and method
supplement cannot contaminate actual source costs. All formats share one policy.

## Localized sheets and fonts

Sheet names are localized displays, with stable English IDs. Locale controls names,
charts and notes; generated escaped mappings handle cross-sheet references. Display
language is not a financial category key. `meta.xml` stores report_locale; styles
store language/region, and validators discover locale. Numbers/OpenFormula are untranslated.

en-CA/zh-TW use Noto Sans TC; zh-CN uses Noto Sans SC with its separate license. PNG,
PDF and ODS share locale resources. Security/company names/custom text stay verbatim.
Use `scripts/render_report.py` for language-only editions without ledger changes;
see [the locale contract](i18n-plan.md).
