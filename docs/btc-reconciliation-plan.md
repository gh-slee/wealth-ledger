# BTC balance and event reconciliation contract

Balances, events, revisions and operation recovery are implemented. This generic
contract contains no owner's balances/baselines/acceptance history. Commands:
[manual section 19](user-manual.md#19-btc-balances-events-and-reconciliation).

Actual historical costs/contributions remain unknown without evidence. Default:
actual_only; explicit bull_average_proxy adds separate whole-holding estimates while
retaining reconciliation. Quantity basis, fee coverage and cost policy are independent;
see [section 13](user-manual.md#13-bull-bitcoin-purchases-and-contributions).

All quantities/dates/B000001/E000001 below are synthetic and must be replaced.
An old opening declaration must not become a new observation.

## 1. Scope and existing data

- Python handles production, without LLM, automated wallet login or LibreOffice.
- Totals cover all tracked wallets' BTC+LBTC at 1:1 BTC equivalents. CAD/USD market
  value cannot replace quantity. Preserve original CSV network/delivery types.
- Balance, Wealthsimple CSV and Bull CSV are independently optional.
- Fixed opening, orders, observations and events remain separate. A new observation
  cannot overwrite or recreate opening quantity.
- Preserve existing declarations/opening; never infer a precise observation time or
  convert old evidence into today's balance.
- Unknown actual costs/contributions stay unknown; proxies do not fill actual cost.
  Quantity reconciliation does not enable combined returns/Dietz/XIRR automatically.
- Initial support assumes a fixed all-wallet scope. Scope changes need a separate
  baseline, not silently adding/removing wallets through a new total.
- A new project may start with a balance only, with no invented Bull opening/history/
  cash. Before the first observation, expected quantity/cost/contributions are unknown.
  Later Bull history requires overlap handling; never add all historical buys again.

## 2. Inputs and time selection

| Inputs | Behavior |
|---|---|
| Either/both CSVs, no balance | Existing detection/deduplication/cutoff policies; anchor plus later known changes if available |
| Balance only | Save observation; carry existing stock/Bull records with original dates |
| Balance and either/both CSVs | Validate the batch, then reconcile at the same cutoff while retaining source times |
| No new input | Regenerate the latest saved valuation, without a new observation/date |

Options: --btc-balance, --btc-balance-as-of, --btc-balance-source. Source defaults to
user_reported_total; a human-readable explanation can be supplied.

- Use Decimal/integer satoshis, up to eight decimals. Zero is valid; negative, NaN,
  Infinity and excessive precision reject. Events have separate positivity rules.
- Omitted observation time uses the execution-start time once, labeled execution
  time rather than claiming a wallet read. Prefer actual viewing time.
- Observation/event times require UTC offsets; retain UTC/original inputs and display
  America/Toronto. Equal UTC instants are equal; reject naive/future times.
- Without a balance, existing CSV valuation defaults remain unchanged.
- With a balance and no explicit valuation, use the latest workflow candidate,
  latest saved valuation and observation time. New observations generally create
  valuation points; older backfills only revise applicable saved valuation without
  moving latest backward.
- Explicit --valuation-as-of controls reporting, not observation time. Never use
  later observations/completed orders/events for an earlier valuation.
- Historical balances can be saved without backfilling every month. Explicit historical
  valuation selects only saved stock snapshots at/before cutoff; no eligible stocks
  blocks the combined report rather than importing future prices into history.
- Time/source without a quantity reject. A new balance cannot combine with
  --wealthsimple-only, --snapshot-id or --lookthrough-run-id (saved-data replay).
- Balance-only does not imply synchronized full monthly sources; preserve formal/
  temporary labels, completeness and carried status.
- New valuations need applicable quotes/FX. Carried stocks retain original values;
  normal ETF updates query latest official publications. Offline replay requires
  identical financial valuation fingerprints.

## 3. IDs, queries and revisions

| Record | Stable ID | Revision |
|---|---|---|
| Balance | balance_id, e.g. B000001 | balance_revision; original content retained |
| Economic event | event_id, e.g. E000001 | event_revision; append corrections/voids |
| Reconciliation | Balance ID plus relevant observation/ledger revisions | First-recorded versus current recalculated results |
| Import/report operation | operation_id | Accepted inputs, cutoff and publication status for retry |

Never recycle/change IDs with corrections, reports or later CSVs. CLI/report exposes
balance ID/revision/time/expected quantity/gap/status. Implemented queries:

```bash
.venv-portable/bin/python scripts/btc_balances.py list
.venv-portable/bin/python scripts/btc_balances.py show B000001
.venv-portable/bin/python scripts/btc_events.py list --balance-id B000001
.venv-portable/bin/python scripts/btc_events.py show E000001
```

- Same scope/UTC time/quantity deduplicates. Different source explanation requires
  explicit supplementation/revision, not a second same-time balance.
- Same time/different quantity requires btc_balances.py revise with the original ID.
- Same quantity/new viewing time is a new observation. Repeating omitted time creates
  a new declaration; retry the same operation by ID instead.
- Balance quantity/source can revise. Time/scope are identity: void and replace if wrong.
- Events revise/void rather than reverse fake transactions. Require expected revision
  and reason to avoid overwriting later corrections.
- Event source/reference identity cannot revise. Void/replace wrong identity and
  preserve replacement links. Quantity/type/time/link changes revalidate intervals.
- Quantity corrections keep balance ID/event links. Earlier observations/voids may
  invalidate intervals: flag links for review instead of silently moving them.

## 4. Quantity and differences

For T, choose the latest active same-scope observation B at/before T:

```text
Q(T) = B.quantity + sum(known net changes where B.time < occurred_at <= T)
```

Without B, use fixed opening + completed buys + active known events. A balance-only
project has no expected pre-observation quantity.

- A balance is after events completed at its instant. Same-time events belong to
  its reconciliation, not subsequent quantity again. Uncertain ordering requires
  corrected times or an unresolved gap.
- Interval expectation: first balance uses existing opening/known events to its
  time; later balances use prior active reported quantity plus intervening changes.
- residual = reported - expected. Positive means more than expected; negative less.
  No monetary rounding tolerance: a one-satoshi gap remains visible.
- Separately retain full-ledger opening+all-known-event expectation/gap. A new anchor
  never claims previous differences were explained.
- Freeze first-recorded expectation/gap; later evidence yields recalculated results.
- Accept unexplained totals for valuation with user-reported/unresolved status.
  Do not invent fees, contributions, trades or gains.
- A matching later balance does not settle earlier unexplained intervals.
- Pre-anchor backfill recalculates gaps without deducting/adding to the reported
  total again. Post-anchor events affect subsequent quantity once.
- Negative expected holdings are contradictions, not clamped zero. Block affected
  valuation publication and preserve diagnostics.
- Ordinary observations/fees do not create scope baselines. Zero BTC retains account
  identity. Only actual scope changes create new scope baselines.

## 5. Event types, evidence and deduplication

| Type | Net BTC-equivalent effect | Boundary |
|---|---|---|
| fee | Decrease | Actual BTC-equivalent fee |
| sale | Decrease | No invented CAD proceeds/cash/realized P&L |
| spend | Decrease | Principal only; fees separate |
| external_out | Decrease | Out of tracking scope; not automatic CAD withdrawal |
| external_in | Increase | Non-Bull inflow; cost/contribution classification separate |
| own_transfer | Zero | Within-scope own wallets; moved gross quantity, fees separate |
| conversion | Zero | 1:1 BTC/LBTC network change; gross quantity, fees separate |

Every quantity_btc is positive; type supplies direction. Sale/spend/outflow quantities
exclude separately recorded fees. Do not deduct fees already reflected in Bull delivery.

Require type, quantity, offset-aware occurred_at, source and source-unique reference.
Reference may be a transaction/document ID or a user-assigned non-reused record code.

- Source is provenance, not on-chain verification. Label declarations and never call
  unverified references independently confirmed transactions.
- Same key/economic content deduplicates; changed content requires explicit event-ID
  revision. Separate equal-time/equal-amount real events need separate references.
- Equal amounts do not auto-match Bull/manual records. Missing buys belong in CSV,
  not external_in. Void a misclassified manual buy before importing Bull, with links.
- Orders before a fixed opening's reference cutoff may overlap that opening. Flag
  review; do not add blindly or recompute opening automatically. Explicitly revise
  opening evidence before claiming full-ledger reconciliation.
- Support single CLI and fixed-schema CSV batches. Archive raw batch CSV/original
  CLI JSON. Earlier YAML was illustrative; no YAML parser is planned in this version.
- Arbitrary signed adjustments and automatic discrepancy-to-fee generation are unsupported.

## 6. Attribute an explanation to a balance

**Use --balance-id explicitly; never guess the intended latest discrepancy.**

- To explain an observation, validate the supplied ID is active, same scope and
  temporally applicable.
- A genuine event may be recorded without a balance link. Apply its true time and
  later reconcile intervals without inventing a user-selected link.
- B's interval is (previous active observation, B.time]; first interval starts at
  applicable ledger scope. Do not force earlier events into the current period.
- Reject out-of-interval links and report applicable bounds/IDs; never change event
  time to fit a gap.
- Each event is one global economic record. A link is attribution, not a second
  quantity effect or a copied event for every gap.
- Existing events use btc_events.py link with event/balance ID, expected revision and
  reason; not add again. Reattribution requires explicit unlink with reason.
- Partial/over explanations retain the remaining or reversed gap; do not truncate
  or auto-settle. Zero-net transfer/conversion cannot explain a nonzero difference.
- Zero residual means known arithmetic agrees, not independent wallet verification.

## 7. Examples (replace dates and IDs)

Omitted observation time is accepted; an explicit actual viewing time is preferable:

```bash
# Balance only
.venv-portable/bin/python scripts/update.py --btc-balance 0.07990000 \
  --btc-balance-as-of "2024-11-10T18:10:00-05:00"

# Either or both CSV files plus an optional balance
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv /path/to/orders.csv \
  --btc-balance 0.07990000 --btc-balance-as-of "2024-11-10T18:10:00-05:00"
```

Synthetic first example: expected 0.08000000, reported 0.07990000, gap -0.00010000.
Assume returned ID B000001. Value the reported amount while the gap remains unresolved.
After confirming a fee:

```bash
.venv-portable/bin/python scripts/btc_events.py add \
  --balance-id B000001 \
  --type fee --quantity-btc 0.00010000 \
  --occurred-at "2024-11-10T18:00:00-05:00" \
  --source "wallet manual record" --reference "fee-20241110-001"

.venv-portable/bin/python scripts/update.py
```

The fee precedes observation: expectation becomes 0.07990000 and gap zero. Do not
deduct again to 0.07980000. The update makes a new edition at the latest saved cutoff.
A later fee without a balance link:

```bash
.venv-portable/bin/python scripts/btc_events.py add \
  --type fee --quantity-btc 0.00001000 \
  --occurred-at "2024-11-12T09:00:00-05:00" \
  --source "wallet manual record" --reference "fee-20241112-001"

.venv-portable/bin/python scripts/update.py \
  --valuation-as-of "2024-11-12T09:00:00-05:00"
```

Event add saves data only. If later than current report, CLI identifies that it is
not covered and suggests an applicable valuation time. Bare update does not become
today. New cutoffs need applicable pricing. Revision/void/batch examples:

```bash
.venv-portable/bin/python scripts/btc_balances.py revise B000001 \
  --quantity-btc 0.07991000 --expected-revision 1 --reason "Corrected transcription"
.venv-portable/bin/python scripts/btc_events.py revise E000001 \
  --quantity-btc 0.00009000 --expected-revision 1 --reason "Corrected fee amount"
.venv-portable/bin/python scripts/btc_events.py void E000001 \
  --expected-revision 2 --reason "Duplicate of imported transaction"
.venv-portable/bin/python scripts/btc_events.py import /path/to/btc-events.csv
```

Wrong observation time: data-only void/replacement, then update. Balance add requires
--as-of, avoiding an accidental current-time observation:

```bash
.venv-portable/bin/python scripts/btc_balances.py void B000001 \
  --expected-revision 2 --reason "Incorrect observation time"
.venv-portable/bin/python scripts/btc_balances.py add \
  --quantity-btc 0.07991000 --as-of "2024-11-10T18:20:00-05:00" \
  --source "user reported total" --replaces-balance-id B000001
```

Replacement targets must be voided and same scope. Events similarly support
--replaces-event-id. Replacement links are audit-only, without extra quantity effects.
Batch fields:

```csv
source,reference,type,occurred_at,quantity_btc,balance_id
wallet manual record,fee-20241110-001,fee,2024-11-10T18:00:00-05:00,0.00010000,B000001
```

The manual must cover lookup ID -> explain -> inspect residual -> regenerate, missing
Bull orders, partial explanations, multiple observations, same-time corrections,
source overlap and zero totals.

## 8. Storage, publication and failed-operation recovery

- Back up SQLite before changes/migrations. Archive dated/hashed raw CSV, CLI JSON
  and revision evidence without overwrite.
- Wallet/event/revision/link/operation tables exist, initialized on first wallet
  write; foreign keys/deduplication live in the data layer, not just CLI.
- Parse/validate all batch inputs before one atomic submission via shared transaction
  or isolated staging DB. Independent importer calls are not a batch transaction.
  Failed data stages leave no partial formal records; archived unused evidence is
  identified through operation state.
- Data commit and reporting are separate. Quote/calculation/report failure after
  commit retains data and reports data-saved/report-not-published, operation ID,
  fixed cutoff and error.
- Saved accepted IDs/revisions/cutoff support retry. Subsequent corrections expire
  an unpublished operation rather than silently replaying stale inputs.
- --resume-operation requires no new quantity/CSV or current observation time and
  does not recount events. Reject combining with new inputs.
- Normal retries fetch latest official ETFs and save evidence, while reusing applicable
  frozen prices/FX. Offline replay requires the identical valuation fingerprint.
- Publish latest only after all three formats/checks pass. Preserve old reports,
  payloads, quotes and reconciliation; later evidence creates editions, not overwrites.
- Published operation retries return saved results. Query pending/failed operations
  read-only. Bare regeneration retains latest saved cutoff and warns of pending
  work rather than silently choosing an unpublished new cutoff.

Implemented operation interfaces:

```bash
.venv-portable/bin/python scripts/update.py --list-operations
.venv-portable/bin/python scripts/update.py --show-operation OPERATION_ID
.venv-portable/bin/python scripts/update.py --resume-operation OPERATION_ID
```

The first two are read-only. Options cannot combine with each other/new input.
Data-only operations explicitly require no publication; a later update is separate.

## 9. Reports and status

ODS/MD/PDF share a payload and balance/time/scope/reported/expected/gap/explanation/
residual table. Full-ledger expectations, first-recorded results and event IDs are
additional audit detail.

- Show selected quantity, last balance time, later buys/events and source-date differences.
- Distinguish ledger estimate, user report, carried balance+events, unresolved gap,
  partial explanation, arithmetic agreement and source/link conflict. Verification
  level is separate.
- Retain old unresolved intervals. Curves may show observation effects but cannot
  call them investment gain.
- Separate Bull cumulative purchases, observations and estimated holdings. Preserve
  mixed/carried flags; all currency totals/company/sector/region denominators use
  the applicable current quantity.
- Unknown costs stay unknown. Without reliable fee/sale/outflow cost allocation,
  complete actual cost/P&L are unavailable. An explicit proxy is still an estimate,
  not actual allocation. Missing sale proceeds limit scope without invented cash.
- Conditional code templates generate text. Missing new inputs do not imply no activity.

## 10. Regression acceptance

1. Either/both CSVs, balance-only, combined inputs and no inputs obey timing/carried
   rules; no new input creates no current-date point.
2. Unexplained observations create no invented events/contributions. Zero quantity
   remains valid with retained scope.
3. Pre-anchor fees are not deducted twice; post-anchor once; same-time events precede balance.
4. Multiple observations retain old gaps; partial/over explanations recalculate
   correctly without confusing full-ledger and interval expectations.
5. Validate ID queries, wrong/void IDs, interval bounds, quantity revisions, time
   replacement and link invalidation after an earlier observation.
6. Missing Bull orders, manual duplicates, source conflicts and pre-opening-cutoff
   overlap do not double count.
7. Equal-time deduplication/conflicting revisions and same-quantity/new-time observations;
   reference-based event deduplication.
8. No future-data leakage or fake stock repricing; eight decimals, DST offsets,
   naive times, negatives and non-finite validation.
9. Atomic rollback, committed-data/report failure, fixed retry, stale operations
   and latest-pointer safety.
10. Legacy DB/reports stay readable; isolated synthetic regressions cover currency
    totals, ODS formulas/images and affected PDF layout.

Run the current suite and record actual results, not a personal ledger's test count
or report version. Financial changes require regression evidence; report changes
also need formula/structure and affected ODS/PDF visual checks.

## 11. Documentation and implementation map

Update affected README/AGENTS/TODO/manual/API/report/ODS/help/templates with contract
changes. Unimplemented parts cannot appear as runnable commands. Keep private session
and real acceptance evidence ignored.

- wallet.py: satoshis, append-only balance/events, references, interval links/reconciliation.
- operations.py: isolated atomic staging, revision fingerprints, status/retry.
- workflow.py: optional balance, one/two CSVs, no input and historical cutoffs.
- btc_balances.py/btc_events.py: read-only queries and backed-up data operations.
- wallet_reports.py: shared sections/ODS formulas/two audit CSVs; reporting.py quantity chart.
- Before the first balance, balance-only history is unknown. Later Bull history adds
  only post-anchor purchases to current estimates, not historical purchases twice.
- Explicit wallet-scope changes, independent on-chain verification and historical
  cost allocation remain outside this version. Ordinary totals cannot alter scope silently.
