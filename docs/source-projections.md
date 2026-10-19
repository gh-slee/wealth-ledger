# Source-neutral projection model

SRC-004C1 implements `wealth_ledger.source_projection.project_sources`. This is an
**internal, read-only analysis model**, not a report payload, new public API route,
browser feature or daily-workflow switch. It reads verified canonical-v2 archives
and financial state without executing a parser, downloading references, initializing
a database, changing history or generating reports. No runtime LLM is involved.

The existing `report_projection_unavailable` gate remains in force. SRC-004C as a
whole is unfinished. Do not use a C1 model as a replacement for a published report
or as authorization to import/migrate a real portfolio.

## Explicit inputs and reproducibility

```python
from pathlib import Path
from wealth_ledger.source_projection import project_sources

model = project_sources(
    Path("/path/to/disposable/synthetic-workspace"),
    period_start="2024-01-01T00:00:00Z",
    as_of="2024-03-01T00:00:00Z",
    fx={
        "usd_cad": "1.25", "usd_twd": "30",
        "usd_cad_date": "2024-02-29", "usd_twd_date": "2024-02-29",
        "usd_cad_source": "synthetic-fixed", "usd_twd_source": "synthetic-fixed",
    },
)
assert model["review_only"]
assert not model["report_projection_ready"]
assert not model["report_published"]
```

Both times must have offsets and the period start must precede the cutoff. FX is
optional: absent rates leave conversions unknown while retaining native CAD/USD
observations. Supplied rates must be positive decimal strings (or `Decimal`), with
nonfuture effective dates and explicit sources. They are display conversions at
the cutoff, **not historical cash-flow FX**. Numeric JSON floats are rejected.

Financial arithmetic uses a deterministic decimal context, independent of the host
process precision, rounding or exponent settings. Analysis exceeding a bounded
4096-digit precision/exponent range fails closed rather than silently rounding
extreme canonical values. The canonical store remains lossless.

The model records the logical `state_sha256`, explicit inputs and a deterministic
`projection_sha256`. A concurrent financial state change rejects the result.
The digest is not a publication signature or frozen-history receipt. This is a
view of **current recorded revisions at an economic cutoff**, not a reconstruction
of what was known on that historical date. Read frozen report bundles for original
historical presentations and historical FX/price evidence.

## Positions, observations and coverage

- Each source account selects its latest snapshot not after the cutoff, including
  explicitly empty snapshots. Historical snapshots are never summed as current
  assets. Equal-time competing observations fail closed for explicit resolution.
- The model preserves namespaced source identity, source revision, observation time
  and the existing ledger account ID from its immutable binding. An older selected
  observation is marked `carried`; its stock price is not refreshed implicitly.
- Source unit price, native/CAD book costs and source unrealized values remain
  separate. An unknown value stays `null`, while explicit zero stays zero. No unit
  price or source CAD acquisition cost is invented through division/current FX.
- `observed_values` and `native_observed_values` sum **observed rows only**. A known
  empty observation may have a zero observed subtotal; that never proves zero
  complete wealth. `complete_portfolio_values` is always `null` in C1.
- Assets omitted by partial snapshots become `unobserved_prior_assets` gaps, with
  no fabricated sale, zero quantity or refreshed price. Gaps persist across partial
  observations; a later complete observation resets that account's observed scope.
  Corrections to an observation replace its membership without resurrecting
  superseded rows when an older batch is replayed.
- Funding-account observations remain in `funding_observations`, separate from
  portfolio assets. Recorded cash movements are not inferred cash balances.
- Structured membership/coverage declarations remain visible. Their status does
  not prove completeness of a person's entire wealth. Raw source audit fields,
  parser context, transaction addresses and lifecycle payloads are not copied into
  normal projected rows.

## Contributions and cryptocurrency

Cash flows use `(period_start, as_of]`. Only explicitly external completed deposits
and withdrawals form `known_external_net_native` and its optional display
conversion. Purchases, purchase cash legs, matched internal transfers, income and
fees are not additional capital contributions. Pending/cancelled/voided records
produce no active capital effects. Unclassified funding and unresolved transfers
remain unresolved; a matching counterpart after the cutoff does not close an
earlier interval.

