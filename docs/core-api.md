# Core API and data rules

Use [project guidance](../AGENTS.md) and the task-relevant
[development procedures](development.md). [TODO](../TODO.md) distinguishes future
work. Interfaces below are implemented unless explicitly marked otherwise.

The ledger core uses Python's standard library and Decimal precision 60. Payload
amounts, quantities and ratios serialize as strings; ratios are fractional values.
Undefined ratios are null, not zero.

## Optional Web boundary

The optional `wealth_ledger.web` package requires `requirements-web.lock`. Its
`api.create_app(settings)` uses explicit `WebSettings`, a trusted-host initialized
`storage.Store`, versioned `admin/app.sqlite3` and server-owned portfolio IDs.
Authentication is an opaque server-side session, not a financial DB identity or JWT.
No data root defaults to the legacy CLI workspace. Full endpoint/security/operation
contracts are in [Web operations](web-operations.md). Financial CSV/optional dated BTC inputs use the implemented
[upload/job API](web-imports.md): preview and confirmation precede isolated execution.
Artifact registration remains a trusted internal hook; validated complete bundles
are registered atomically with the published Web job.

## Workspace-scoped application services

`workspace.resolve_workspace(legacy_root=CODE_ROOT, explicit=None)` returns a frozen
`Workspace(code_root, workspace_root)`. Installation code/fonts/locales/registry
remain read-only; private state belongs under workspace_root. `workspace_from_args`
resolves `--workspace` before reading locale/settings. Explicit paths must exist,
be dedicated empty directories or recognizable ledgers/configuration, and retain
state roots within that directory. No fallback, initialization or real migration
occurs during resolution. Omitting the option preserves legacy checkout-local use.

```python
from pathlib import Path
from wealth_ledger.application import ApplicationService
from wealth_ledger.workspace import resolve_workspace

workspace = resolve_workspace(explicit=Path("/path/to/existing/portfolio"))
service = ApplicationService(workspace)
preview = service.preview({"paths": ["/path/to/holdings.csv"]})
operations = service.operations()
# Normal mutation can download missing reference/official data and publish reports.
# result = service.update({"paths": ["/path/to/holdings.csv"], "kind": "monthly"})
# result = service.update({}, resume="OP-...")
```

`update` centralizes detection/request validation, locking, pre-update backup,
staged atomic ingestion, operation recovery, analysis and validated publication.
`record(request, action, label=...)` provides the same lock/backup/staged data-only
operation path to flow, opening and wallet commands; it never publishes a report.
`operation(id)` and `operations()` query only the selected ledger. The service does
not import CLI modules, mutate module-global paths or launch subprocesses. HTTP/job
callers apply server-managed portfolio authorization before invoking the service.

`publishing.publish(project, payload, import_result, lookthrough_run_id=None)` and
`database_backup(project, label)` now live in the core package. The low-level
publisher requires its caller to hold the workspace lock. Backups use read-only
SQLite source connections. Report manifests, validation, failed-build preservation,
revision directories and latest-pointer behavior remain compatible. New bundles
also store `bundle_files` SHA-256 checksums and `previous_latest` so recovery can
verify a completed bundle and finish pointer/state handoff without a new edition.
`verify_bundle` checks operation linkage and every artifact; `recover_publication`
rejects changed/unprovable pointers and corrupted or duplicate bundles.

`update` additionally accepts trusted internal `operation_id`, `expected_fingerprint`
and `on_data_committed` arguments. Web jobs persist their fixed core operation ID
before execution. The expected input fingerprint is checked inside the portfolio
lock. `operations.atomic_data(..., finalize=...)` runs the update commit marker in
the same financial SQLite transaction as imported rows. A saved `execution_at`
remains fixed across queued execution/resume; browser fields cannot choose operation
IDs or arbitrary core arguments. Unknown started states are not automatic retries.
`reporting.generate_reports(..., cache_directory=None)` uses a private temporary
cache by default; publication supplies `workspace/work/cache`. Plotting is serialized
inside a process while process-global library cache paths/settings are scoped and
restored. Workers should process one report at a time; separate portfolio locks
still serialize writes across processes. This is not an HTTP concurrency contract.

`resources.company_aliases(workspace)` loads bundled `config/company-aliases.json`
(version 2), optionally a legacy workspace full v2 file, then
`config/company-aliases.override.json` with this schema:

