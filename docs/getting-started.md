# Start tracking a new portfolio

This guide is for a new user with no Wealth Ledger history. You can begin from the
holdings or order exports you have today; you do not need to reconstruct your whole
financial life before recording the first observation. Missing costs/contributions
stay unknown and limit related analysis.

## 1. Install and initialize an empty instance

Follow [the README Docker quick start](../README.md#self-host-with-docker-compose).
The current distribution builds from source; public prebuilt images and pull-only
Compose are planned as WEB-008. Git/Python are currently required for the audited
build-context helper; Docker builds the application dependencies and frontend.

Use a new dedicated persistent volume, initialize the owner once on the host, then
start both Web and worker services. Enter the password only in the host terminal.
The default username is `owner`; select another with the documented `init-owner
--username` option. Open the configured local origin and sign in. There is no public
registration endpoint and no initial demo portfolio in a real new installation.
A synthetic fixture shown in the README is not loaded into your instance.

Keep the volume and complete private backups. Stopping containers does not delete
data; `down -v` or deleting a volume does. For access/HTTPS and deployment limits use
[Web operations](web-operations.md); for complete recovery use [backups](web-backups.md).
Existing CLI users should instead use [copy-verified adoption](web-adoption.md).

## 2. Create a portfolio

Choose a name for an independent ledger. This creates no holdings, transactions,
source accounts or observations. New portfolios default to English report language
and actual-known BTC cost policy; review **Settings** if you want another supported
report locale. Interface language and light/dark/system appearance are separate.
No report means no saved valuation yet, not a zero investment balance.

## 3. Choose available evidence

| Input | What it supplies | What it cannot establish alone |
|---|---|---|
| Wealthsimple supported holdings CSV | Dated positions, account rows and original amounts/currency | Deposits, withdrawals, complete past transactions or investment-period returns |
| Bull Bitcoin supported orders CSV | Order lifecycle, completed purchases and funding evidence, BTC/LBTC units | Current all-wallet balance, later wallet/network fees or external contribution origin |
| Optional dated BTC total | User-reported all-wallet BTC+LBTC equivalent quantity | Actual historical cost, reason for a gap, purchases or independent on-chain verification |
| Financial records / unified cash-flow CSV | Explicit deposits/withdrawals/transfers and declared coverage | Automatically recovered earlier history or statutory contribution room |
| Other institution's export | Only usable if an installed, enabled compatible parser supports its exact format | Arbitrary bank CSV support or automatic plugin installation |

Provide either built-in CSV, both, a BTC total alone, or later prepare from saved
facts. BTC input means units such as `0.01000000 BTC`, not CAD market value. A total
requires its actual observation time with UTC offset. CSV filename/date alone does
not decide the full valuation basis; inspect the preview.

## 4. Preview, review and confirm

Open **Import & jobs**, normally with **Use parser plugins** enabled.

1. Choose the original supported CSV files. For the first observation select
   **Baseline**. Selecting or uploading a file does not book it financially.
2. If requested, set a stable source-account alias and source timezone. An alias
   identifies the source account, not a one-time filename; reuse it for later files
   from that same account. Do not reuse it for a different account. Select a saved
   source context explicitly when one exists; the app does not guess one by filename.
3. Choose **Upload & preview**. Review detected formats, source dates, source-account
   identities and destination mappings. New accounts are created by confirmed facts;
   later exports should map to the same verified account. Use **Preview reviewed
   mappings** when required. Advanced correction parents are explicit, not automatic.
4. If FX/BTC references are required, upload compatible verified reference JSON or
   explicitly enable public reference fetching. Preview itself is offline; references
   may stay pending until the workflow's approved preparation stage. Do not invent
   prices or dates to make a blocked preview pass. First Bull orders do not imply a
   zero opening balance; unknown pre-tracking holdings/costs stay unknown.
5. Confirm only a ready preview with **Confirm import & generate reports**, including
   its confirmation dialog. Changed files/mappings/settings need a new ready preview.
   No bank/broker credentials are needed and no trades are placed.
6. Keep the worker running. Wait for **Published**; data-committed/report-pending is
   not the same state. Recover a saved operation through its existing resume path
   after a publication failure; do not reimport to guess whether data committed.

Explicit native compatibility is an advanced alternative with its own opening and
canonical-data omission guards; do not toggle it simply to bypass a blocker. See
[browser workflow](web-frontend.md) and [default parser workflow](source-projections.md#default-daily-workflow).

## 5. Read, check and export

Open **Overview**, **Holdings**, **Exposure**, **History** or **Bitcoin & flows**.
Amounts use saved source/reference dates. A source carried forward is not a newly
observed balance, and a complete supplied export is not necessarily complete wealth.
CAD/USD/TWD switches affect presentation, not historical inputs or a live quote.

**Analysis reports** reads the saved full analysis and provides original PDF, ODS,
Markdown and attachments; a ZIP preserves relative chart links. CSV/JSON dataset
exports are separate from a complete private instance backup. Several report editions
at one cutoff are revisions/publications, not several broker CSV submissions.

One observation begins a history; it cannot demonstrate a trend or calculate complete
period returns. Value change includes flows and is not automatically investment gain.

## 6. Add contributions and missing earlier evidence later

Holdings differences and Bull purchase spending cannot reveal your contributions.
Use **Financial records** to preview/confirm deposits, withdrawals, transfers, source
references, actual dates and coverage. Import the supported unified cash-flow CSV
when many entries are available. Request broker statements/activity exports, preserve
originals privately, and map them to the supported schema; arbitrary native bank
activity exports are not yet automatically converted.

Starting options:

- Track forward from the first observation, with prior contributions/costs unknown.
- Backfill evidenced earlier cash flows and coverage later, without rewriting frozen
  reports or manufacturing historical balances.
- Record an evidenced pre-tracking BTC quantity via the opening form when appropriate;
  quantity does not reveal acquisition cost. A later BTC total is a balance anchor,
  not a purchase. Unexplained differences remain unresolved until dated linked events
  or corrections supply evidence.

Saving a declaration does not publish a new report. Prepare/confirm a report from
saved facts separately, selecting an explicit new cutoff and compatible references
when a later event is to be included. Read [financial records](web-financial-records.md)
for fields, balance IDs, corrections, transfer matching and flow coverage. Complete
combined period performance and Bull funding-origin classification remain planned;
current holdings and orders can still be tracked with those limitations visible.

## 7. Continue at your own cadence

Submit new exports when available: monthly, six weeks later or two months later are
all valid. Either source may be updated independently. Preserve the account alias
and reviewed mapping; overlapping orders are deduplicated by source identities.
The app retains originals and actual source dates. It does not invent missing
month-end balances or interpret missing files as no transactions. Later files are
not permission to rewrite old frozen reports.

## How parser plugins work now

Two real built-ins are `wealthsimple.holdings` and `bullbitcoin.orders`, both using
protocol v2 in the default daily flow. A parser detects a specified format and returns
normalized records/evidence; trusted core code owns account mappings, financial
validation, append-only storage, valuation, historical projections and reports.

An external author can implement a compatible Python parser, package a factory under
`wealth_ledger.source_adapters`, and supply synthetic contract/overlap/revision tests.
The host administrator reviews and pins the distribution/version/entry point, installs
it into the same API/worker runtime and explicitly enables it in private host config.
Docker users build a reviewed derived image; restoring data does not install code.
New compatible v2 formats use the same preparation/confirmation/report pipeline.
The independently installed synthetic example proves extensibility, not real support
for a third broker. The v1 SDK example is nonbooking; new financial parsers need v2.

Plugins are trusted executable Python, not a security sandbox. Uploaded CSVs cannot
install or enable code. There is no marketplace/auto-install screen or runtime LLM.
Official ETF reference-data adapters form a separate system from financial CSV
parsers. Read [adapter design](source-adapters.md) and [SDK/install guide](parser-sdk.md).