`account_coverage` joins contiguous complete cash-flow declarations. A gap does not
mean no activity. `period_coverage_complete` refers only to the **canonical bound
accounts**, not omitted legacy accounts or outside assets. Full-period external
contributions and investment performance remain unavailable in C1:
`period_net_external_values: null`, `performance_ready: false`.

`movements` projects active completed effects once, retaining BTC/bitcoin and
LBTC/liquid independently and their combined BTC-equivalent **quantity change**.
It excludes future/pending events and handles explicit separate fees without
subtracting included fees twice. Purchase rows retain source-leg quantity, net
recorded quantity change, source CAD cost and a purchase rate explicitly based on
cash-leg spend per source-leg BTC. An all-in cost is available only where the
relevant fee/cost values are known. A nonvalued crypto fee cannot invent a CAD acquisition amount.
The movements are cumulative recorded changes through the cutoff; they do not
include an opening balance and cannot establish total holdings. `wallet_balance`
is `null` and `wallet_balance_verified` is false.

## Legacy coexistence and remaining acceptance

Legacy bindings keep the original account IDs, but C1 does not sum legacy rows with
canonical facts. `legacy_state_present`, `legacy_bindings` and
`legacy_merge_ready: false` make the boundary explicit, including legacy wallet-only
state. The original ledger/report bytes and daily native behavior are unchanged.

C2 supplies the read-only compatibility layer described below. The remainder of
SRC-004C must complete:

1. Production imports/declarations, frozen valuation/history publication and retry
   through the compatible financial basis, with original IDs and operation context.
2. Shared CLI/Web reports, three-locale ODS/Markdown/PDF/chart parity,
   backup/empty-restore and a synthetic third parser through real imports/reports
   without provider branches in the projection/report core.

Keep the phase gate until those acceptance conditions pass. Formal private adoption
and deployment require a separately approved migration plan.

## Verification

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_source_projection.py' -v
```

The 29 synthetic tests cover both current built-in formats and an additional
provider using the same projection logic, irregular/partial/empty observations,
revisions/voids, explicit FX, unknowns, funding/purchase/transfer effects, fees,
archive integrity, concurrency, legacy binding preservation and unchanged report
gates. This proves the internal model's provider neutrality, **not** the complete
third-provider financial/report workflow. Installed-wheel acceptance runs these
same tests outside the checkout. See [ingestion](source-ingestion.md),
[adapter acceptance](source-adapters.md#delivery-sequence-and-acceptance-gates) and
[the roadmap](../TODO.md).

## Legacy and wallet compatibility (SRC-004C2)

`wealth_ledger.source_legacy_projection.project_compatible_sources` is a separate
**read-only internal model**, composed over C1. It is not the production report
payload or a new CLI/HTTP/browser route. C1 remains canonical-only; its flags and
behavior are unchanged. C2 returns `legacy_merge_ready: true` only after its
supported compatibility checks succeed, while `report_projection_ready` and
`report_published` remain false. All normal canonical report gates remain.

```python
from pathlib import Path
from wealth_ledger.source_legacy_projection import project_compatible_sources

