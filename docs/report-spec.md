# Investment report specification

This defines the supported report contract. A new clone contains no financial data;
each user establishes a baseline from their own inputs. Python writes ODS directly,
without local LibreOffice or LLMs. Reports support en-CA/zh-TW/zh-CN, CAD/USD/TWD
equivalents and America/Toronto time.

## Formats and consistency

- `portfolio.ods`: filterable holdings, account summaries, charts, history and flows.
- `report.md`: selected-language analysis/tables with relative PNG links.
- `report.pdf`: fixed-layout equivalent, validated for fonts/charts/pagination.
- `charts/`: independently usable PNGs.

All formats share calculated inputs. Save bundles under
`reports/YYYY-MM-DD_HHMM/rNN/`; revisions never overwrite older editions. Raw sources,
DB and outputs stay in the project; private financial data stays out of Git.

## Main contents

| Section | Measures/details |
|---|---|
| Overview | Portfolio/accounts in CAD/USD/TWD, native CAD/USD values, cash, snapshot/report times |
| Currency holdings | Separate CAD/USD securities, exchange, quantity, price, native book/value/P&L and allocation |
| Account holdings | TFSA/RRSP/Non-registered details and currency subtotals; additional accounts supported |
| Concentration | Largest/top-three/top-five securities, direct-stock/ETF summaries; an ETF is not one underlying company |
| Sector/country/region | GICS, official country/market, regions, direct/ETF equities, coverage/dates and non-company/unclassified reconciliation |
| Instrument types | Direct stocks/ETFs/cash; wrapper classification, not underlying asset allocation |
| Counts | Distinct securities, account-position rows and cash rows separately |
| Cash | Reported CAD/USD cash per account and weights; not presumed immediately withdrawable |
| Cost/P&L | Native aggregate book/value/P&L, weighted average cost and return across accounts |
| Account/security matrix | CAD-equivalent values and within-account weights; cash separate |
| Summary | Deterministic verified holdings/concentration/cash/history observations, without trading advice |
| Data checks | Account completeness, source dates, arithmetic, currencies, duplicates, FX and anomalies |
| Methods | Definitions, denominators, currencies, dates, provenance and missing analysis prerequisites |

## Three-currency valuation

Let C/U be native CAD/USD market values including reported cash; r is CAD per USD,
s is TWD per USD:

```text
Total CAD = C + U * r
Total USD = C / r + U
Total TWD = (C / r + U) * s
CAD to TWD = s / r
```