```json
{"schema_version":1,"companies":[{"id":"synthetic","name":"Synthetic Example","aliases":["Synthetic Holdings"]}]}
```

Overrides replace a complete company row by stable ID; new IDs append. Each row
requires id/name/aliases and may include a sources string array. Unknown schemas,
duplicate IDs and conflicting normalized aliases fail before downloading funds.
Analysis retains bundled/legacy/override raw hashes, effective canonical hash and
precedence as `alias_resources`; saved analysis replay uses frozen results rather
than current overrides. Existing unchanged v2 files preserve their effective hash.
Private overrides never belong in Git. See [adapter protocol](source-adapters.md)
for the independent SRC-001 versioned canonical record contract.

## Offline preflight API

`preflight.preview_update(project, request, now=None)` reads the real project and
creates a SQLite backup/necessary source/cache copies in private system temporary
storage. It reuses importers/reconciliation and returns schema_version, status,
sources, checks, pending_checks, blockers, proposed cutoff and BTC quantity, without
formal data/operation/report writes or public downloads.
`render_preview(result, locale="zh-TW")` renders the selected language; CLI `--json`
returns the same structured result.

`core.inspect_holdings(project, csv_path, kind)` shares `_holdings_plan` with the
importer to check format/deduplication/baseline/revisions/accounts without initializing
the real DB or requiring FX. A new snapshot lacking FX uses only its parsed date as
a temporary base_override, never invented FX/value; simulation_complete is false.
`workflow.select_context(..., base_override=None)` shares time selection; normal
updates do not supply an override.

`fx.read_saved_rates`/`prices.read_saved_quote` are offline reference readers: no exact
cache returns None; invalid existing cache fails. Normal resolvers may download
missing references; preview only uses offline readers. Verified JSON follows the
same validity/evidence rules without generating quotes.