model = project_compatible_sources(
    Path("/path/to/disposable/synthetic-workspace"),
    period_start="2024-01-01T00:00:00Z",
    as_of="2024-03-01T00:00:00Z",
    # Optional explicit reference FX, exact-cutoff BTC quote and cost policy.
    btc_cost_policy="actual_only",
)
assert model["review_only"] and not model["report_projection_ready"]
```

### Identity and old evidence

C2 checks SQLite integrity/foreign keys and all archived legacy holdings/activity,
order, wallet and opening source hashes. It rejects unsafe paths/symlinks, corrupted
order payload hashes and unsupported native crypto schemas. This is an integrity
check against retained host evidence, not an independent authentication of an
unsigned historical database or source document.

Explicit `legacy_holdings`/`legacy_crypto` bindings keep original account identities.
A canonical observation at the same account/time must match the old financial
signature, or have an archived original revision that proves the explicit correction
lineage. Unproven changes fail closed. Original snapshot IDs and frozen rows remain
unchanged. A known superseded whole snapshot cannot reset the latest legacy state
without proof of an explicit correction from that state. Later partial observations
retain other accounts and expose omitted prior assets as gaps; accounts missing an
eligible observation remain present with unknown values, never a fabricated zero. Earlier applicable legacy observations remain usable when
there is no eligible newer canonical observation; none are relabeled as fresh.

Orders merge by bound source identity and stable order ID, never amount/date alone.
Compatible duplicates produce one acquisition; distinct IDs with equal economics
remain distinct. Completed native economics must agree with actual canonical legs
and costs as well as lifecycle fields. A partial order export cannot discard old
purchases or funding. Known native cash balances use the original explicit zero-CAD
assumption and deduplicated funding/spend, including known separate cash fees.
Negative cash remains visible and blocks its valuation; it is never clamped or
explained by invented funding. New source accounts inherit no opening assumption.

Funding associations require typed purchase cash legs or the same uniquely
identified old funding event. If a funding-only subset shares an old account group
but has neither proof, C2 rejects with `legacy_cash_binding_required`; provide an
export containing the relevant purchase/funding identity before proceeding. C2
does not infer a cash-account relationship from a similar alias or amount. An
ambiguous relationship requires host review, not an automatic financial merge.

### Shared BTC reconciliation and costs

`wallet_reconciliation.reconcile_wallet` is pure code shared with the existing
native wrapper. It receives signed acquisition changes, the applicable explicit
opening and current append-only wallet records. Integer satoshi arithmetic is
independent of the process decimal context. It retains:

- Original balance/event IDs and revisions, fixed opening references, linked
  balance intervals and first-recorded versus currently recalculated residuals.
- Latest eligible user-reported balance plus subsequent known changes, with
  same-time changes included in the observation rather than counted again.
- Prior unresolved gaps, stale links and opening/backfill overlap warnings.
  New observations never erase earlier unexplained differences.
- Unknown pre-observation history as unknown, and negative holdings as a blocking
  contradiction. New canonical accounts never acquire a zero opening implicitly.

Original frozen combined history supplies the BTC scope account ID where present;
otherwise an existing single native acquisition account or explicit global wallet
scope is used. Platform acquisition accounts are not additional full wallet
positions. BTC and LBTC networks remain in acquisition evidence while quantity is
reconciled for the declared all-wallet BTC-equivalent scope.

`btc_price` is optional and must be a positive decimal reference with provider,
source and an eligible completed minute candle for the exact cutoff, as required
by `prices.validate_quote`. It is caller-supplied evidence, not a price fetched or
independently verified by C2. Missing FX/price values remain unknown. No quote or
new FX is applied to old frozen history.

`actual_full_cost_cad` stays unknown; retained purchase costs do not establish all
opening/disposal costs. The default remains `actual_only`. Explicit
`bull_average_proxy` uses only the identity-deduplicated **Bull purchase cohort**,
not purchases from another platform. Its unchanged acquisition average can be
applied to a changed user-reported total as an estimate. Actual historical costs,
contributions and reconciliation gaps are never filled by that proxy.

### Cash-flow dates and frozen history

Legacy cash flows keep date-only precision and original sourced CAD values/FX.
Their date bounds use the explicit report timestamps' offsets, not an invented
midnight instant or an implicit UTC next day. Exact canonical overlaps retain the
original historical CAD value and are not added twice. Unmatched new USD flows
without historical conversion evidence remain unknown for contribution arithmetic;
cutoff display FX cannot replace their historical acquisition/contribution FX.

`covered_account_periods` reuses the original explicit flow coverage declarations
and their account-over-global precedence. It exposes a dated **external** CAD net
only where coverage and historical conversions allow it, with declaration IDs.
Absent/incomplete coverage, unclassified source funding, missing historical FX and
contradictory no-external declarations remain unavailable. This external subtotal
is not total capital flow to an account: matched internal transfers require their
own account-capital treatment before performance calculation.

`known_recorded_external_cad` is a recorded subtotal with explicit date/instant
precision, not a complete total of personal contributions. Full portfolio period
contributions, investment gains, Dietz and XIRR remain gated. Unknown outside
activity, wallet scope and fee/counterpart coverage are not inferred complete.

`legacy_snapshot_history` preserves original IDs/revisions/dates/source IDs/frozen
FX. `frozen_combined_observations` copies saved observation values and revisions;
it never reprices or generates missing months. This is separate from a new
historical report edition or replay of original published report bytes.

The final model binds financial state, private settings, frozen history and input
quotes. Concurrent changes invalidate the result. No database/evidence/report is
written or migrated by this read function.

### Remaining production acceptance

C3C must route ordinary CSV and saved-data daily workflows through the compatible
basis, preserve first-recorded expectations and fixed valuation/recovery contexts,
and materialize reports through the shared pipeline. C3A now connects BTC declaration writes to the compatible basis as described below.
Ordinary import/report routes remain gated; a C2 read result alone never authorizes
publication.

Three-locale ODS/Markdown/PDF/chart parity, a third parser through actual reports,
full backup/empty-target restore and original frozen-history preservation remain
required before removing the canonical report gate or switching a real daily
ledger. Private deployment/adoption still needs a separately reviewed and approved
plan. No existing user's data was migrated to implement C2.

Focused checks: `test_source_legacy_projection.py` (33 synthetic cases) and the
existing `test_wallet.py` (47 cases), plus the full suite and installed-wheel
acceptance. These verify the compatibility boundary, not a deployed private Web
instance or complete production plugin workflow.

## Source-aware BTC declarations (SRC-004C3A)

`wallet_basis.py` now supplies the existing CLI and Web declaration paths with a
shared source-aware financial basis. It does not parse an input, resolve prices/FX,
render/publish a report, infer contribution coverage or enable ordinary canonical
CSV updates. Native-only workspaces retain their historical declaration behavior.

When canonical batches exist, balance expectations and balance-detail queries use
C2's verified, identity-deduplicated acquisitions, fixed opening and active wallet
records. New records retain first-recorded expected quantity/residual and a
`calculation_basis` state/model hash. Later source backfills or linked fees can
change the current reconciliation without rewriting those original values/hashes.
Unknown expectations are null, never the native display fallback zero. A new user
observation can anchor current quantity while older unknowns/residuals remain.

Linked events use the first known acquisition boundary or preceding observation;
the interval remains `(previous observation, target observation]`. Unlinked events
and revisions also verify the canonical compatibility/evidence boundary. No fee,
contribution or disposition is invented to explain a reported difference. The native
report-shaped `wallet.make_crypto_view` rejects canonical workspaces; supported
source-aware record queries use `wallet.balance_detail` instead.

### Fixed pre-tracking opening

`crypto_opening.import_opening(project, json_path, source_account=None)` retains
native Bull derivation when no canonical batches exist. In a canonical workspace,
its unchanged declaration JSON schema explicitly attributes:

```text
Opening BTC = reported total at reference time
            - identity-deduplicated net acquisition quantity through that time
            - signed known manual events through that time
