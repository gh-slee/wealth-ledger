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

C3B/C3C must route ordinary CSV and saved-data workflows through the compatible
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
until C3B/C3C acceptance. Existing frozen reports remain readable and unchanged.
