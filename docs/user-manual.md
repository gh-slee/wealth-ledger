# Wealth Ledger user manual

This describes supported operations. Reports support English, Traditional Chinese
and Simplified Chinese (section 21); code/field names are English. Every sample
quantity, amount, time and ID is synthetic and must be replaced for real use. Past
dates still require actual viewing/posting times and applicable market references.

For daily use: section 3 updates holdings; 5-8 cover contributions/backfill; 13 covers
Bull orders/purchase rates/proxies; 19 covers optional totals, ID attribution and
retry; 20 covers offline preview; 21 covers language/offline editions. See
[development](development.md) and [TODO](../TODO.md) for contributor work.

## 1. Choose a tracking baseline

A new clone has no user data. The first valid Wealthsimple CSV As of time establishes
the stock baseline and its account scope, including supported TFSA/RRSP/Non-registered
accounts. Bull-only or balance-only can establish their own scope (13/19). Original
files, SQLite, frozen FX, reports and backups remain in the local project.

Opening assets are not a new contribution: they already contain earlier funding and
investment results. Do not record the opening value again as a deposit. One valuation
cannot yield period performance; incomplete flows cannot turn value changes into
returns. BTC buys/valuations alone do not enable combined performance without origins,
transfers and coverage.

| Question | Evidence needed |
|---|---|
| Current holdings/account values | Holdings CSV and frozen FX |
| Value change since last time | Two complete holdings observations |
| Period deposits/withdrawals | Dated source-backed cash flows |
| Gain/return after contributions | Opening/closing valuations, complete flows and explicit coverage |
| Since-inception funding/performance | Earlier complete flows, reliable opening/inception values and historical support |

## 2. Install and start

Production is Python 3.12+, independent of LLMs, Codex, Node or local LibreOffice.
An OpenDocument spreadsheet reader can open ODS; generation needs no office process.
Install Python 3.12+ first, then:

```bash
git clone https://github.com/gh-slee/wealth-ledger.git
cd wealth-ledger
python3 -m venv .venv-portable
.venv-portable/bin/python -m pip install -r requirements.lock
```

Multiline examples use Bash. In PowerShell use single-line equivalents. Windows can
create the venv with py -3 -m venv .venv-portable and use
.venv-portable\Scripts\python.exe for subsequent commands:

```powershell
.venv-portable\Scripts\python.exe scripts/update.py --input C:\Downloads\holdings.csv --kind monthly
```

When moving machines, preserve private data and recreate the venv rather than copying
a platform-specific environment. First try the isolated offline
`.venv-portable/bin/python examples/demo.py --output work/demo`, which never reads
real finances or downloads prices. See [synthetic examples](../examples/README.md).

### Separate code from private portfolio data

All daily commands accept `--workspace /absolute/path/to/portfolio`. Omit it to
continue using the original checkout-local ledger; existing files are not moved.
Choose a dedicated existing empty directory for a new portfolio:

```bash
mkdir -p "$HOME/.local/share/wealth-ledger/household"
python scripts/update.py --workspace "$HOME/.local/share/wealth-ledger/household" \
  /path/to/holdings.csv --kind baseline
python scripts/update.py --workspace "$HOME/.local/share/wealth-ledger/household" \
  /path/to/orders.csv --bull-opening-file /path/to/private-opening.json --dry-run
python scripts/update.py --workspace "$HOME/.local/share/wealth-ledger/household" --list-operations
python scripts/btc_balances.py list --workspace "$HOME/.local/share/wealth-ledger/household"
python scripts/btc_events.py list --workspace "$HOME/.local/share/wealth-ledger/household"
python scripts/cash_flows.py accounts --workspace "$HOME/.local/share/wealth-ledger/household"
python scripts/crypto_opening.py show --workspace "$HOME/.local/share/wealth-ledger/household"
```

Use the same option for every later import, coverage declaration, balance/event
edit, backup-producing mutation and `--resume-operation OP-...`. It may appear
before or after a subcommand. A nonexistent directory, an unrelated nonempty
directory, duplicate options or escaping state paths fail; there is no fallback to
another ledger. Resolution and read-only queries do not initialize a new database.
An empty workspace is initialized on its first mutation. Preview remains offline
and leaves the selected workspace unchanged.

The selected directory contains `config/local.toml`, `data/`, `reports/`, `backups/`
and `work/`. Report paths, source archives, locks, operation IDs and latest pointers
belong to that portfolio. Relative **input/output arguments** are still relative
to your shell's working directory; the workspace option does not change directory.
Offline `render_report.py` uses explicit source/output paths; `--workspace` only
selects its locale default and never changes its saved input.