```

The calculation uses integer satoshis, including separate recorded purchase fees,
without changing Bull purchase-cost averages. It ignores balance observations as
acquisitions. No eligible acquisition history, a negative result or pre-source
manual events require a balance/reconciliation instead of an invented opening.
Actual opening cost and historical contributions remain null.

New openings use one all-wallet scope; a revision of an existing native opening
keeps its original scope key/ID lineage. `source_account=None` selects the existing
unique scope or `all-wallets-btc-plus-lbtc` for a fresh canonical opening. An explicit
different key cannot create a second concurrent all-wallet opening. The existing
storage schema and archived native declarations are unchanged.

`reference_purchases` freezes account/source ID, timestamp and net quantity;
`reference_events` freezes event ID, type, timestamp and quantity. Link/reason-only
revisions do not alter this financial footprint. Later normal purchases do not
rederive opening. New/changed/voided old-date purchases or events expose
`opening_overlap` and block unanchored quantity valuation until reconciled. A new
observation can anchor current quantity; it does not erase that warning. Earlier
cutoffs compare only the applicable part of the frozen footprint, never future buys.
Repeated identical declaration evidence returns the original revision even after
new transactions. An intentional opening correction needs a new explicit declaration;
Web preview requires the current opening revision. Never submit a fresh total as
an opening merely to hide a residual; use a balance observation for later totals.

### Entry points and remaining gates

Use the existing [CLI examples](user-manual.md#19-btc-balances-events-and-reconciliation)
and [Web Financial records](web-financial-records.md). No new endpoint, request
schema, database migration or runtime dependency is required. Web preview simulates
on a disposable copy, confirmation rechecks financial/engine state under the lock,
and the worker commits declaration evidence with its durable completion marker.
Recovery reads that result rather than rerunning the declaration. Source-state
changes stale an earlier Web preview. Backups include these records/references.

C3A tests cover native/canonical overlap, unknown/zero quantity, exact satoshis,
fixed opening revisions/backfill, a synthetic third provider, actual CLI record
commands, Web preview/confirmation/staleness/recovery and Docker empty-volume restore.
They do not establish a third parser's complete report workflow. Source ingestion
receipts remain data-only; normal canonical imports/new reports are still blocked
until C3C acceptance. Existing frozen reports remain readable and unchanged.


## Source report payloads and frozen valuations (SRC-004C3B)

C3B implements a trusted Python core interface over verified saved native/canonical
facts. It renders reports without dispatching a provider parser. It does **not**
add an ordinary import command, browser form, HTTP route, report registration or
`latest` publication. Those remain C3C; `report_projection_unavailable` is retained.
A rendered development bundle is not a published Web report or a daily-use switch.

### Explicit inputs and entry points

```python
from pathlib import Path
from wealth_ledger.application import ApplicationService
from wealth_ledger.workspace import resolve_workspace
from wealth_ledger.source_valuation import read_source_valuation
from wealth_ledger.reporting import generate_reports
from wealth_ledger.workbook import build_workbook