Preview hides newly simulated IDs. JSON issues expose only code/severity/message,
not full orders, addresses, references or accounts. Blocked exits 2; other results
exit 0 but may retain pending quotes/latest ETF/report checks. Formal updates must
revalidate: preview is not a committable operation and cannot survive changed inputs
or concurrent data. See [manual section 20](user-manual.md#20-offline-import-preview).

## BTC report cost estimation

`btc_performance.btc_cost_estimate(crypto)` is a pure no-I/O function with Decimal
precision 80 and `crypto.cost_estimate_policy`. New payloads explicitly set
`actual_only`; missing policy in old saved payloads retains legacy replay semantics,
not a proxy default for new projects.

`actual_only` returns `method=actual_costs_only`, `status=proxy_disabled` and known
buy quantity/spend/reference average/value, but estimated_cost_cad/estimated_gain_cad/
estimated_return are None. `bull_average_proxy` divides completed Bull CAD spend by
delivered BTC+LBTC and applies the average to current total quantity, returning
`method=bull_average_applied_to_all_btc` and estimated cost/P&L/rate. Neither mutates
input or DB.

Proxy includes opening/unexplained differences; reconciliation stays independent.
No buys means no average/cost/P&L; zero holdings with an average means zero estimated
cost/P&L and None rate. Only completed buys change the average; balances/events change
quantity. Never fill actual book/avg_cost/unrealized, contributions or period returns
with the proxy. `btc-cost-estimate.json` records policy/results, checked across formats.

`wallet_reports.quantity_basis_label(crypto)` labels quantity without changing
quantity_status/observations. An opening whose reference_as_of matches valuation
and whose reported_total matches quantity may identify that reported baseline;
later estimation must not imply a new report. Formal anchors distinguish same-time
reports/later estimates. Known events without an anchor remain ledger estimates.
Event/fee coverage, cost policy and quantity provenance are separate.

```python
from pathlib import Path
from wealth_ledger.core import (
    initialize, import_holdings, make_payload,
    import_cash_flows, mark_flow_period,
)

initialize(project)
result = import_holdings(project, csv_path, kind="baseline", fx=fx)
payload = make_payload(project, snapshot_id=result["snapshot_id"])
```

`project`/`csv_path` are Path values. DB: `data/db/portfolio.sqlite3`, mode 600.
Ordinary SQLite has no password/file encryption; permissions are not encryption.

## Holdings import

`kind`: baseline/monthly/interim. First import becomes baseline. Reject pre-baseline
backfill or a later date requested as a new baseline. CSV needs account/security/
quantity/price/cost/value/currency fields and `As of YYYY-MM-DD HH:MM GMT±HH:MM` footer.
Save timezone-aware ISO and UTC for ordering/same-time identity. Required FX:

```python
fx = {
    "usd_cad": "1.4", "usd_twd": "30",
    "usd_cad_date": "2024-06-28", "usd_twd_date": "2024-06-28",
    "usd_cad_source": "https://example.test/cad",
    "usd_twd_source": "https://example.test/twd",
}
```

These are synthetic API rates, not real financial inputs. Require positive rates,
effective dates no later than snapshot and nonempty sources. FX module owns official
fetch/staleness policy. Save rates with snapshots; reimported overrides do not replace them.

- Deduplicate raw SHA-256 and semantically equal normalized numbers/order/UTC time.
- Different content at the same time creates a revision, preserving earlier source/
  snapshot and inheriting the period kind.
- Archive read-only CSVs under `data/raw/holdings/YYYY/MM/`, mode 400; conflicting
  filenames get hash suffixes without overwrite.
- Account IDs are the first 16 SHA-256 characters of account numbers. Display data
  masks accounts; originals still contain full source details.
- Security key: `MIC:Symbol:Currency`; cash: `cash:Currency`. Reject duplicate account/security rows.
- Only LONG CAD/USD market values are supported; reject other sides/currencies.
- Check quantity*price and native cost/P&L with 0.01 tolerance. Larger discrepancies
  become findings while original values remain intact.
- CAD cash book cost never determines current FX/value; retain/flag anomalies.
- Baseline accounts establish expected scope. Later missing accounts are incomplete;
  exits/closures are not inferred. New accounts may import, but differing scopes
  suspend total-portfolio comparisons.

Return status imported/revision/duplicate and snapshot_id. New/revised data also
returns revision/is_complete/issues/source_path; duplicates return fx_preserved.

## Report payload

`make_payload(project)` selects latest data time/revision; snapshot_id selects a
saved revision. Missing/mismatched evidence becomes a finding, not a DB rewrite.

| Key | Contents |
|---|---|
| `meta` | Snapshot ID/time/kind/revision/completeness, missing accounts, row/counts, baseline, currencies, official/history IDs |
| `fx` | Six input keys plus cad_twd |
| `source` | Original filename, relative archive, raw/semantic hashes, rows, import time, integrity_ok |
| `accounts` | Native subtotals, three equivalents, cash/ratios, position counts and portfolio weights |
| `positions` | Per-account securities, excluding cash |
| `securities` | Cross-account aggregation; sum quantity/cost/P&L, recompute weighted cost/return and value/quantity price |
| `cash_rows` | Cash with analogous fields and preserved source costs |
| `totals` | native_cad/native_usd/total_cad/total_usd/total_twd, cash and native noncash costs/P&L |
| `instrument_types` | Source instrument values/weights, such as stocks/ETFs/cash |
| `matrix` | Account columns, security CAD values/account weights and separate is_cash rows |
| `concentration` | largest, top3_cad/top5_cad/top3_weight/top5_weight, cash-inclusive denominator |
| `history` | Latest revision per real observation, values/accounts/completeness without daily interpolation |
| `changes` | Prior/current times, three-currency changes and account/quantity/value/price/weight differences |
| `comparisons` | previous/previous_month/baseline using the changes structure |
| `cash_flows` | Imported actual flows, accounts and source filename/path/hash |
| `periods` | Prior/baseline CAD flow-adjusted analysis per account/portfolio |
| `issues/findings` | Structured issues and legacy summary text, localized at presentation |

Prior formal month means latest baseline/monthly before the current month.
official_snapshot_ids selects the last formal observation each month. Preserve
is_complete; partial data cannot imply total completeness. Missing applicable prior
data or different account scope gives available=False/reason.

## Cash flows and coverage

Required CSV: `date,account_id,flow_type,currency,amount`; positive amounts, direction
by type. Stable flow_id is recommended, otherwise derived from normalized content.
Types: deposit, withdrawal, transfer_in, transfer_out, income, fee, internal.

- USD needs positive usd_cad/fx_date/fx_source or positive amount_cad/fx_source.
  Freeze each conversion; current FX cannot replace it.
- Transfers require transfer_id, same-date/different-account equal-CAD in/out legs.
  Missing/duplicate/mismatched legs suspend period analysis.
- Same ID/content deduplicates; changed content rejects. Flow revision/void API is
  not yet implemented; adding corrected content under a new ID can double count.
- Income/fee/internal are not external contributions. Retained dividends/fees are
  already in valuations and must not be counted twice. Transfers cancel portfolio-wide.

```python
import_cash_flows(project, activity_csv)
mark_flow_period(project, "2024-05-31", "2024-06-30", "complete")
mark_flow_period(project, "2024-06-30", "2024-07-31", "no_external")
# A specific account declaration can be provided using account_id.
```

Coverage: partial/complete/no_external, otherwise not_provided. This is explicit
user evidence, not inferred from absent files. Adjacent monthly declarations may
support baseline periods; gaps/partial declarations block performance. Newer same-scope
declarations win; account-specific overrides portfolio-wide. Portfolio no_external
allows internal transfers; account no_external does not allow that account's transfers.

Require two distinct-date valuations. Date/end-of-day convention excludes opening
day and includes closing day. Validate alignment with snapshot times; date-only
records cannot describe precise intraday timing. Require complete valuations, same
scope, complete flow ledger and valid transfer pairing:

```text
Investment gain = Closing value - Opening value - Net external contributions
Modified Dietz = Investment gain / (Opening value + Weighted flows)
Flow weight = Calendar days from flow date to period end / Period calendar days
```

XIRR: opening/contributions negative, withdrawals/closing positive, 365-day annualization.
Do not recount pre-baseline contributions. Range-check numerical solutions; repeated
sign changes conservatively return ambiguous_cash_flow_signs instead of XIRR.
Dietz is approximate, not exact TWR with valuations at every flow. USD/TWD history
does not inherit CAD returns.

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Synthetic CSVs/isolated temporary projects cover native/cash/FX totals, deduplication,
revisions, missing accounts, month/baseline comparisons, flow weights/transfers,
evidence integrity and undefined ratios. Tests never read or write real portfolios.

## Bull Bitcoin and combined valuation

`crypto.import_bull_orders(project, csv_path, source_account='bullbitcoin-main', opening_assumption=metadata)`
creates crypto_accounts/crypto_sources/crypto_order_revisions and preserves original
CSVs. First import requires an explicit zero-opening assumption; completed economic
values/times cannot silently change. Support CAD Funding/Buy Bitcoin only; all three
statuses must be Completed and completion time must fall within cutoff.

`crypto.make_crypto_view(project, as_ofISOtimestamp)` returns Decimal-string funding,
spend, BTC/LBTC deliveries/equivalents, CAD difference, actual event months and masked
orders. Unclassified Funding is not automatically an external portfolio flow. No
invented missing-month positions. Display excludes ADDRESS, TRANSACTION_ID, MESSAGE
and full order IDs.

`combined.make_combined_payload(project, snapshot_id=None, *, as_of=None, price_file=None, fx=None, source_updates=None, btc_cost_policy=None)`
saves combined_observations. Scope changes create separate baselines, preserving
broker snapshots/positions. BTC is a CAD valuation proxy in totals/types, excluded
from native brokerage tables. Equal replays do not add observations; corrected same-time
data creates revisions.

`prices.resolve_btc_price(project, as_of, override=None)` selects Coinbase BTC-USD
last completed one-minute close, archiving raw evidence/SHA-256 and reusing saved
quotes. Missing complete pricing/evidence stops execution; never substitute purchase
price/zero. Disclose older stock prices/differing cutoffs and incomplete combined
scope. Combined returns need Bull origins/transfers/fees/balance/coverage support;
only eligible confirmed Wealthsimple account performance is currently enabled.
meta.missing_official_months lists months without complete formal observations.

## Automatic source-update API

```python
from wealth_ledger.workflow import identify_inputs, prepare_update

sources = identify_inputs([Path("any.csv")])
payload, result = prepare_update(project, [Path("holdings.csv"), Path("orders.csv")])
```

identify_inputs checks required fields, rejecting unknown/ambiguous formats and
multiple files of one source. prepare_update imports/selects cutoff: stocks use As of;
Bull-only uses execution time; both use execution time when Bull is later. No inputs
reuse latest combined cutoff. Injectable aware now supports offline tests; CLI uses
system time.

meta.source_updates stores status/actual dates. meta.data_status is sources_updated,
carried_source, mixed_dates or btc_only. account_coverage_complete describes source
accounts; is_complete also requires synchronized updates/valuation time. BTC uses
fixed opening/completed buys/known events or an applicable anchor/later events;
independent verification remains separate. History retains status, carried totals
are dashed, and wealthsimple_history preserves original stock dates.

Bull-only first reports explicitly limit scope with snapshot_id=None. Adding stocks
creates a new scope, not growth. Advanced as_of is supported; snapshot_id cannot
combine with new input files.

## Official ETF/company analysis API

`fund_sources.fetch_fund(fund_id, directory, today=None)` takes market-qualified IDs,
such as XTSE:FBTC, and returns holdings date/query status/complete weights/immutable
raw evidence. Strictly check date, identity, pagination and weight type. BMO allocation
is fractional; other current providers use percentages. Vanguard uses paginated
delayeredHoldings. Fetch public issuer data only.

`lookthrough.calculate(payload, funds, aliases)` is pure Decimal: company identities,
recursion/cycles, aggregation, known non-company/unresolved/rounding reconciliation.
Return top20/full companies/paths/unresolved/classification, version company-exposure-2.
Keep security identity distinct from company aliases.

`lookthrough.attach_analysis(project, payload, run_id=None, fetcher=fetch_fund)` fetches
root/child funds, stores fund_sources/lookthrough_runs/source links and attaches
payload.lookthrough. Never substitute old cache on failure. Inject fetcher for
synthetic tests. run_id verifies financial valuation fingerprint and replays offline,
without asset/flow history changes.

lookthrough_reports shares results across MD/PDF, ODS formula tables, complete company/
unresolved CSVs and source JSON. CLI attaches analysis before generating reports;
manifest records run_id. Offline format fixtures are not live evidence.

## Official classification API

`fund_sources.holding(..., gics_sector=None, icb_sector=None, issuer_sector=None)`
separates explicit GICS, ICB and unconfirmed issuer labels; country retains official
classification. Vanguard requests both taxonomies, opening the public fund page
for cookies before official pagination, with no private login/LLM. Parser version:
issuer-holdings-2. Unknown fields stay empty; generic sector never implies GICS.

`classification.calculate_classification(analysis, components, funds, identities, securities)`
is pure Decimal, version official-classification-1, called by lookthrough.calculate.
Components retain source_fund and original gics_sector/icb_sector/issuer_sector/
official_country. Prefer own_official_row, then latest same-company evidence;
equal-date conflicts: conflicting_latest_official_classification; absent:
no_official_classification. Country/region mappings live in the module; unknown codes
are not guessed.

payload.lookthrough.classification contains dimensions/full rows/two coverage measures/
date ranges, components/assignments/evidence, condensed root_groups coefficients,
root_coverage, denominators and policy/version/status. Each dimension reconciles to
investment_total_cad with separate resolved/unknown equities, non-company and adjustment
rows. Never normalize disclosed weights. Merge same-root currencies before coefficients.

classification_reports.report_section/workbook_tables/write_exports share this result;
existing layers call them, with exports linked from lookthrough_reports.write_exports.
allocation-exposure.csv and classification-detail.csv use UTF-8 BOM/fractional ratios;
assignment JSON contains dates, official URLs, source funds, status and method.
reporting._charts produces three same-run PNGs shared across formats.

Save classification in lookthrough_runs.payload_json without schema migration.
run_id still checks valuation fingerprint; older analysis without classification
replays original reports, newer analysis replays saved classifications without today's
data. Optional manifest.classification records version/status/coverage/dates/exports.
Analysis refresh does not add financial history or flows.

## Pre-Bull opening and unknown actual costs

`crypto_opening.import_opening(project, json_path, source_account='bullbitcoin-main')`
reads explicit total-wallet BTC+LBTC, calculates completed buys at reference_as_of and
fixes the difference as attributed pre-Bull quantity. Validate finite/nonnegative
satoshi precision, timezone/scope and total >= buys. Same account/source SHA deduplicates;
new buys never recompute opening. Require imported Bull ledger with intact evidence.

Archive read-only declaration JSON by date/hash. Append
crypto_opening_revisions(id, source_account, revision, payload_json, source_path,
source_sha256, created_at), unique per account/revision, without modifying original
crypto_accounts.opening_json. CLI backs up first. latest_opening(..., cutoff=None)
reads latest revision/checksum. applies_from is provided-order tracking boundary,
not invented acquisition time; earlier cutoffs do not apply it. No reconstructed
trades/values.

Fields include reported_total_btc_equivalent, reference_purchased_btc_equivalent,
opening_btc_equivalent_qty, declared_on, reference_as_of, applies_from, basis,
confirmed_by and referenced CSVs. cost_cad/historical_contribution_cad=null,
network_distribution=unknown, wallet_fees_accounted=false.

make_crypto_view adds opening/purchased/opening equivalent quantities; without a
wallet anchor total is fixed opening + completed buys. qty_btc/qty_lbtc/monthly/orders
still describe Bull buys only. No invented Funding/Buy/flows/acquisition month.

combined.py retains value/FX, but unknown opening makes complete CRYPTO book_native/
book_cad/avg_cost/unrealized_native/unrealized_pct and affected native cost/P&L totals
null. valuation also stores known_bull_cost_cad, opening_market_cad,
bull_purchase_market_cad and cost_status. _partial_summary is combined-only, not a
brokerage cost change. ODS actual fields use unknown text, never SUMIFS zeros. Explicit
proxy estimates stay separate from actual payload fields.

scope_id includes opening_revision_id. Backfill/revision creates a new comparison
baseline; preserve combined_observations/reports. No-input regeneration retains
cutoff/frozen quotes. New scope changes valuation fingerprint, requiring new official
ETF analysis, not an incompatible frozen replay.

## Wallet and operation APIs

`wallet.add_balance(project, amount, as_of, source=..., time_basis=..., replaces=..., now=...)`
saves all-wallet equivalents; equal-time duplicates deduplicate, changed quantities
need revision. wallet.add_event needs type/quantity_btc/occurred_at/source/reference,
optional balance_id. own_transfer/conversion have zero net quantity.

`wallet.revise(... expected_revision, reason, action)` appends revisions; identity
fields cannot change, requiring void/replacement. records/get_record/balance_detail/
revision_history are read-only. wallet.make_crypto_view(project, cutoff, strict=True)
wraps Bull with anchor/reconciliations/events/full-ledger expectation/unresolved state;
only post-anchor events change reported quantity. Unknown history, negative holdings
or archive-integrity contradictions may block valuation.

operations.atomic_data validates importers in isolated SQLite, then installs via one
transaction. Source bytes remain intact; failed data stages leave no partial formal
records. execute_update separates commit/publication and saves request/result/fixed
cutoff/fingerprint/publication in update_operations. Resume reuses accepted inputs,
not original CSVs; reference overrides are archived. Later input revisions expire
unpublished operations; published retries return saved results.

Data-only APIs never publish. `ApplicationService.record` supports an optional stable operation ID and expected input fingerprint; data and its `data_only_complete` marker commit atomically, while exact completed retries reuse the saved result. CLI uses project_lock/backup/operations; direct mutation
callers must arrange backup/locking/batch safety. prepare_update can consume committed
accepted input; formal CLI does not use it to commit external inputs one by one.
No API/CLI needs an LLM.

Wallet tables initialize on first write: wallet_records stores stable identity/source
keys; wallet_revisions appends declarations; wallet_links relates event revisions to
selected/prior balances via foreign keys; wallet_balance_slots enforces one active
same-scope/UTC observation. Presentation is America/Toronto; DB/evidence retain UTC/
original times and explicit/execution_time basis.

crypto.monthly_purchase_price(row) returns Decimal buy_cost_cad/buy_btc_equivalent_qty
or None for zero quantity. Monthly views serialize average_purchase_price_cad_per_btc
as string/null. Reports reuse it without new DB columns or transaction changes.

## Report publication validation

report_checks.validate_report_presentation(payload, output) uses existing pypdf and
standard XML/JSON/Decimal to check effective opening/quantity, known Bull spend,
unknown actual complete cost/P&L, policy-specific proxy values/formulas/supplements,
quantity/fee provenance and reconciliation availability across formats. Unknown
actual fields cannot have numbers/formulas. Valid zero quantity/gaps remain numeric.
With backfill, old assumptions stay only in btc-opening-audit.json, which must match
the payload/declaration. No crypto: not_applicable; success: passed/checks/policy;
failure: ValueError.

reporting.generate_reports returns supplement filenames and produces opening audit
JSON for separate opening declarations, including report_as_of, original/effective
assumptions, quantity/cash states and policy without input/DB mutation. Publisher
checks after formula validation but before moving bundle/latest. Manifest records
presentation_validation/reporting.supplements and selected btc_cost_policy; policy
separates actual-only/proxy validation. Failures preserve operation/cutoff for retry.

## Local policy and future adapters

settings.btc_cost_policy(project, override=None): explicit override -> local setting
-> actual_only. Reject unknown policies/invalid TOML. Ignored config/local.toml
[reporting] btc_cost_policy or --btc-cost-policy chooses the proxy. It is presentation
only. combined.make_combined_payload attaches cost_estimate_policy after saving
financial observations; policy changes do not create observations.
workflow.prepare_update(..., btc_cost_policy=None) passes it through; requests freeze
resolved policy for retry despite later config changes. See config/local.example.toml.

Current CSV detection supports two known formats. fund_sources.REGISTRY is official
ETF support, not a general arbitrary-source plugin SDK. Future kinds, conflict/
submission remain planned. SRC-001 canonical contracts and the independent
SRC-002A `source_registry` library are described in
[adapter design](source-adapters.md#implemented-registry-library-src-002a). The registry
loads/detects explicitly enabled trusted parsers. SRC-002B `source_pipeline.plan_sources`
is shared by the source-parser CLI and owner-only `/source-plans` jobs, with host
configuration/code fingerprints and bounded nonbooking execution. Normal financial
imports retain their current implementations; source plans cannot submit batches;
arbitrary bank/exchange CSVs cannot replace supported imports.

SRC-003 ships that same contract in an audited installable core wheel, together
with `source_testing.check_contract`, `check_rejected` and `record_index`.
The installed console and checkout wrapper share `source_cli.main`.
See [the SDK guide](parser-sdk.md) for the independent example, explicit enablement,
artifact privacy, installation/derived-image acceptance and v1 limits. Installed
resources use `workspace.CODE_ROOT` (the package resource bundle); `PACKAGE_ROOT`
identifies executable modules. `resolve_workspace(explicit=...)` requires a private
existing directory outside the package installation; no implicit site-packages
ledger is created. Source checkouts retain their original workspace behavior.

## Locale presentation APIs

settings.report_locale(project, override=None) reads CLI/local/new/legacy defaults;
ensure_report_locale_setting(project) saves defaults only during normal locked work.
Invalid locale fails before submission; legacy defaults zh-TW, new defaults en-CA.

i18n.presentation_context uses ContextVar; tr validates named parameters;
display_payload deep-copies presentation fields without mutating financial inputs.
SourceText preserves source wording. validate_catalogs checks keys/parameters.
context.metadata supplies catalog/font SHA and format/render versions.

generate_reports(..., locale=...), build_workbook(..., locale=...) and
render_preview(..., locale=...) share resources. Direct Python calls without locale
retain legacy zh-TW compatibility; CLI separately resolves project settings.
verify_workbook/validate_report_presentation discover ODS metadata or use legacy zh-TW.
Formula sheet IDs map to localized display names.

editions.render_language_edition(source, output, locale) reads a saved bundle into a
new output, preserving data.json bytes without DB/network/latest access. Manifest
records source checksum/fingerprint and new presentation version; missing legacy
checksums disclose weaker metadata consistency. See [locale contract](i18n-plan.md).

## Explicit-context canonical facts (SRC-004A)

`source_v2` defines lossless facts and strict `decode_batch` replay without parser
execution. `source_ingestion.prepare_ingestion` is read-only; `commit_ingestion`
uses the existing service lock, backup, atomic data/receipt boundary and private
immutable evidence. `read_facts` is not a report payload or contribution calculator.
See [the complete API/phase contract](source-ingestion.md). Registry detection can
inspect API2, while the v1 source-plan route rejects it without explicit context.
Normal importers remain direct, and generating a new legacy financial report from
a canonical-v2 workspace fails closed until SRC-004B/C implement projections.

## Explicit-context parser preview

`source_builtin.registrations()` supplies trusted Wealthsimple/Bull v2 parsers;
`source_formats` owns their byte-only grammars shared by the legacy import facades.
`source_context_pipeline.parse_sources(paths, contexts=..., config_path=...)` runs
a fresh bounded child and returns `ParsedSources(receipt, batches, raw)`. The host
strictly decodes and validates each canonical batch without importing plugin code
again. Results are private evidence, not permission to book or publish reports.
`plan_context_sources` returns only the nonbooking summary. Context, original bytes,
normalized bytes, selections, configuration, catalog and actual environment participate
in its fingerprint. Revalidation rejects changes; it does not update a saved receipt.
See [schema and limitations](source-ingestion.md#explicit-context-previews-src-004b1).