These are alternative equivalents of the same assets. Apply the same policy per
account and sum unrounded values. Preserve both FX dates/sources; publication/market
close times can differ. References are [Bank of Canada daily FX](https://www.bankofcanada.ca/rates/exchange/daily-exchange-rates/)
and [Taiwan central bank TWD/USD closing rates](https://www.cbc.gov.tw/tw/lp-645-1.html).
Holidays may use the latest preceding published date with disclosure. Missing FX
must not be guessed. Freeze each period's rates rather than revaluing history.

## Cost, P&L and weights

```text
Average cost = Native book value / Quantity
Unrealized P&L = Native market value - Native book value
Unrealized return = Unrealized P&L / Native book value
Account weight = Position CAD equivalent / Account total CAD equivalent
Portfolio weight = Position CAD equivalent / Portfolio total CAD equivalent
Cash ratio = Cash CAD equivalent / Portfolio total CAD equivalent
```

- Identify securities by MIC, Symbol and native currency. Aggregate presentation
  across accounts without merging underlying records.
- Weighted average cost is total native book / total quantity; return is total
  P&L / total cost, never an average of percentages.
- Exclude cash from security costs/P&L. Avoid zero division; label non-positive
  costs and special calculation scopes.
- Unrealized return is current holdings versus book cost, not annualized or a
  tracking-period total return.
- Wealthsimple book values are neither cumulative contributions nor verified tax
  ACB. Retain CAD book values but never derive current FX from CAD/native book ratios.
- Portfolio weights include reported cash. Securities-only concentration needs an
  explicitly separate denominator.
- Value cash by native quantity/Market Value. Preserve anomalous source CAD cash
  book values and identify discrepancies without rewriting them.

## Charts

A first complete snapshot supports eight categories:

1. Account CAD-equivalent values.
2. CAD/USD trading-currency allocation.
3. Aggregated security value rankings.
4. Security values stacked by account.
5. Native unrealized P&L in separate CAD/USD panels.
6. Native unrealized return, excluding cash.
7. Direct-stock/ETF/cash instrument allocation.
8. Security/account weight heatmap using full account denominators.

Trading currency is not underlying currency exposure. Instrument type is not actual
sector/region exposure. Preserve precision for tiny cash weights. Embed same-run
PNGs with original aspect ratios/fonts in ODS. Updates regenerate images; workbook
formula edits do not redraw them or expose editable chart series.

## Later snapshots and flows

The first CSV establishes a baseline; comparisons require actual later snapshots.
Distinguish formal monthly and temporary updates. Daily/monthly charts use real
observations; connecting dates does not fabricate daily data. Add comparisons to
the previous snapshot, previous formal month and baseline; separate CAD/USD/TWD
history for portfolio/accounts; new/disappearing/changed quantities, values, native
prices, weights and percentage-point changes; cash/account-allocation history; and,
only with complete external flows, opening/closing values, net flows and investment gain.

```text
Investment gain = Ending value - Beginning value - Deposits + Withdrawals
```

A disappearing position requires a complete account snapshot. Missing accounts are
not zeroed or silently carried to manufacture completeness. Quantity changes can
include splits/reinvestment, not necessarily trades.

Flows save date, account, type, native amount, CAD equivalent, source, transfer pair
and coverage. Coverage distinguishes not supplied, partial, confirmed complete and
confirmed no external flows. Transfers are inflow/outflow per account and cancel at
the portfolio boundary. Internal trades/FX/retained dividends are not external
contributions. Missing flow data is not zero.

Compute CAD gain/Modified Dietz/XIRR only when prerequisites are met. USD/TWD value
conversions do not inherit CAD returns; currency-specific returns require opening,
closing and each flow converted on their own dates.

## Analysis requiring additional inputs

| Analysis | Required evidence |
|---|---|
| Dividends/income/fees/realized P&L | Dated, currency-specific trades/income/fees or source reports |
| Target-allocation gaps | Explicit user targets; never invented target weights/trade amounts |
| Benchmarks/volatility/drawdown | Sufficient compatible returns/flows and benchmark policies |

A holdings CSV cannot supply these automatically. Fetch ETF constituents separately
through official adapters. Classification is implemented below; missing/conflicting
labels stay unknown. Summarize availability and omit empty chart placeholders.
See [ETF Facts guidance](https://www.getsmarteraboutmoney.ca/tool-embeds/etf-facts/)
and [Wealthsimple custom activity/realized reports](https://help.wealthsimple.com/hc/en-ca/articles/35654428540571-Request-a-custom-statement);
actual columns/coverage still require validation.

## Initial acceptance

- Original CSV copies match; quantities/prices/value/native P&L reconcile.
- Reimports deduplicate; corrected same-time inputs create revisions.
- Currency/account totals and cash inclusion reconcile across all formats.
- Validate ODS against official schemas, independently evaluate caches/formulas,
  and match embedded PNG bytes/aspect/placement. Check PDF selected-language text,
  pagination/clipping and Markdown images. Reader-specific behavior needs reader acceptance.
- Synthetic later-snapshot/missing-account/revision/zero-cost/transfer tests never
  write formal personal history.

## Combined Bull Bitcoin reports

Use a separate order ledger/combined observations without rewriting the original
Wealthsimple baseline. Present BTC/LBTC 1:1 equivalents while retaining networks.
Without observations, quantity is fixed opening + completed buys + known net events;
otherwise use the latest applicable reported balance + later events. Do not guess
fees, claim independent verification or erase older gaps. Separate CAD purchase cost,
reference valuation and price changes. BTC valued in CAD is neither native security
nor CAD cash.

Explicit Bull average proxy: completed Bull CAD spend / delivered BTC+LBTC; estimated
whole-holding cost = current quantity * average; estimated P&L = value - estimated
cost; rate = P&L / estimated cost. Apply to all quantity including opening/unexplained
differences without clearing reconciliation status. A quantity-only update leaves the
average unchanged; completed buys may change it. Zero-holding rates are n.a.; no buys
means no average.

Quantity labels distinguish a matching same-time user baseline, later opening/purchase
estimate, formal balance and later-event estimate. Formats share the same classifier.
Event/fee coverage is independent: missing fees do not invalidate a reported baseline
or justify extra deductions. An opening declaration does not create another observation.

Label every proxy estimate consistently and save `btc-cost-estimate.json` with date,
method/results. Estimates cannot fill unknown actual costs, historical contributions,
realized/period/portfolio actual P&L. Preserve original declarations/payloads. Opening
cost is not zero-cost profit, and fixed purchase spend is not remaining cost at every balance.

Add BTC tracking, cumulative purchases and monthly Funding/spend charts. Funding/Buy
are the same money, not two contributions. Freeze price/candle/FX evidence without
backfilling old months with today's price. Show mixed source times/missing formal
months and compare actual irregular dates. Combined XIRR/Dietz remain disabled until
external-flow classification/reconciliation is complete. Security rankings remain
wrapper rankings; company look-through is separate below.

### Partial-source history

Either source can refresh the overview. Show updated/carried/not-supplied status and
original holdings/event dates. Missing files do not prove no trades. Bull-only uses
execution-time valuation while stocks retain snapshot prices; mixed-date totals are
estimates. Bull-only initial scope is explicit.

History retains real stock snapshot dates; totals with carried sources use dashed
lines/hollow points. Each valuation freezes FX/BTC prices. Do not fill days/months
or label estimated value changes as investment gain.

## ETF company look-through (implemented)

All formats show Top 20 with rank 1-20, direct/ETF indirect CAD, totals and three
denominator weights; ODS also shows USD/TWD. Main denominator is all noncash investments,
including BTC. Add `12_company_exposure` and full company/unresolved CSVs.

Normal updates query latest published official data and disclose issuer-effective
dates. Unsupported/failed/partial data stays unresolved; no third-party substitution.
Save raw evidence, SHA-256, fetch time, parser version and company-alias fingerprint.
Analysis revisions do not create valuation observations. `--lookthrough-run-id`
replays same-valuation frozen analysis explicitly offline.

Futures/swaps are not resolved to notional/delta exposures; their net values remain
unresolved, separate from equities. Reconcile undisclosed weight and rounding
separately. Rankings estimate disclosed company equities and may change with missing
coverage. See [manual section 15](user-manual.md#15-etf-company-look-through).

## Sector, country and regions (implemented)

Reuse same-run company components/official holdings for GICS, official country/market
and country-derived regions. Accept explicit `gicsSectorDescription`; retain ICB/raw
issuer labels without guessed taxonomy conversion. Prefer each row's own official
classification; fill gaps from reliable same-company latest classifications within
the run, leaving equal-date conflicts unclassified. Never infer direct-stock country
from MIC/currency/ISIN. Regions are not developed/emerging status; country is not
revenue geography. See [manual section 17](user-manual.md#17-sector-country-and-region-exposure).

Main denominator is all noncash investments including BTC; also show resolved-equity
weights. Classification coverage uses resolved company equities, without treating
unknown instruments as covered. Separately show classified investment weight and
effective-date ranges. BTC, ETF net cash, bonds, unresolved and rounding adjustments
remain separate. Decimal reconciles every dimension to the same total; no forced
rescaling of negative adjustments.

ODS/CSV include full categories, CAD/USD/TWD and both weights. MD/PDF show CAD, Top 15
countries plus other classified countries, and full unclassified/non-company rows.
Charts: `13_sector_exposure`, `14_country_exposure`, `15_region_exposure`; gray means
unclassified/non-company. Retain tiny negative adjustments. Export root coverage,
`allocation-exposure.csv` and company/path/classification-method/evidence details in
`classification-detail.csv`. Freeze evidence/payloads and record version/coverage/
dates/files in manifests. No DB migration, holdings/valuation/flow/history changes
or invented classifications for older analysis; replay preserves saved results.

## Backfilled pre-Bull opening

After explicit total-wallet BTC+LBTC/scope attribution, save a separate declaration
of total minus referenced completed Bull buys as a fixed opening. Include quantity/
three-currency value, leaving actual acquisition cost/contributions unknown. Actual
complete average/P&L/rate remain unavailable; opt-in proxy estimates are separate
from known Bull spend. Added-scope value is not a contribution or investment gain.

Show buys/opening/total/date/reference-cutoff/source across formats. Preserve original
zero-opening evidence in raw files/`btc-opening-audit.json`, not the current main
table. Monthly charts retain actual buys without fake opening trades. Opening
revisions create new scope baselines while retaining older valuations/sources/reports;
never invent pre-tracking values. Later CSVs deduplicate/accumulate buys without
recomputing the opening. Quantity agreement does not verify fees/network distribution.

## BTC balance/event reconciliation

All formats include one shared reconciliation section. Without observations, state
ledger estimation; an old opening is not a new observation. Rows contain stable
balance ID, UTC observation time, revision, reported/interval expected quantity,
remaining gap, first-recorded results and actual event IDs. Show full-ledger expected
quantity/anchor difference separately and retain older unresolved observations.

Pre-observation known fees change reconciliation only; later fees change subsequent
estimates. ID links do not duplicate economic effects. Separate user declaration from
independent verification; arithmetic agreement is not verification. Unexplained gaps
are not gains/contributions. Unknown actual costs/disposal allocation do not imply
zero actual P&L; an explicit proxy uses applicable quantity.

With observations add `16_btc_wallet_reconciliation`, comparing actual cumulative
Bull buys, observed points and post-anchor estimates without invented months. Export
`btc-reconciliation.csv`/`btc-events.csv`; retain complete DB/source revisions. Text is
deterministic, shared across formats. Normal updates fetch official ETFs; explicit
same-valuation replay records frozen status in manifests.

## Monthly BTC average purchase price

The cumulative/monthly table adds CAD/BTC = completed monthly Bull CAD spend /
delivered BTC+LBTC. This is quantity-weighted, not a simple order-rate average. No
buys means n.a.; Funding, opening, observations and later fees are excluded. Formats
show two currency decimals; data.json retains Decimal results. Unknown complete
holding cost does not prevent known monthly Bull purchase-rate reporting.

With backfill, show effective pre-Bull opening/equivalent quantity and independently
unknown actual cost/contributions/network distribution. Original zero assumptions
stay in the audit attachment; without backfill, show the applicable declaration.
Bull CSVs establish known spend, not earlier acquisition cost/external contributions.
Proxy opening estimates are labeled and never overwrite actual fields.

## Presentation state and publication checks

Separate known purchase spend, unknown actual opening cost, unavailable complete
actual P&L and available proxy estimates. Opening quantity cannot establish CAD
cost/contributions/network. Without observations show not calculated/reason; zero
gaps remain numeric. Historical evidence stays traceable; everyday reports show
effective current state.

Before publishing, the shared `publishing.publish` service (called by
`scripts/update.py` through `ApplicationService`) runs
`report_checks.validate_report_presentation` to read MD/PDF text/ODS cells against
the payload: effective opening/total, known Bull spend, nonnumeric unknown actual
cost/P&L, proxy values/formulas/supplements, quantity/fee labels, reconciliation
availability and audit evidence. Superseded-assumption leakage/inconsistency raises
ValueError and leaves latest unchanged. `manifest.presentation_validation` records
checks/policy; it cannot prove complete trades or independent wallet verification.

## Default and optional BTC cost policies

`actual_only` is default: show known actual costs and reasons for missing complete
costs, without applying later Bull averages to earlier costs. Explicit
`[reporting] btc_cost_policy` or `--btc-cost-policy bull_average_proxy` adds whole-holding
estimates. Reports/method supplements record policy; proxy never changes actual
book/avg_cost/unrealized, flows or period performance. Formats/checks share one policy.

## Languages and versions

Formats/charts share static catalogs, financial payload and precision. New projects
default to English; legacy projects preserve Traditional Chinese. Locale does not
change timezone/currency/valuation/cost policy. Source/machine exports retain schemas
and verbatim text; unknown and valid zero remain distinct.

Manifests record locale/catalog SHA, format/render versions, fonts/SHA, data checksum
and financial fingerprint. Offline editions preserve data.json, mark frozen analysis,
record render time and never update quotes/ledger/latest. Legacy checksum gaps are
metadata-consistency limitations. See [i18n contract](i18n-plan.md).

## Frozen Web exports

Registered editions can be downloaded as complete ZIP bundles preserving relative
chart links, or projected CSV/JSON datasets. Inclusive date filters apply only to
dated rows/months already present in the selected report. These are not all-ledger
revision exports or full instance backups. Unknowns, source dates and precision
remain explicit; CSV escapes spreadsheet formula text. See [exports and private
backups](web-backups.md) for scope, limits, API routes and restoration.


## Source-neutral core report model

The C3B developer API produces `source-neutral-1` editions with a shared localized
document for ODS/Markdown/PDF. It shows CAD/USD/TWD valued observed subtotals, native
CAD/USD holdings, original account scopes, security ranks/matrices, effective BTC
quantity and optional proxy, monthly purchase rates, reconciliation, frozen history,
recorded flows and dated coverage/quote evidence. Eight base charts and applicable
BTC/history/company/sector/country/region charts use deterministic code. Unknown
values remain unknown, and partial scope cannot establish full wealth or returns.

Existing official ETF fetching/replay remains a separate explicit analysis operation;
rendering never refreshes sources. Source observations, derived valuation editions
and published Web reports are different records. C3B adds no normal CLI/HTTP
publication route and does not remove the report gate. See [source report semantics](source-projections.md#source-report-payloads-and-frozen-valuations-src-004c3b)
and [workbook limitations](workbook.md#source-neutral-report-editions).


## Frozen source publication operations

C3C1's opt-in source-report workflow atomically freezes verified source facts, the
derived valuation and effective-date/coverage-aware ETF analysis before publishing
ODS/Markdown/PDF and audit exports. Report-only retry reads that payload; it never
refreshes prices, FX, constituents or original CSVs. Publication manifests carry
`report_model` and `source_valuation_id` alongside the operation/approval binding.
Old derived editions retain their bytes, and already published retries cannot move
a newer latest pointer backwards. Source financial payloads omit developer-stage
publication flags; actual state belongs to durable operation/manifest records.
See [approval and recovery](source-projections.md#frozen-source-report-publication-src-004c3c1).
The advanced core alone does not register Web reports; the default CLI/browser
workflow now connects it to approved publication and Web registration.