# Use a disposable synthetic workspace while evaluating this developer interface.
workspace = resolve_workspace(explicit=Path("work/synthetic-ledger"))
service = ApplicationService(workspace)
inputs = {
    "as_of": "2024-03-01T00:00:00Z",
    "period_start": "2024-01-01T00:00:00Z",
    "generated_at": "2024-03-01T00:00:00Z",
    "kind": "interim",
    "fx": {
        "usd_cad": "1.5", "usd_twd": "30",
        "usd_cad_date": "2024-02-29", "usd_twd_date": "2024-02-29",
        "usd_cad_source": "synthetic-fixed", "usd_twd_source": "synthetic-fixed",
    },
}
payload = service.source_payload(**inputs)  # Read-only; no observation is saved.
receipt = service.source_valuation(inputs)  # Lock, backup, atomic staged write.
frozen = read_source_valuation(workspace.workspace_root, receipt["observation_id"])
output = Path("work/synthetic-source-report")
artifacts = generate_reports(frozen, output, locale="en-CA")
build_workbook(frozen, output / "portfolio.ods",
               chart_images=artifacts["charts"], locale="en-CA")
```

`workspace.workspace_root` is the resolved portfolio directory. Financial inputs use decimal
strings or `Decimal`, never binary floats. Times must include offsets. FX effective
dates cannot be later than the cutoff; generation cannot precede it. Optional
`btc_price` follows the C2 explicit BTC-USD minute-candle contract, including provider,
reference URL and candle boundaries. No automatic quote lookup, parser, LLM or local
LibreOffice is invoked. An absent quote leaves BTC value unknown without discarding
a known quantity. `btc_cost_policy` defaults to `actual_only`; the Bull-cohort proxy
is explicitly opt-in. Existing source evidence must be imported through its approved
ingestion path first; this API does not import a CSV.

### Values, coverage and costs

`meta.report_model` is `source-neutral-1`. CAD/USD/TWD totals are **valued observed
subtotals**, and all weights use the stated observed denominator. Complete wealth
and period returns remain unavailable. Carried securities retain original source
prices/dates, native amounts, source CAD book cost and original account/security/
observation IDs. Aggregates retain member provenance; unavailable or mixed-date
unit prices are not replaced with an implied value/quantity quote. Current display FX never rewrites source CAD cost or prior editions.

No observation means unknown. An explicit empty holdings observation means an
observed zero for that scope. An unpriced wallet is excluded from the valued subtotal
with quantity and missing quote disclosed. Known account cash can still contribute
a partial subtotal in the same account. Canonical funding/buy movements do not prove
a cash balance. Known negative reconstructed legacy cash is disclosed and excluded,
never clamped to zero or counted as a positive asset.

Actual BTC full cost/P&L remain unknown when historical acquisition/disposal costs
are incomplete. An optional proxy is a separate estimate using the deduplicated
Bull cohort. Fixed openings, anchors, immutable recorded residuals, recalculated
residuals, linked events and backfill conflicts remain visible. A known native zero
opening is distinguished from an unknown opening; obsolete assumptions are not
promoted to current effective values. Monthly BTC tables include delivered quantity,
net recorded change, CAD purchase spending and weighted purchase rate. They do not
rename purchase spending or funding as complete contributions.

### Frozen editions and history

`source_valuation` stores derived editions in `source_report_observations` and
content-addressed `data/raw/source-valuations/<sha256>.json`, separate from source
facts. Repeating the same cutoff/projection/scope/kind returns the saved edition;
changing only generation time does not create one. A changed financial/reference/
settings projection at the same cutoff creates a new revision without rewriting
old bytes. These are derived report revisions, not additional source transactions.
Reading a saved ID verifies database/archive bytes, checksum, safe path and metadata;
it does not load parsers, fetch prices, use current settings or mutate the ledger.
Rendering that frozen payload in another locale also does not create a valuation.

Read-only payloads explicitly mark the current prospective row as an unsaved
preview, without a valuation ID. Saved editions show their stable ID/revision.
History uses actual saved dates and latest revisions for the same scope, up to the
cutoff. Missing months are not interpolated. Changed account/wallet scope starts a
separate comparable series; old edition IDs remain readable. Native historical
snapshots/combined observations retain their own IDs, dates and historical FX and
are displayed separately rather than spliced into a newly calculated growth curve.
Two distinct saved source dates enable the historical-value chart. Unknown values
remain gaps, and complete-period growth, Dietz/XIRR and contributions remain disabled.

An optional `operation_id` enables existing atomic receipt recovery; a repeated
completed operation returns its proven result without recalculation. Optional
`expected_fingerprint` rejects stale previews before writes. Failed staging cannot
leave a live edition/archive. This core method uses the existing Web maintenance
barrier through the operation service. Full instance backups include the database,
raw valuation archives and receipts; empty-volume restore retains the same editions.
There is no new restore command or automatic publication.

### Report and acceptance boundary

Shared sections drive en-CA/zh-TW/zh-CN Markdown, embedded-font PDF and self-contained
ODS with matching amounts, source dates, coverage and unknowns. Eight standard
charts remain; optional history, BTC acquisition/spending/reconciliation and existing
company/sector/country/region analyses use explicit available inputs. Optional ETF
analysis consumes separately attached/frozen official evidence with the existing
fetch/replay policy; the report builder never performs an implicit refresh. Its
weights describe the observed investment subset, not all personal wealth. ODS
formulas cover source-linked values/FX/subtotals; analysis ordering, some summaries
and images are frozen. See [ODS limitations](workbook.md#source-neutral-report-editions).

`test_source_report.py` covers read-only inputs, scope/unknown/zero distinctions,
original IDs/dates, history/revisions, integrity, concurrent changes, atomic failure/
recovery, all three formats/locales and explicit synthetic exposure analysis. The
installed-wheel suite runs the same tests outside the checkout. Docker acceptance
freezes canonical-only and mixed native/canonical editions, then verifies their
hashes after a full backup and restore into a new empty volume. All fixtures are
invented. This evidence does not establish an actual personal deployment or C3C's
third-parser/ordinary browser confirmation/publication workflow.


## Frozen source report publication (SRC-004C3C1)

C3C1 connects verified v2 input facts to actual reports through an opt-in trusted-host
workflow. It is **not** the regular `update.py`/Web import cutover: those routes,
optional total-entry integration and source-aware browser projections remain C3C2.
The native canonical report gate is deliberately retained. B2 remains data-only;
confirming a B2 source submission still does not generate a report automatically.

### Core entry points

- `ApplicationService.source_report_preview(paths=(), valuation=..., directory=...,
  contexts=(), bindings=(), config_path=None, selections=None, timeout=60)` parses
  CSVs once in an isolated child, uses the existing explicit mapping contract and
  simulates compatible values offline in a disposable workspace.
- `source_report_confirm(directory, approval_sha256, config_path=None,
  on_data_committed=None)` validates the exact frozen approval under the workspace
  lock and commits facts, a derived valuation, frozen analysis and an atomic report
  operation marker together. It then publishes the approved frozen report inputs.
- `source_report_resume(operation_id)` verifies the durable commit/archive and
  resumes publication only. It never reads the old CSV paths, loads a parser,
  fetches FX/BTC quotes, refreshes ETF holdings or recomputes portfolio values.

CSV inputs require explicit v2 host contexts and reviewed account bindings as in
[B2](source-ingestion.md#frozen-submission-and-recovery-src-004b2). Missing bindings
return `mapping_required` without saving an approvable bundle. `paths=()` instead
uses already verified facts; it neither infers missing activity nor imports inputs.
This interface uses previously recorded BTC openings/balances/events; it does not
add a BTC-total argument or replace financial declaration commands/forms.

`valuation` requires offset-aware `as_of`, `period_start`, `generated_at` and explicit
CAD/USD/TWD `fx`. Optional fields are `btc_price`, `kind`, `btc_cost_policy` and
`report_locale`. Schema and quote rules are identical to C3B. Decimal strings are
required in JSON. There is no implicit quote lookup or wall-clock cutoff selection.
Known valued rows form an observed subtotal; unavailable wallet/cash scope stays
unknown. The caller reviews those limits before approving the digest.

### Approval and atomic recovery

The private preview bundle has a closed manifest, configuration bytes and optional
nested frozen ingestion evidence. Its SHA-256 binds the workspace, operation ID,
financial/settings/reference fingerprint, actual code/dependency environment,
locale/catalog metadata, mappings, original CSV/normalized bytes, explicit valuation
and simulated compatible scope/totals. Confirmation rejects changed evidence,
settings, source state, parser configuration or environment. No parser is called
again during confirmation. Failed staging does not install financial facts or
valuations; the failed operation audit remains. Create a new reviewed preview for
a proven data failure rather than reusing its operation ID.

On first confirmation, the existing official ETF fetch/replay implementation runs
in staging once, preserving effective/fetch dates, hashes, coverage and unknowns.
Fetch failures stay explicit rather than reusing stale sources. The approved cutoff
and FX/BTC references are fixed; ETF freshness and report rendering are identified
as pending at preview, not falsely described as completed offline checks. No assets
at all means no analysis denominator; an entirely unknown report does not invent
zero equity exposure. No parser/provider branch is added to valuation or publishing.

The operation retains its exact report payload, localization and analysis under
`data/raw/source-publications/<sha256>.json`, separately from the C3B valuation
archive. Publication-specific status lives in the operation/manifest; the frozen
report copy omits the C3B developer-stage status flags. Original derived valuation
bytes remain unchanged. `data_committed` and `report_failed` always refer to the
same fixed operation/payload. Later financial facts stale an unfinished operation;
changed presentation catalogs require review, not silent reinterpretation.

A completed checksummed bundle can finish a crash-interrupted pointer handoff
without a second edition. Retrying an already published ID verifies its original
artifacts and leaves a newer latest pointer untouched. Reading a copied/restored
workspace finds the operation-bound relative bundle rather than trusting an old
host's absolute path. Restored publication data/analysis/locale/source IDs and old
report bytes remain frozen. Backup/copy-adoption validation verifies archived report
payloads against their derived valuations and published bundles.

This is core/advanced-CLI publication. It does not create a browser job/report-library
registration for a Web-managed portfolio. Do not use it to bypass a Web import gate
or switch a real daily workspace. Ordinary worker/UI integration and complete
cutover acceptance remain C3C2.

### Advanced CLI examples

Use a disposable synthetic ledger while evaluating this pre-release interface.
Create its directory first and keep it separate from installation code. The
checkout command is `python scripts/source_reports.py`; an installed wheel supplies
`wealth-ledger-source-reports` with the same subcommands. This example assumes
private `context.json`, `bindings.json`, parser configuration and source CSVs have
already been prepared using the SDK/B2 formats.

A synthetic `valuation.json`:

```json
{
  "as_of": "2024-03-01T00:00:00Z",
  "period_start": "2024-01-01T00:00:00Z",
  "generated_at": "2024-03-01T00:00:00Z",
  "kind": "interim",
  "report_locale": "en-CA",
  "fx": {
    "usd_cad": "1.5", "usd_twd": "30",
    "usd_cad_date": "2024-02-29", "usd_twd_date": "2024-02-29",
    "usd_cad_source": "synthetic-fixed", "usd_twd_source": "synthetic-fixed"
  }
}
```

```bash
python scripts/source_reports.py preview work/synthetic.csv \
  --workspace work/synthetic-ledger \
  --context work/context.json --bindings work/bindings.json \
  --valuation work/valuation.json --config work/parsers.json \
  --plan-directory work/reviewed-source-report
