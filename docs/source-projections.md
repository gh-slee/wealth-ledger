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

The remainder of SRC-004C must complete:

1. Identity-bound legacy/canonical overlap reconciliation; existing wallet opening,
   full-balance anchors, linked events and explicit cost policies; frozen valuation
   and history/contribution projections with compatible original IDs/dates.
2. Shared CLI/Web valuation and publication, three-locale ODS/Markdown/PDF/chart
   parity, retry/backup/empty-restore and a synthetic third parser through real
   imports/reports without provider branches in the projection/report core.

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