Bundled fonts/locales/company identities come from the installation. You do not
need to copy company aliases into a fresh workspace. Advanced overrides are
specified in [the core API](core-api.md#workspace-scoped-application-services).
Matplotlib/font caches use private writable locations, so the code checkout can
be read-only. No local LibreOffice or runtime AI is required.

Do not point the option at an unrelated directory or at another user's ledger.
A workspace path is a trusted local operator choice, not Web authorization or a
sandbox against malicious files. Keep backups of the complete workspace. Existing
private migration is **not automatic**; a formal adoption/restore UI/command remains
WEB-006 work. A new empty directory does not import the old ledger's history.

### Optional API foundation

The optional Web API supports independent portfolios, bounded source uploads,
offline preview, explicit confirmation and durable report jobs. The React interface
is planned; advanced financial records remain in this manual's CLI. See
[Web operations](web-operations.md) and the [API import/job guide](web-imports.md).
Existing CLI data is never adopted automatically.

## 3. Monthly updates

1. Export complete same-account holdings for one valuation date.
2. Export all intervening activity and verify completed deposits/withdrawals/transfers.
3. Normalize/import flows. Holdings may update first if flows are incomplete; adjusted
   returns remain unavailable.
4. After verifying every account/date, explicitly declare coverage.
5. Import holdings and inspect the new report's quality/performance status.

Formal monthly snapshot:

```bash
cd wealth-ledger
.venv-portable/bin/python scripts/update.py \
  --input ~/Downloads/holdings-report-YYYY-MM-DD.csv --kind monthly
```

Use --kind interim for extra observations. Monthly comparisons use the last complete
formal snapshot in each month; keep interim observations/old reports. Dates come
from As of, not filenames. Reimporting an existing interim as monthly does not change
its kind; choose correctly on import.

Duplicate Wealthsimple inputs do not add stock history. Bull timing is in 13.1.
Changed same-time content creates revisions; new times create observations even
with unchanged holdings. Never edit original CSV dates to fabricate history.
Regenerate after adding flows:

```bash
.venv-portable/bin/python scripts/update.py
```

No file means latest saved cutoff, not today. --snapshot-id 1 selects a saved stock
snapshot. Reports increment rNN without overwriting. reports/latest.json points to
latest successful output; supported systems also have reports/latest/ symlink.

## 4. Get Wealthsimple data

The following describes source-document workflows; UI names can change. Consult the
linked official guidance. The web interface is recommended.

### 4.1 Holdings, activity and annual contribution evidence

Open **Profile -> Documents -> Generate document**:

| Document | Selection | Tracker use |
|---|---|---|
| Holdings report (CSV) | Date/accounts | Supported holdings input |
| Custom activity statement | Period/accounts, CSV | Deposit/withdrawal/trade/transfer evidence |
| Contribution confirmation statement | Tax year/eligible registered accounts | Annual contribution cross-check |

Contribution confirmations exclude withdrawals, contributions transferred from prior
institutions and moves between same-type Wealthsimple accounts. They cannot replace
activity history. Cross-check documents instead of importing both as separate flows.
See [official custom statements](https://help.wealthsimple.com/hc/en-ca/articles/35654428540571-Request-a-custom-statement).

Web Activity can filter accounts/types/dates and show/download activity CSV. Check
unclear adjustments against statements. See [activity/running balance](https://help.wealthsimple.com/hc/en-ca/articles/39449252453019-View-your-account-activity-and-running-balance).

### 4.2 Older records

Download account CSV/PDF statements under Documents -> Statements, or select periods/
accounts under Generate document -> Bulk download monthly statements for ZIPs.
Request unavailable older records from support. See [monthly statements](https://help.wealthsimple.com/hc/en-ca/articles/360056580894-Find-your-monthly-statements).

Save original activity CSV/PDF/ZIP in data/evidence/wealthsimple/ and reference its
filename/relative path in normalized flow source fields. The importer archives the
normalized CSV, not documents named by source; retain those originals yourself.

**Current support:** native holdings CSV imports directly. Native activity conversion
is not implemented; first map it to section 6's unified flow schema. Do not pass
native activity to holdings/flow importers. The tool never logs into the broker,
syncs private accounts or retrieves credentials.

## 5. Classify contributions, withdrawals and transfers

Contributions cross the **currently tracked investment boundary**. They are distinct
from TFSA/RRSP tax contributions; CRA room is not calculated.

| Event | flow_type | Portfolio effect |
|---|---|---|
| Deposit from untracked bank/cash | deposit | External contribution |
| Withdrawal to untracked account | withdrawal | Reduces net contribution |
| Between tracked investment accounts | transfer_out + transfer_in | Cancels portfolio-wide; affects each account |
| Retained dividends/interest | income | Investment result, not new contribution |
| Internal account fees | fee | Reduces investment result, not withdrawal |
| Trades/internal FX | internal or omit | Not external funding |

Untracked Wealthsimple chequing -> TFSA is a deposit. Tracked Non-registered ->
tracked TFSA is paired transfer; tax consequences may still exist, while portfolio
funding cancels.

Assets from an untracked broker change the boundary; a document saying transfer
cannot establish internal treatment. In-kind/cross-day/multicurrency/fee cases need
scope/value review and lack specialized automatic handling. Never substitute original
cost for transfer-date value. Plan account scope/conversion before adding brokers.

## 6. Create and import cash-flow CSV

Find stable account IDs:

```bash
.venv-portable/bin/python scripts/cash_flows.py accounts
```

Output shows account_id, label and masked number. Copy examples/templates/cash_flows.csv
into a private UTF-8 input and use correct IDs. A spreadsheet is fine; preserve
text dates/transaction IDs on save.

| Field | Rule |
|---|---|
| flow_id | Strongly recommended stable DB-unique ID; prefix broker IDs with provider/account |
| date | Required YYYY-MM-DD; consistent actual completed posting date |
| account_id | Required, from accounts command |
| flow_type | Required supported English type |
| currency | Required CAD/USD only |
| amount | Positive, no grouping/currency symbol; type controls direction |
| usd_cad | CAD per USD for flow conversion; blank for CAD |
| fx_date | Required with usd_cad; not later than flow date |
| fx_source | Required USD FX/CAD-value evidence |
| amount_cad | Optional sourced CAD equivalent for USD instead of rate conversion |
| transfer_id | Required shared ID for paired legs |
| source | Recommended original broker/bank filename or relative evidence path |
| note | Optional reconciliation notes |

**Synthetic example:** replace ACCOUNT_ID_FROM_COMMAND; never import verbatim into
a real ledger:

```csv
flow_id,date,account_id,flow_type,currency,amount,source,note
example-deposit-001,2024-10-15,ACCOUNT_ID_FROM_COMMAND,deposit,CAD,2000,activity-october.csv,Example only
example-withdrawal-001,2024-10-20,ACCOUNT_ID_FROM_COMMAND,withdrawal,CAD,300,activity-october.csv,Example only
```

Net contribution is CAD 1,700. For USD 500 at a verified applicable 1.40 CAD/USD,
provide usd_cad=1.40, applicable fx_date/source: CAD 700. Sample rates are not actual
transaction evidence. Period-end FX is not the flow's rate.

Transfer legs need different accounts, same ID/date/equal CAD, one in/one out.
Unmatched transfers block performance; never alter true dates merely to match.
Import:

```bash
.venv-portable/bin/python scripts/cash_flows.py import /path/to/cash-flows.csv
```

Same raw input/stable IDs deduplicate; same ID/changed content rejects. New CSVs do
not overwrite flows. Omitted IDs are content-derived; changing date/source/note can
create a new ID, so notes are not an update mechanism. Two real identical-content
transactions need distinct IDs.

## 7. Declare period completeness

Importing and confirming completeness are separate. The program cannot know whether
you omitted an account/day. For synthetic complete May 31/June 30 observations:

```bash
.venv-portable/bin/python scripts/cash_flows.py coverage \
  --start 2024-05-31 --end 2024-06-30 --status complete
.venv-portable/bin/python scripts/update.py
```

Use actual snapshot dates only after verification. Boundary: **(start, end]**,
excluding opening day and including closing day. Earlier flows are already in opening assets.

| Status | Use | Flow-adjusted performance |
|---|---|---|
| partial | Some records but known gaps | No |
| complete | All relevant flows/transfers checked | Yes if valuation/pairing requirements pass |
| no_external | Confirmed no external flows; internal transfers still recorded | Yes if other requirements pass |
| Not declared | Not supplied/verified | No, not presumed zero |

Default declaration covers all tracked accounts. --account ACCOUNT_ID_FROM_COMMAND
limits it to one account, not portfolio completeness. Latest same-scope declaration
wins; account-specific declarations override general ones. Re-declare partial if gaps
appear. Adjacent complete months may support cumulative periods; any gap blocks it.
Account-specific no_external disallows account transfers; use complete with both legs.

Flows are date-only. Intraday snapshots/flows on both sides of cutoff need boundary
review or consistent end-of-day observations. Same-date snapshots do not support
date-weighted period returns.

## 8. Backfill contributions you did not previously track

**Start with the first reliable snapshot and record subsequent periods completely;
recover older evidence in parallel.** Full inception recovery is not required to
track next month's results.

1. Download oldest available activity/statements, including prior brokers.
2. Identify completed flows/transfers with actual dates/currency/amount/source.
   Bank evidence verifies external flows, not every inter-investment transfer.
3. Cross-check annual confirmations/RRSP receipts; they cannot supply transaction
   dates or replace withdrawal/transfer history.
4. Import verified old flows with original dates. Baseline-day/earlier records appear
   in the ledger but are not new post-baseline contributions.
5. Preserve annual totals without dates as annual-only/unverified-date evidence.
   Never invent January 1 or baseline lump-sum deposits.
6. Keep missing months/accounts, transfer-only evidence and unexplained gaps visible.
   Current value minus cost cannot reconstruct contributions.

| Evidence recovered | Reliable conclusions |
|---|---|
| Complete baseline onward | Net flows/gain/eligible returns since tracking started |
| Annual earlier contribution totals only | Verified-year totals, not date-weighted returns |
| Earlier full flows but no historical valuations | Funding history, not monthly value curves |
| Complete inception flows/transfers/reliable values | Basis for separately planned inception/backfill support |

Current performance periods use imported snapshots. Old flows alone neither move
baseline to account opening nor create inception XIRR. Pre-baseline holdings CSVs
reject. Earlier holdings/zero-asset inception/old brokers/transfers require a separate
validated migration before changing baseline.

CRA records are supporting TFSA evidence, not real-time records; cross-check institutions.
See [CRA guidance](https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/tax-free-savings-account/contributing/before.html).
The investment flow ledger is not a complete tax-contribution ledger.

## 9. Read reports

- portfolio.ods: eleven sheets for combined BTC, including BTC tracking/reconciliation;
  nine for brokerage-only. Filter, reconcile and explore formulas/embedded charts.
- report.pdf: fixed layout and embedded selected-locale fonts for reading/archiving/sharing.
- report.md: text/tables/chart links for comparison; retain charts/ when moving it.
- data.json/manifest.json: same-run analysis, provenance and validation.

CAD/USD/TWD are alternative values, not amounts to add together. Native security
costs/holdings stay CAD/USD. Saved FX freezes history.

ODS embeds same-run PNGs, regenerated by updates. They are independent of external
files/reader fonts, but cell edits do not redraw charts or expose editable series.
Use formal inputs/regeneration for updated analysis.

Report prose/findings use deterministic fixed/conditional templates, not LLM calls.
Dates/amounts/quantities/ratios and carried/mixed/reconciliation/flow caveats come
from the payload. Combined findings emphasize valuation/data limits, not new market
commentary/trade advice. Shared templates in combined.py/reporting.py feed workbook.py;
change those rather than editing one generated format.

```text
Net external contributions = deposits - withdrawals
Investment gain = closing value - opening value - net external contributions
```

CAD 100,000 -> 110,000 with deposits 6,000/no withdrawals yields gain 4,000, not a
10% investment return. Gain includes prices/dividends/internal fees/FX. Transfers
cancel portfolio-wide but affect account calculations.

Modified Dietz is date-weighted approximate period return; XIRR is annualized money-
weighted return and can be volatile over short periods. Missing data/inapplicable
denominators/ambiguous repeated flow-sign changes produce no forced result.
Holding unrealized P&L differs from tracking-period total return.

## 10. Errors, corrections and backups

| Situation | Action |
|---|---|
| Missing fields/As of | Re-export official holdings; never fabricate fields/dates |
| Missing known account | Export full scope; period analysis pauses, account is not zero |
| USD flow lacks evidence | Supply verified applicable FX or sourced CAD equivalent |
| Unpaired transfer | Verify both legs/dates/amounts without changing evidence to fit |
| Newly found transaction | Use its real stable ID, import and regenerate |
| Imported flow wrong amount/date/account | Mark period partial; no flow revise/void CLI yet, arrange backed-up revision/rebuild |
| Native activity format unsupported | Normalize flows first, not holdings import |

No reverse fake transactions for input mistakes: they distort date-weighted performance.
Do not edit SQLite/delete originals. Preserve DB/evidence before selecting a pre-import
backup or rebuilding from correct inputs. No automatic restore CLI exists yet.

Holdings/flow imports back up SQLite before changes; successful reporting backs up
afterward. Same-disk backups/ cannot replace a complete private-project backup to
another disk/secure destination. SQLite has no encryption/password. Permissions
limit access, but evidence/reports/backups remain sensitive and must stay out of public Git.

## 11. File locations and future brokers

```text
docs/user-manual.md           This manual
data/raw/holdings/YYYY/MM/    Archived original holdings inputs
data/raw/activity/YYYY/MM/    Archived normalized flow inputs
data/evidence/wealthsimple/   Broker statements saved by the user
examples/templates/cash_flows.csv Blank normalized flow template
data/db/portfolio.sqlite3    Portfolio and flow history
data/fx/                    Frozen FX and public source evidence
reports/YYYY-MM-DD_HHMM/rNN/ Immutable report editions
reports/latest.json         Latest successful report pointer
backups/                    Database backups
```

Future adapters map raw broker data to unified holdings/flows, reusing analysis/reporting.
Review actual formats/official fields for IDs/time/currency/cancellations/transfers/
accounts to avoid namespace collisions, duplicate transfers or scope-driven fake growth.
Other native holdings, automatic Wealthsimple activity conversion, cross-broker
reconciliation, tax room and automatic inception backfill remain unimplemented.
Manual normalized flows currently apply to established accounts/supported CAD/USD.

## 12. Validation scope

Independent Python environments have exercised deduplication/revisions/contributions/
cutoffs/FX/isolated second periods. Independent evaluation checks ODS caches; ODF 1.2
schemas check XML/manifests. Embedded PNG/font rendering has been inspected in an
isolated LibreOffice reader. That is development acceptance, not a runtime dependency.
Current tests never modify a real portfolio:

```bash
PYTHONPATH=src .venv-portable/bin/python -m unittest discover -s tests -v
```

## 13. Bull Bitcoin purchases and contributions

### 13.1 Export and import

Export orders from Bull Financials/order history, preferably the full history or all
activity since the last snapshot. Reimports deduplicate. Current support is CAD
Funding and purchases from CAD Balance into BTC/LBTC. Native sales, other payment
forms and fee discrepancies are unsupported and stop import rather than silently
skipping. Section 19's wallet events do not replace native Bull order conversion.

Pass either CSV or both to one command. Detection uses columns, not filenames;
order is irrelevant, with at most one file per source:

```bash
# Wealthsimple only
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv

# Bull Bitcoin only
.venv-portable/bin/python scripts/update.py /path/to/orders.csv

# Both, in either order
.venv-portable/bin/python scripts/update.py /path/to/orders.csv /path/to/holdings.csv
```

| Inputs | Cutoff/data policy |
|---|---|
| Wealthsimple only | New As of; BTC from opening/buys/events or applicable anchor; Bull marked carried |
| Bull only | Execution time rounded to minute; completed orders/BTC quote to cutoff, stocks retain snapshot quantity/native prices |
| Both | Normally stock As of; later completed Bull orders switch to execution time, retaining stock date disclosure |
| First Bull-only | BTC/Bull-cash scope; stocks not supplied; later stocks create new scope |
| No CSV/balance/explicit cutoff | Latest saved valuation, no current-date observation |
| Same unchanged Bull CSV again that day | Reuse applicable saved daily valuation without repeated points |
| Same Bull CSV on a later day | May create a current BTC valuation, not new buys/contributions |

Stock October 9 + Bull-only December 10 refreshes BTC for December 10 but keeps
October 9 stock quantities/native prices. Current applicable FX converts equivalents.
This is a mixed-date estimate, not complete December 10 wealth or investment return.
Show source dates/status separately.

Latest completed order is an event date, not wallet reconciliation/no-later-activity
proof. Missing CSVs retain known data with carried status. Bull monthly events use
actual completion dates; stock history is unchanged. Dashed total curves identify
carried/mixed data; stock-account lines use original snapshots.

Legacy --input/--bull-input remain supported. Advanced optional cutoff:

```bash
.venv-portable/bin/python scripts/update.py /path/to/orders.csv \
  --valuation-as-of 2024-12-10T22:00:00-05:00
```

Require an offset and cutoff no earlier than selected stocks; include only completed
orders by cutoff. Missing FX/quotes may need public network queries without private
uploads. Reuse frozen references for identical valuation, while normal reporting
still queries latest official ETFs. Full saved-analysis replay needs matching
--lookthrough-run-id (section 15). Brokerage-only reporting:

```bash
.venv-portable/bin/python scripts/update.py --wealthsimple-only
```

First Bull ledger import requires an explicit original zero BTC/LBTC/CAD opening
assumption. Copy config/bull-opening.example.json privately, review every field/basis,
and provide --bull-opening-file /path/to/private-bull-opening.json. Public examples
are not user declarations and clones never silently assume zero. Existing pre-Bull
holdings use section 18's separate effective opening, preserving the original
ledger declaration; do not silently change saved assumptions.

### 13.2 Quantity and valuation

Present BTC+LBTC as 1:1 BTC equivalents. Preserve original deliveries/networks; their
cumulative amounts are not current network wallet balances. Bull order CSV does not
include Bull Wallet auto/manual Liquid-to-main-chain swaps. Own-asset transfers are
not new contributions; actual fees may reduce holdings.

Without observations: fixed opening + completed deliveries + known net events.
Deduct supplied actual fees only. Do not estimate unknown fees or label quantity as
independently verified. Section 19 supports dated balances/events; never alter buy
orders to force balance agreement.

BTC uses Coinbase Exchange BTC-USD last complete one-minute close at/before cutoff,
with at most five minutes' gap, archived raw response/hash. Convert via report FX;
no future quotes/purchase-price substitution. LBTC uses 1:1 BTC valuation proxy.
CAD is a valuation currency, separate from native security tables.

Monthly average CAD/BTC = completed monthly Bull CAD spend / delivered BTC+LBTC.
It is quantity-weighted, not a simple quoted-rate average or Funding/cumulative/current
valuation calculation. No buys means n.a.; exclude unknown pre-Bull costs/later fees.
ODS uses formulas; updates recalculate.

With backfill, show effective pre-Bull opening, not obsolete zero assumptions. Each
report preserves original BTC/LBTC/CAD declaration in btc-opening-audit.json without
showing it as current main-table quantity. Original evidence/cash basis stays intact.

Bull CSV establishes completed spend/rates, not actual pre-Bull cost/contributions.
Synthetic buys of 0.01000000 for CAD 1,000 plus opening 0.00500000 with unknown cost
still leave complete actual cost/P&L unknown. Default actual_only; optional proxy is
not historical actual cost. Funding records do not reconstruct complete external
contributions. Quantity basis/fee coverage remain separate.

### Whole-holding cost and P&L: Bull average proxy

Default **actual_only** does not fill earlier unknown costs with later prices.
Opt in through CLI or ignored config/local.toml copied from local.example.toml:

```bash
.venv-portable/bin/python scripts/update.py --btc-cost-policy bull_average_proxy
```

```toml
[reporting]
btc_cost_policy = "bull_average_proxy"
```

CLI overrides TOML; absent settings use actual_only. Proxy calculation:

```text
Reference average CAD/BTC = Completed Bull purchase spend / Delivered BTC+LBTC equivalents
Estimated holding cost CAD = Current BTC equivalents * Reference average
Estimated P&L CAD = Current market value CAD - Estimated holding cost CAD
Estimated return = Estimated P&L CAD / Estimated holding cost CAD
```

Reference average uses completed Bull purchases and 1:1 deliveries only. Opening,
observations, Funding/manual fees do not change it; new completed buys do, with
reimports deduplicated.

Apply the average to **all current equivalents**, including opening/unexplained gaps.
Estimates remain available without erasing unresolved status. A total-only update
leaves average unchanged while cost/P&L scale. At equal price and positive quantity/
average, the return rate is unchanged. Below average, more quantity increases absolute
estimated loss rather than necessarily improving P&L.

Synthetic example: buy 0.06 BTC for CAD 6,000, average 100,000/BTC, valuation 120,000:

| Total BTC | Estimated cost CAD | Value CAD | Estimated P&L CAD | Rate |
|---|---:|---:|---:|---:|
| 0.08 | 8,000 | 9,600 | 1,600 | 20% |
| 0.09 | 9,000 | 10,800 | 1,800 | 20% |
| 0.07 | 7,000 | 8,400 | 1,400 | 20% |

These estimates do not supply actual opening expenditure or turn extra quantity into
funding/gain. After sales/spends/fees the proxy still uses the average but does not
compute actual remaining allocation, realized P&L or fees. No completed buys means
no estimate; zero holdings with an average gives zero cost/P&L and n.a. rate.

ODS/MD/PDF label the method; btc-cost-estimate.json saves policy/method/inputs/results.
actual_only shows no proxy numbers. Actual data.json/position/analysis book/avg_cost/
unrealized remain unchanged, without adding proxy into portfolio actual P&L. Actual
costs/flows/period performance still require original completeness conditions.

Monthly quantity charts show real completed cumulative buys, not actual month-end
wallet balances/values. New valuations may create mixed-date estimated history,
not complete synchronized formal snapshots. Original broker baseline/reports remain.

### Report data states

- **Effective quantity:** applicable ledger/opening/anchor+later events. Do not split
  unknown backfill networks or invent CAD cost/cash.
- **Quantity versus fees:** at an opening's matching reference time/quantity, label
  a user-reported unverified baseline; later estimates are opening+known buys.
  Separate formal observations/later events. Only supplied fees are included; unknown
  fees are not deducted. Missing fees do not invalidate a reported baseline or create
  another observation. Cost estimation is independent.
- **Known Bull spend:** numeric completed-order cost. Pre-Bull actual costs/contributions
  remain not supplied without original evidence.
- **Whole-holding estimates:** explicit proxy only, separate from actual fields and
  missing-cost reasons. Default actual_only adds no proxy.
- **Wallet gaps:** without dated observations, not calculated/reason; insufficient
  ledger remains insufficient. Known zero is numeric, not missing.
- **Zero cash/no-buy months:** legitimate states. Balanced Funding/spend gives zero
  CAD cash, not zero pre-Bull BTC; no monthly buys gives n.a. purchase rate.

Before publication, validate effective quantities, known/unknown costs, gaps and audit
supplements across formats. Superseded assumptions, payload mismatch or false numeric
unknowns stop publication, retaining latest success. See manifest.presentation_validation
and section 19 recovery. This does not independently verify wallets or complete history.

### 13.3 Funding treatment

Funding moves CAD into Bull; Buy spends that balance. Funding 1,000 + spending 1,000
leaves zero CAD, not 2,000 contributions/assets. Use actual user orders.

Origins matter portfolio-wide: untracked bank inflow is external contribution;
tracked Non-registered -> Bull is internal transfer; main-chain/Liquid/hot/cold own
wallet movements are internal, with fees separate.

Bull origins remain unclassified and do not automatically enter the brokerage flow
ledger. Eligible Wealthsimple account returns remain available. Combined Dietz/XIRR
are disabled pending origins, paired transfers, wallet balance/fees and coverage.
Known Funding/spend/monthly quantities/combined valuations remain usable.

### 13.4 Earlier BTC without transaction history

Use a dated opening/balance with unknown cost/contributions, not a new buy, zero
cost or invented acquisition date. Determine whether total already includes Bull.
Section 18 supports independent pre-Bull opening; original declaration/reports remain.
New scope does not become new funding/gain.

References: [Bull CSV export](https://www.bullbitcoin.com/fr/blog/launch-of-bull-bitcoin-version-2),
[Bull Wallet network transfers](https://www.bullbitcoin.com/blog/how-to-move-bitcoin-from-your-spending-wallet-to-cold-storage-privately),
[Liquid assets](https://docs.liquid.net/docs/liquid-assets),
[Coinbase candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles).

## 14. Irregular updates, missing months and backfill

Monthly is an organizational recommendation, not a prerequisite. Imports 1.5/2 months
or longer apart use actual dates/elapsed days.

| Situation | Treatment |
|---|---|
| October then December holdings | Two observations, no invented/zero November; compare actual interval, not one-month return |
| Later submit saved November CSV | Import its true As of if after baseline; history sorts by source date |
| December Bull export contains October-December | Deduplicate known orders, restore actual event months without fabricated month-end balances |
| Partial Bull export | Record supplied content; endpoints do not prove no intervening activity; export missing periods |
| Updated holdings/incomplete flows | Value changes available, flow-adjusted gain/returns unavailable |
| Different source dates | Automatic 13.1 cutoff, explicit source times and mixed-date estimate |

October-December flows must cover the whole interval, not December alone. Eligible
broker returns use real date weights after coverage confirmation. Missing months
are not zero contributions. Save original CSV/activity evidence for later recovery.

## 15. ETF company look-through

Daily commands are unchanged. Either CSV/both trigger latest official ETF queries,
even Bull-only with carried stocks. No-input regeneration retains financial cutoff
while saving a new analysis version, without another valuation observation:

```bash
.venv-portable/bin/python scripts/update.py
```

Portfolio analysis adds Top 20, paths/coverage/official dates after wrapper rankings/
matrices. All formats start with rank 1-20 by combined direct/indirect value and add
stacked direct/ETF charts. company-exposure.csv contains all resolved companies,
three currencies, three denominator weights and per-fund amounts. Ratios are fractions
(0.154=15.4%). unresolved-exposure.csv traces root/path/item/unresolved net value,
already in totals/denominators; never add it again. fund-sources.json records sources/
raw SHA-256. Use ODS/PDF for reading, CSVs for detail/audit.

### Calculation policy

- Company CAD = direct CAD across accounts + each root ETF CAD * terminal company weight.
- Principal weight = company value / all noncash investments, including self-custody
  BTC/Bitcoin ETFs/ETF cash/unresolved, excluding account cash.
- Also show total-assets-with-cash and resolved-company-equity weights separately.
- Multiply fund-of-fund paths. QQC uses CI's QQQM then Invesco US constituents;
  Vanguard uses fully paginated official delayered holdings.
- Retain source precision without rescaling to 100%. Positive undisclosed residual
  stays unknown; small overweight rounding is separate; large excess rejects.
- Bitcoin/cash/bonds are non-company. Futures/swaps/FX contracts/unidentified equities/
  funds remain unresolved. Net derivative value is not notional/delta exposure.
- Auditable company-aliases.json, security IDs and conservative names merge companies.
  ISIN/CUSIP/SEDOL/FIGI identify securities, not companies directly. ADR/share-class/
  aliases use company rules. Same ticker across markets is insufficient; ambiguous
  same-name multinational records without identifiers remain unresolved.

Renaming/nonstandard aliases/unsupported securities may need manual mapping maintenance,
not LLM guesses. Export source names/methods/per-fund amounts. Mapping edits create
new analysis; older saved runs remain replayable.

### Latest publications, dates and failures

Latest means fetched published official data, not every issuer publishing daily.
Show valuation/effective/fetch times/status separately. Current adapters: TSX VEQT,
VFV, QQC, XCHP, ZNQ, FBTC; US SMH and underlying QQQM. FBTC uses Fidelity Canada,
not its US namesake. QQC uses current manager CI, not an old Canadian Invesco source.

CI's undisclosed residual remains unknown. Vanguard monthly/Fidelity quarterly data
can be older. Adapter freshness windows flag old daily/monthly/quarterly releases;
these windows are not issuer publication promises.

Failed downloads/parsers/unsupported ETFs may still yield reports with that fund fully
unresolved and incomplete. Never fill zero or silently reuse old evidence. Missing
coverage can affect ranks. Preserve already saved public evidence for diagnosis.

This estimates stock-snapshot exposure with latest published constituents, whose
 dates may be later than snapshot. It never rewrites past values/flows/performance.
lookthrough_runs changes analysis history, not snapshots/combined_observations counts/dates.

### Offline saved analysis

Find lookthrough_run_id/lookthrough.run_id in manifest/data. Synthetic run 1 example:

```bash
.venv-portable/bin/python scripts/update.py --lookthrough-run-id 1
```

Only identical valuation time/holdings/totals can replay. New holdings/prices cannot
mix with old analysis. No issuer queries; explicitly label frozen replay, not current
latest. Required financial references must already exist; this is not offline new-CSV import.

ODS amounts/weights use formulas with frozen constituent/resolved-equity coefficients.
Value edits propagate, but order/mappings/holdings/PNGs do not download/redraw. Formal
updates regenerate consistent formats.

### Storage and extension

- data/raw/fund_holdings/<time-id>/<fund>/: immutable official evidence.
- fund_sources: parsed holdings/date/URL/SHA/parser version.
- lookthrough_runs/lookthrough_run_sources: valuation/alias fingerprints/results/links.
- Report rNN/: three formats, PNGs, companies/unresolved CSVs, sources/data/manifests.

New ETFs require explicit identity/official adapter in fund_sources.REGISTRY and
format tests. Unsupported means unresolved. Python queries public sources only,
without LLM/agent/Codex/Node/LibreOffice or private amount/account/CSV/flow uploads.

| ETF | Issuer | Automated method |
|---|---|---|
| VEQT, VFV | Vanguard | Official GraphQL, complete pagination |
| XCHP | BlackRock/iShares | Official holdings CSV |
| SMH | VanEck | Official XLSX parsed in Python |
| ZNQ | BMO | Official fund data API |
| FBTC | Fidelity Canada | Official JSON API |
| QQC | CI | Official fund page, then QQQM constituents |
| QQQM | Invesco US | Official holdings JSON |

Issuer changes need adapter maintenance. Fixed field/date/weight/identity rules run
without LLM/browser login. Failures stay unresolved. Runs are command-driven; no
scheduler, watched folder or automatic private CSV download exists yet.

## 16. Development and roadmap

Use [AGENTS.md](../AGENTS.md), [development](development.md) and [TODO](../TODO.md).
Private agent state belongs in ignored AGENTS.override.md, separate from public facts.
Inspect latest.json/manifest for status rather than creating a financial update.
Suggested convenience work: FUT-002; flow work: Bull origins/transfer pairing.
General bank/broker/exchange plugins remain planned, not arbitrary CSV support.
All production features execute without LLMs.

## 17. Sector, country and region exposure

Normal updates need no classification file. Python queries latest published official
constituents/classifications, saving raw evidence/dates/fetch/SHA. Latest may be month-end,
not today. Financial/classification dates can differ without rewriting historical performance.

### Provenance and missing data

- **GICS:** Vanguard explicitly supplies gicsSectorDescription and icbIndustryDescription,
  stored separately. Only explicit GICS is GICS, even if the fund generally uses ICB.
  BlackRock Sector/Invesco sectorName retain original unconfirmed taxonomy. No guessed ICB conversion.
- **Country/market:** official constituent fields, not revenue geography or necessarily
  uniform legal domicile across issuers. MIC/currency/ISIN prefix cannot classify
  direct stocks; US-listed TSMC ADR does not imply US classification.
- **Same-company borrowing:** prefer the component's own row, else latest same-run
  reliable company/dimension evidence. Equal-date conflicts stay unclassified. Direct
  stocks follow the same rule; retain method/date/fund/URL/status, or unknown.
- **Regions:** explicit country mapping to North America, Latin America/Caribbean,
  Europe, Asia, Middle East, Africa, Oceania in classification.py. This is a display
  policy, not issuer developed/emerging status or a complete gazetteer. Unsupported/
  non-country codes such as XE remain unclassified; additions require tests.

References: [VEQT](https://www.vanguard.ca/en/product/etf/asset-allocation/9692/vanguard-all-equity-etf-portfolio),
[VFV](https://www.vanguard.ca/en/product/etf/equity/9563/vanguard-sp-500-index-etf),
[S&P GICS](https://www.spglobal.com/spdji/en/landing/topic/gics/),
[FTSE Russell ICB](https://www.lseg.com/en/ftse-russell/industry-classification-benchmark-icb).
Changed official formats can require maintenance; failures never imply fresh cached data.

### Weights, dates and reconciliation

| Measure | Denominator/meaning |
|---|---|
| All-investment weight | All noncash CAD investments, including BTC/Bitcoin ETF/ETF cash/unresolved, excluding account cash |
| Company-equity weight | Resolved company equities including unclassified equity; n.a. for non-company |
| Equity classification coverage | Classified dimension equity / resolved equity; read with unresolved amounts |
| Classified investment weight | Classified equity / all noncash; BTC lacks corporate classification by design |
| Effective-date range | Earliest/latest adopted evidence dates, not fetch dates; detail retained |

Classified/unclassified equity, direct/ETF Bitcoin, ETF net cash, bonds, unresolved
instruments/residuals and rounding reconcile to the same total. Preserve negative
cash/rounding without forced normalization. These are decompositions, not additions
to portfolio assets. Own-row classifications may differ across issuers/dates; preserve
evidence. This is not revenue, derivative-notional/delta or FX-risk analysis.

### Reports and audit files

- ODS has full GICS/country/region tables after company exposure, CAD/USD/TWD, both
  weights, frozen coverage/dates, root coverage and coefficients. All countries remain.
- MD/PDF show sectors/regions/coverage and Top 15 countries plus remaining classified
  countries, with all unclassified/non-company categories. Full details in ODS/CSV.
- 13_sector_exposure/14_country_exposure/15_region_exposure use all-investment weights;
  gray identifies unclassified/non-company, retaining tiny negative adjustments.
- allocation-exposure.csv contains all dimensions/currencies/fractional weights:
  0.1=10%; currency equivalents are not additive.
- classification-detail.csv traces companies/paths/original GICS/ICB/issuer/country
  and assignments JSON with official dates/URLs/funds/status/method. Non-company
  reconciliation remains in allocations/unresolved-exposure.csv.

ODS formulas propagate current position CAD/FX through frozen coefficients. Saved
coverage/dates/identity/order/PNGs do not update automatically or write SQLite.
Regenerate for formal results.

### Saved history/replay

Classification is frozen in lookthrough_runs payload; refreshing analysis adds no
snapshots/orders/flows/valuation dates. Each run/new rNN is preserved. No-input refresh
retains financial valuation while updating official analysis. Same-valuation replay
retains classifications/dates and discloses no refresh. Older runs without classification
stay as saved, without today's labels. Run IDs are local: inspect latest.json/manifest
rather than copying the example's ID blindly.

## 18. Backfill pre-Bull BTC without transaction history

After confirming all-wallet BTC+LBTC includes imported Bull buys and explicitly
attributing the difference to pre-Bull holdings, declare:

**Fixed opening = declared total - completed Bull BTC+LBTC through reference cutoff.**

This is user attribution, not proof of origin/fees/acquisition dates/network split.
Quantity-only backfill leaves actual CAD cost/contributions unknown, never zero or
current-value contributions. Complete actual average/P&L remain unavailable; opt-in
proxy appears separately (13.2). Known Bull spend remains numeric.

Copy config/crypto-opening.example.json to a private file:

| Field | Meaning |
|---|---|
| reported_total_btc_equivalent | All tracked wallets/LBTC 1:1, max eight decimals |
| reference_as_of | Offset-aware completed-buy cutoff; explain in basis if report time rather than precise wallet observation |
| declared_on | Actual YYYY-MM-DD declaration date |
| balance_scope | all_wallets_btc_plus_lbtc after confirming scope |
| basis | Why the difference is pre-Bull, known/unknown coverage |
| confirmed_by | Declaration/evidence identity, never credentials |

Synthetic example files must not be imported unchanged. Import backs up, archives
JSON and appends a SQLite revision, then report:

```bash
cd wealth-ledger
.venv-portable/bin/python scripts/crypto_opening.py import /path/to/private-opening.json
.venv-portable/bin/python scripts/update.py
```

Read-only inspection:

```bash
.venv-portable/bin/python scripts/crypto_opening.py show
```

Archive: data/raw/crypto/opening/YYYY/MM/, hashed declaration; table:
crypto_opening_revisions. Preserve original Bull assumption/orders/reports. New
corrected JSON appends revision/comparison scope without rewriting evidence. Actual
acquisition dates/cost/contributions remain unknown.

Backfill creates a new scope baseline, not same-day growth or fabricated earlier
values. One new-scope point creates no history curve. Later either/both CSVs retain
fixed opening; deduplicate/accumulate orders without monthly balance resubmission
or recalculation from the old total. Earlier missing buys/sales/fees may overlap the
opening: review explicitly, not old total minus new cumulative buys. Totals below
known purchases reject and need separate sale/fee/missing-source handling.

Funding/Buy remain one money flow. Opening adds no CAD deposit/trade/cash_flow.
Inception funding still requires reliable historical trades/transfers/flows, not BTC total alone.

## 19. BTC balances, events and reconciliation

Implemented Python commands need no LLM, wallet login or LibreOffice. Start in
wealth-ledger. Replace all synthetic IDs/quantities/times; future times reject.
Input is BTC quantity, not CAD/USD value.

### 19.1 Optional total without CSV

```bash
# Optional total; time defaults to the start of this execution
.venv-portable/bin/python scripts/update.py --btc-balance 0.07990000

# Use the actual viewing timestamp when available
.venv-portable/bin/python scripts/update.py --btc-balance 0.07990000 \
  --btc-balance-as-of "2024-11-10T18:10:00-05:00"

# Either CSV, or both; balance remains optional
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv /path/to/orders.csv \
  --btc-balance 0.07990000 --btc-balance-as-of "2024-11-10T18:10:00-05:00"
```

Total covers all tracked wallets' BTC+LBTC 1:1 equivalents, max eight decimals; zero
is valid. Without --btc-balance-as-of use execution-start time and disclose that the
program did not read a wallet. --btc-balance-source "wallet display" can describe
evidence. Time/source cannot appear without quantity.

Balance-only carries stock/Bull data with dates. New totals generally create valuation
points; historical balances never move latest cutoff backward. No-input update still
uses latest saved time. Equal-time/quantity deduplicates; repeating omitted time is a
new viewing declaration. Use operation recovery for the same failed attempt (19.7).

New balance-only projects have unknown pre-observation costs/buys/contributions/
expectations. Later Bull import still needs an explicit original ledger assumption;
pre-observation buys are already included, not added twice. Orders alone do not
complete unknown history.

--valuation-as-of controls report cutoff, not viewing time. No future-data backfill.
Historical combined reports select stocks at/before cutoff or stop if unavailable.
Normally save old corrections, then regenerate the latest applicable report. New
balances cannot combine with --wealthsimple-only/--snapshot-id/--lookthrough-run-id.

### 19.2 Different total without an explanation

Accept the reported quantity for valuation, saving stable ID/time/original JSON and
initial expectation/gap. Keep it unresolved rather than inventing fees/sales/funding/
a new opening. Preserve fixed opening/orders.

Later quantity = latest applicable reported balance + later known net events.
Old observations/gaps remain; matching later observations do not settle earlier gaps.
Arithmetic agreement is not independent on-chain/wallet verification.

### 19.3 Find the ID, then explain the gap

```bash
.venv-portable/bin/python scripts/btc_balances.py list
.venv-portable/bin/python scripts/btc_balances.py show B000001
.venv-portable/bin/python scripts/btc_events.py list --balance-id B000001
```

Stable balance_id identifies one observation through revisions. Explicitly select
it rather than the latest gap. Event time must be after prior active observation
and at/before this one; first intervals use applicable ledger scope. Reject void IDs
and out-of-interval links.

Synthetic expected 0.08000000/reported 0.07990000 leaves -0.00010000. Later confirmed
pre-observation fee:

```bash
.venv-portable/bin/python scripts/btc_events.py add \
  --balance-id B000001 \
  --type fee --quantity-btc 0.00010000 \
  --occurred-at "2024-11-10T18:00:00-05:00" \
  --source "wallet manual record" --reference "fee-20241110-001"
.venv-portable/bin/python scripts/update.py
```

Expected becomes 0.07990000, gap zero, holdings still 0.07990000, not 0.07980000.
Partial explanations leave a residual; excess creates a reversed gap, not clamped
zero. Preserve first-recorded/recalculated results.

source names the origin; reference is its unique transaction/document/custom code.
Same source/reference deduplicates; changed content needs revision. Custom declarations
are permitted but are not independent verification.

### 19.4 Record an unlinked event or link an existing one

```bash
.venv-portable/bin/python scripts/btc_events.py add \
  --type fee --quantity-btc 0.00001000 \
  --occurred-at "2024-11-12T09:00:00-05:00" \
  --source "wallet manual record" --reference "fee-20241112-001"
.venv-portable/bin/python scripts/btc_events.py show E000002

# Explicit attribution of an existing event; no second economic entry
.venv-portable/bin/python scripts/btc_events.py link E000002 \
  --balance-id B000003 --expected-revision 1 --reason "Attribute to observation"
.venv-portable/bin/python scripts/btc_events.py unlink E000002 \
  --expected-revision 2 --reason "Wrong attribution"
```

Never duplicate one fee to explain another observation. Links attribute; true-time
economic effects occur once. Earlier observations/voids can change intervals; mark
invalid links for review, then inspect/correct them without silent reassignment.

Event add is data-only. Events later than the saved report need a newer valuation;
bare update does not include them automatically. CLI advises the cutoff:

```bash
.venv-portable/bin/python scripts/update.py \
  --valuation-as-of "2024-11-12T09:00:00-05:00"
```

### 19.5 Types and batch imports

| Type | Direction | Boundary |
|---|---|---|
| fee | Decrease | Actual wallet/swap fee, not fees already deducted from Bull delivery |
| sale, spend | Decrease | Principal separate from fees; no invented received cash/realized P&L |
| external_out | Decrease | Leaves scope; contribution/withdrawal treatment separate |
| external_in | Increase | Non-Bull inflow; origin/cost/flow classification separate |
| own_transfer, conversion | Zero | Own-wallet or 1:1 BTC/LBTC movement; gross quantity, separate fees |

All quantities are positive; type controls direction. Missing Bull buys belong in
CSV, not external_in. Void mistaken manual classifications before importing with
replacement evidence. Missing orders before the original opening reference cutoff
may overlap opening: review explicitly without automatic recomputation/double count.

Copy examples/templates/btc_events.csv and fill the fixed fields:

```csv
source,reference,type,occurred_at,quantity_btc,balance_id
wallet manual record,fee-20241110-001,fee,2024-11-10T18:00:00-05:00,0.00010000,B000001
```

```bash
.venv-portable/bin/python scripts/btc_events.py import /path/to/btc-events.csv
.venv-portable/bin/python scripts/update.py
```

Commit only after the full batch validates; archive raw CSV. balance_id may be blank.
YAML is unsupported. Missing sale/outflow cash counterparts or actual cost allocation
remain coverage limits/unknown actual P&L, never zero. Explicit proxy estimates may
still use current quantity but do not establish actual allocation.

### 19.6 Correct, void or replace mistaken identities

```bash
.venv-portable/bin/python scripts/btc_balances.py revise B000001 \
  --quantity-btc 0.07991000 --expected-revision 1 --reason "Corrected transcription"
.venv-portable/bin/python scripts/btc_events.py revise E000002 \
  --quantity-btc 0.00009000 --expected-revision 1 --reason "Corrected fee"
.venv-portable/bin/python scripts/btc_events.py void E000002 \
  --expected-revision 2 --reason "Duplicate of imported transaction"
```

Append revisions without deleting originals. --expected-revision must match current.
Balance time/scope and event source/reference are identities, not silently editable.
Wrong observation time uses void/replacement:

```bash
.venv-portable/bin/python scripts/btc_balances.py void B000001 \
  --expected-revision 2 --reason "Incorrect observation time"
.venv-portable/bin/python scripts/btc_balances.py add \
  --quantity-btc 0.07991000 --as-of "2024-11-10T18:20:00-05:00" \
  --source "user reported total" --replaces-balance-id B000001
.venv-portable/bin/python scripts/update.py
```

Balance add is data-only with required time. Wrong event source/reference similarly
uses void then add --replaces-event-id ORIGINAL_ID with a new reference. Never fix
transcription with reverse fake trades.

### 19.7 Data committed, report failed: recovery

```bash
.venv-portable/bin/python scripts/update.py --list-operations
.venv-portable/bin/python scripts/update.py --show-operation OPERATION_ID
.venv-portable/bin/python scripts/update.py --resume-operation OPERATION_ID
```

First two are read-only. Inputs validate in isolated staging before atomic submission;
invalid batches leave no partial formal data. Later blocking quote/analysis/report
failures identify data-saved/report-not-published, fixed cutoff and operation ID.
Retry without resubmitting CSV/balance, choosing now or recording fees again.
Completed operations return saved results. One unresolved ETF can still produce a
valid explicitly incomplete report, not necessarily a whole-operation failure.

Later revisions expire stale operations; generate from current data/desired cutoff.
Data-only commands do not require automatic reporting. Bare update does not silently
process unpublished new cutoffs and warns of pending work.

Normal retry fetches latest official ETFs while reusing applicable frozen prices/FX.
--lookthrough-run-id requires explicitly identical valuation and no new inputs.
Only fully checked formats update latest. Preserve old reports/frozen evidence.

Back up before changes. Wallet JSON/batch CSV: data/raw/crypto/wallet/YYYY/MM/;
reference overrides: data/raw/reference/YYYY/MM/. CLI and Web writers share the
stable kernel lock `work/update.guard`; never unlink a guard file. Protocol-2
`work/update.lock` metadata can be recovered only after acquiring that kernel lock.
PIDs are diagnostic, not ownership proof. Unknown legacy lock files require trusted
local review with all writers stopped; never remove an active or unproven lock.

### 19.8 Read reconciliation output

ODS/MD/PDF show IDs/time/reported/interval expected/residual/first-recorded/event
records. Display America/Toronto with offset and explicit/execution-time provenance;
DB/evidence retain UTC/original inputs. Full-ledger expectation remains separate;
a new anchor does not erase old differences.

With observations, compare cumulative Bull buys, reported balances and post-anchor
estimates without fabricated monthly balances. btc-reconciliation.csv/btc-events.csv
support audit; full revisions remain in DB/evidence/show commands. Conditional code
text reflects known fees/missing data.

**Combined investment returns remain disabled.** Scope changes, independent on-chain
verification, historical cost allocation and Bull funding/coverage remain roadmap
work. See [the reconciliation contract](btc-reconciliation-plan.md).

## 20. Offline import preview

FUT-001 is implemented and optional. Normal update validates/imports/reports; only
--dry-run previews. It writes no formal DB, raw archive, quote cache, backup,
operation or latest report and generates no ODS/MD/PDF/PNG.

### 20.1 One/two CSVs, balance-only or no input

```bash
cd wealth-ledger

# Either CSV
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv --dry-run
.venv-portable/bin/python scripts/update.py /path/to/orders.csv --dry-run

# Both sources
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv /path/to/orders.csv --dry-run

# Optional balance only; replace the example quantity and viewing time
.venv-portable/bin/python scripts/update.py --dry-run   --btc-balance 0.07990000 --btc-balance-as-of "2024-10-10T17:00:00-04:00"

# Preview regenerating the last successful valuation
.venv-portable/bin/python scripts/update.py --dry-run

# Machine-readable output on stdout
.venv-portable/bin/python scripts/update.py /path/to/orders.csv --dry-run --json
```

Replace sample quantities/times. Either/both CSVs may include a balance. Omitted
viewing time uses this preview's start time; a later formal execution has a new
start time. Supply an actual explicit timestamp to compare the same viewing event.

Existing --input/--bull-input/--kind/--snapshot-id/--wealthsimple-only/--valuation-as-of
and valid reference JSON follow existing exclusions. --dry-run cannot combine with
operation queries/retry or --lookthrough-run-id. No ETF analysis runs. --json is
preview-only; normal output is unchanged.

### 20.2 What preview checks

- Wealthsimple source date/rows/account scope/missing accounts and proposed new/revised/duplicate state.
- Bull new/revised/existing/in-file duplicates; completed economic conflicts block,
  pending orders may preview valid revisions.
- Shared cutoff/carried-source dates without manufactured months/current stock data.
- BTC observation time/expected quantity/gap/applicable cutoff quantity/unresolved
  count. Insufficient ledger means null, not zero or invented fee/flow. A balance
  later than explicit report cutoff is identified as not yet applicable.
- Exact applicable saved rates/quotes or pending missing references, without fake values.

Isolated simulation reuses real parsing, identities, imports, context and reconciliation.
Cleanup removes temporary data/new balance/snapshot/source IDs; never use simulation
IDs for attribution. Query formal IDs after a real import.

### 20.3 Status and exit codes

| JSON status | Meaning | Exit |
|---|---|---|
| checked | In-scope local inputs/applicable references passed; ETFs/reports not checked | 0 |
| pending_reference | Missing references; structural/quantity checks available, dependent work pending | 0 |
| blocked | Input/source/cutoff/quantity/corrupt-reference/concurrency issue | 2 |

blockers identifies blocking issues, checks gives individual states, pending_checks
lists unverified work. simulation_complete=false means partial simulation, such as
FX-independent checks only; it is not full success. Invalid argument combinations
still use argparse exit 2/stderr without guaranteed JSON.

Exit 0 means no in-scope blocker found, not committed data or guaranteed future
quote/report success. Automation must inspect status/pending_checks too.

### 20.4 Offline limits and real submission

No network, private login or LLM. Use exact-date/cutoff valid saved FX/BTC or explicit
applicable reference JSON, never borrowed prices from other cutoffs or invented rates.

Without new-date FX, holdings format/arithmetic/deduplication/revisions/accounts/
baseline still check. FX-dependent cash CAD checks/full simulation remain pending.
BTC quantity reconciles independently of quotes. Latest ETF/company/classification,
charts/ODS/PDF/publication remain unverified and run normally during real update.

Remove --dry-run/--json for submission. Formal workflow rereads/validates/backs up;
it does not commit the preview copy. File/DB/time changes can alter results, especially
with omitted viewing time. Failed formal reports use section 19.7 recovery.

## 21. Report languages and offline editions

Supported: en-CA English/Canada, zh-TW Traditional Chinese/Taiwan, zh-CN Simplified
Chinese/China. New installs default English; legacy ledgers retain Traditional Chinese.
Locale changes no currencies/timezone/calculations/ETF dates/cost policy.

```bash
# Normal update in Traditional Chinese
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv --locale zh-TW
# Offline preview in English
.venv-portable/bin/python scripts/update.py /path/to/orders.csv --dry-run --locale en-CA
# Simplified Chinese command help
.venv-portable/bin/python scripts/btc_events.py --locale zh-CN --help
```

For persistent preferences edit ignored config/local.toml, preserving the existing
[reporting] section rather than adding a duplicate:

```toml
[reporting]
locale = "zh-TW"
btc_cost_policy = "actual_only"
```

CLI overrides are per invocation. Aliases: en/zh-Hant/zh-Hans; ambiguous zh rejects.
Read-only/preview never saves settings; first normal mutation saves compatible default.
Retry uses frozen operation language/resources despite later preferences; incompatible
changed resources reject retry and require new reporting from current data.

**For language-only changes to an old report, use:**

```bash
.venv-portable/bin/python scripts/render_report.py \
  --from-report /path/to/saved-report-bundle \
  --locale en-CA \
  --output /path/to/new-english-edition
```

Input needs data.json/manifest/saved ETF analysis; output is a new directory outside
source. No CSV import, observation, quote/ETF download, SQLite access, latest update
or source overwrite. Preserve valuation/source dates, record render time/frozen replay,
keep data.json byte-identical and record catalog/font/source hashes. Old bundles
without checksums support metadata consistency only, not proof of unchanged originals.

ODS/MD/PDF/PNG share locale. Company/symbol/account names, notes/references remain
verbatim; JSON/CSV/audit schemas stay unchanged. Bundled fonts need no local office
application/system CJK font. Unknown never becomes zero; language changes do not fill
historical costs/contributions.

Canonical documentation is English; complete translated editions remain planned.
Developer Git tools/external raw diagnostics may remain English. See
[the locale contract](i18n-plan.md) for additional-language requirements.