```

Review `account_review`, observed CAD/USD/TWD totals, cutoff, locale and the stated
unknown/pending scope. The returned `approval_sha256` must be copied exactly:

```bash
python scripts/source_reports.py inspect \
  --workspace work/synthetic-ledger \
  --plan-directory work/reviewed-source-report --approval-sha256 REVIEWED_SHA256
python scripts/source_reports.py confirm \
  --workspace work/synthetic-ledger \
  --plan-directory work/reviewed-source-report --approval-sha256 REVIEWED_SHA256 \
  --config work/parsers.json
```

For saved facts only, omit CSV/context/bindings but supply the explicit valuation
and a new plan directory. No source CSV means no new-activity evidence. To render
a failed committed publication, use the returned real operation ID:

```bash
python scripts/source_reports.py resume \
  --workspace work/synthetic-ledger --operation-id SAVED_OPERATION_ID
```

An ordinary failure before commit produces no holdings/valuation effects. A report
failure returns `data_committed: true` and the fixed operation ID; do not reimport
or create another valuation to guess whether it committed. Completed retry does
not need the old plan/configuration/CSV files or the original parser installation.
Keep preview bundles, reports and JSON inputs private, outside public source.

### Acceptance and remaining boundary

`test_source_publication.py` covers actual three-locale ODS/MD/PDF publication,
atomic staging, interrupted delivery, changed/corrupt evidence/settings, report-only
retry, copied-root recovery, preserved unknowns and newer-pointer protection.
The independently installed example now has a separate v2 adapter/entry point; its
real CLI preview/confirmation publishes reports with no new provider branch and
survives loss of original input/plan/configuration files. V1 remains nonbooking.
Native and Docker full backups retain source publications and old reports and verify
empty-target restoration without repricing. These are synthetic acceptance tests,
not a migrated personal instance or completed ordinary browser workflow.

## Web publication and read integration (SRC-004C3C2A)

The opt-in source-report API now binds C3C1 previews to the existing isolated Web
`preview`/`update` lifecycle, fixed approval IDs, publication registry and report
library. Its [request/recovery protocol](web-imports.md#opt-in-source-report-publication-src-004c3c2a)
is separate from data-only B2 and ordinary native imports. No provider branch is
added to publication, valuation or recovery. The independent installed v2 example
has actual API/child-worker/report/read/export acceptance too.

[Source-aware read DTOs](web-frontend.md#frozen-source-report-views) project saved
public presentation fields only. They preserve source dates/IDs/unknowns, observed
subtotal scope, same-scope history and separate estimated/actual costs. They do not
expose archive paths/raw parser fields or pretend a new provider is Wealthsimple
or Bull Bitcoin. Exports carry the same explicit scope and original report bytes.

Full empty-target restore invalidates unstarted source approvals. A proven committed
operation can finish publication/registry delivery using frozen evidence, with no
parser or repricing. Ordinary CLI/upload automatic contexts, mapping inputs and
complete daily workflow acceptance remain C3C2B; existing native gates remain.
