# Financial declarations in the Web app

Open **Financial records** after signing in and selecting a portfolio. These forms
use the same Python validators, locks, database backups and append-only records as
the CLI. They do not require an LLM, wallet login, broker credentials or LibreOffice.

With canonical source batches, BTC opening/balance/event declarations use the same
verified, identity-deduplicated compatibility model as CLI queries. They do not yet
enable ordinary canonical CSV updates or new reports; those routes remain gated by
C3B/C3C. Existing frozen reports are still readable. See the
[source-aware declaration contract](source-projections.md#source-aware-btc-declarations-src-004c3a).

## Save data, then prepare a report

1. Choose a task and enter evidence with its actual dates. BTC fields mean units of
   BTC, including LBTC at 1:1 equivalence, never a CAD/USD market value.
2. Select **Preview declaration**. The worker simulates the change in an isolated
   copy, without modifying the ledger, downloading references or rendering reports.
3. Review **Your declaration** and **Result using saved ledger data**. Confirm only
   after checking the record, dates, source, amount and any linked balance.
4. Select **Confirm and save declaration**, then confirm the dialog. The worker
   backs up the database and commits the data and completion marker atomically.
   **Saved; report unchanged** means the declaration is recorded, not published.
5. Refresh records to inspect the current value and revision history. For a native
   workspace, follow
   **Prepare report** to **Import & jobs**, select **Prepare a report from saved
   data (no new CSV required)**, then preview and confirm a new report. Supply
   reference JSON if needed, or new CSVs when available.

Report generation is separate because a declaration may be recorded after the last
valuation cutoff or explain an earlier observation. The default saved cutoff is
preserved. To include a later BTC observation/event, explicitly choose a valuation
time at or after it and provide applicable reference prices/FX. Saving a declaration
never advances the cutoff, invents a month-end observation, or rewrites a frozen report.
See [imports and jobs](web-imports.md) for reference and recovery contracts.

A successful preview is bound to the current ledger/configuration fingerprint,
application version, request and upload hash. Changes require a new preview. Repeated
network submissions with the same idempotency key reuse the original job; the same
key cannot change its request. Only queued work can be cancelled through the job API.
A crashed preview is interrupted and must be rerun. A crashed data submission is
recovered as saved only when its atomic completion marker proves the commit; uncertain
states require trusted host review and are never automatically repeated.

## BTC balances, events and corrections

| Task | Required evidence | Effect |
|---|---|---|
| All-wallet BTC total | Nonnegative total, explicit observation time with UTC offset, source | Adds a stable balance ID (`B000001`, etc.); establishes a user-reported anchor |
| BTC event | Positive quantity, type, explicit event time/offset, source, unique reference | Adds an event ID (`E000002`, etc.); applies the core event sign |
| Correct, void or link a BTC record | Active record, displayed expected revision, reason and action | Appends a revision; never overwrites or deletes the original |
| Pre-tracking BTC opening quantity | Imported acquisition records, total at a reference time, declaration date, basis, confirming person | Freezes total minus net acquisitions and applicable known events; actual historical cost remains unknown |

A total alone is sufficient for a balance declaration. CSVs and an explanation are
optional. If the total differs from the ledger, the observed total is retained and
the difference remains unresolved; it is not automatically a fee, contribution,
purchase or disposal. Later add the dated event and select the **Balance to explain**
ID. The event must fall in that balance's interval. Source/reference pairs deduplicate
manual events; Bull purchases must come from order CSVs, not manual events.

Supported event types are `fee`, `sale`, `spend`, `external_out`, `external_in`,
`own_transfer` and `conversion`. Own-wallet transfers and network conversions have
zero net BTC effect; report any known fee separately. A BTC event does not supply a
missing CAD acquisition cost or establish cash-flow coverage automatically.

For corrections, select **Correct values**, **Void record**, **Link to balance**, or
**Remove balance link**. Identity changes require voiding the old record and explicitly
naming it as the replacement when adding the new one. Unlink before relinking an
already attributed event. Stale revisions, void records, same-time conflicts, invalid
links and conflicting references fail validation. Details show original/current
revisions, expected and unexplained quantities; an evidence checksum match is not
independent verification of a wallet balance.

A pre-tracking opening declaration is distinct from the explicit zero opening
assumption required by the native first Bull import. It freezes a user-attributed quantity once and
retains unknown actual cost/contributions. Later balances or CSVs do not recalculate
it. Correcting it requires the current opening revision (zero for the first declaration),
a new declared total and an explicit basis. This does not create historical purchases.
Canonical opening previews also show signed known events at the reference time,
so the total, acquisitions, events and opening quantity can be reconciled. Unknown
expected quantities, actual costs and historical contributions display as Unknown.
The optional cost proxy remains a separate, explicitly selected reporting policy.

## Contributions and other brokerage cash flows

Record actual cash movements using a positive original-currency amount and a type:
`deposit`, `withdrawal`, `transfer_in`, `transfer_out`, `income`, `fee`, or `internal`.
The type carries direction. Holdings growth and purchase spend do not establish a
contribution. Bull funding and spending the same funds on BTC are not two contributions.
These brokerage forms do not classify Bull funding origins or enable combined returns.

Choose a known brokerage account. The account table exposes the stable account ID
and masked account number needed for CSV preparation. Supply a unique flow reference
for a manual entry. Equal repeated entries deduplicate; conflicting existing flow
IDs are rejected. Automatic cash-flow corrections/voids are not supported by the
current core; do not change an ID merely to bypass a conflict.

For CAD, CAD equivalent equals the positive amount. For USD, supply either:

- a positive CAD-per-USD rate, effective FX date no later than the flow date, and
  source; or
- an explicit positive CAD settlement equivalent and its source.

If both a rate and CAD amount are supplied they must agree within core tolerance.
Transfers require a shared `transfer_id`; incomplete/mismatched pairs remain visible
and can prevent eligible period returns.

For multiple entries, choose **Import cash-flow CSV**. The original UTF-8/UTF-8-BOM
CSV is preserved byte-for-byte as upload evidence and archived by the importer.
Maximum 10 MiB and 50,000 rows; it is an explicit upload kind, separate from broker
holdings/order detection. Columns:

```csv
date,account_id,flow_type,currency,amount,flow_id,transfer_id,usd_cad,amount_cad,fx_date,fx_source
2024-02-01,a_0000000000000000,deposit,CAD,100.00,bank-reference-001,,,,,
```

The account ID above is an invented placeholder: replace it with one from your
ledger. The five required columns are `date,account_id,flow_type,currency,amount`;
other columns are optional subject to the rules above. An omitted CSV flow ID is
computed from normalized content. This is the existing unified cash-flow format,
not arbitrary bank CSV support. See [the CLI manual](user-manual.md) for obtaining
broker records and reconstructing missing earlier contribution evidence.

## Declare coverage conservatively

Enter an increasing start/end date, a scope (all tracked brokerage accounts or one
account) and `partial`, `complete`, or `no_external`. Period flow inclusion is
`(start, end]`: the start is excluded, the end included. Declare complete/no external
only after checking the actual records. No input is different from confirmed zero
activity. Each declaration is retained; later declarations do not erase earlier ones.
Coverage does not create missing flows or establish tax contribution room.

## Read-only queries and API

All routes are authenticated, owner/portfolio-scoped and private/no-store:

- `GET /api/v1/portfolios/{portfolio_id}/financial`: current opening, balances,
  events, known accounts, flows, coverage and input fingerprint; at most 1,000 rows
  per category with a truncation indicator.
- `GET /api/v1/portfolios/{portfolio_id}/financial/records/{record_id}`: wallet
  record, revisions and optional interval reconciliation.
- `POST /api/v1/portfolios/{portfolio_id}/financial/previews`: discriminated typed
  declaration (`balance`, `event`, `revision`, `opening`, `cash_flow`,
  `cash_flow_upload`, `coverage`), with `Idempotency-Key`.
- `POST /api/v1/portfolios/{portfolio_id}/financial/jobs`: `preview_id` confirmation,
  with `Idempotency-Key`. Use the ordinary job endpoints for status/cancellation.
- `POST /api/v1/portfolios/{portfolio_id}/uploads?kind=cash_flows&filename=flows.csv`:
  raw bounded cash-flow CSV, then reference its upload ID in a declaration preview.

Decimal amounts/quantities are strings. Unknown stays null, not zero. Strict schemas
reject extra fields and browser host paths. Mutations require the existing CSRF and
same-origin controls. Reading records never publishes reports or extends idle login.
The browser retains no persistent financial cache; changing portfolio/authentication
cancels in-flight requests. Complete history remains in the ledger and private backups.
