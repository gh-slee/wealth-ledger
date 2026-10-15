# Wealth Ledger

A local investment tracker for **Wealthsimple holdings CSVs**, **Bull Bitcoin orders CSVs**, and optional user-reported BTC balances. Wealth Ledger preserves source evidence and financial history in SQLite, then generates ODS spreadsheets, Markdown reports, PDFs, and PNG charts.

All production features run in Python. Calculations, charts, report text, official-data downloads, and error handling are deterministic code: **no LLM, agent, Codex, Node.js, GitHub account, or local LibreOffice installation is required to use the tracker**.

Reports support **English (Canada, `en-CA`)**, **Traditional Chinese (Taiwan, `zh-TW`)**, and **Simplified Chinese (China, `zh-CN`)**. New ledgers default to English; existing ledgers without an explicit locale retain Traditional Chinese. Reports show **CAD/USD/TWD** equivalents and dates in **`America/Toronto`**. Language selection does not change currencies, timezone, financial calculations, or tax policy. Additional providers and languages remain subject to explicit implementation and testing.

**Project status:** pre-release source checkout. The supported workflows are described below; source-parser plugins and broader provider coverage are planned. Initial remote publication and clean GitHub CI acceptance are still pending.

For support, use the [contribution guide](CONTRIBUTING.md) and [security policy](SECURITY.md). Use synthetic examples when reporting a problem.

## Contents

- [What it does](#what-it-does)
- [Install](#install)
- [Try an offline synthetic example](#try-an-offline-synthetic-example)
- [Report languages](#report-languages)
- [Start your own ledger](#start-your-own-ledger)
- [Daily updates and optional BTC balances](#daily-updates-and-optional-btc-balances)
- [Preview before importing](#preview-before-importing)
- [Contributions, withdrawals, and transfers](#contributions-withdrawals-and-transfers)
- [History, dates, and missing months](#history-dates-and-missing-months)
- [BTC actual cost and optional estimate](#btc-actual-cost-and-optional-estimate)
- [Reports and official reference data](#reports-and-official-reference-data)
- [Private storage and publication protection](#private-storage-and-publication-protection)
- [Troubleshooting and recovery](#troubleshooting-and-recovery)
- [Development, tests, and optional GitHub publishing](#development-tests-and-optional-github-publishing)
- [Extensibility](#extensibility-current-adapters-and-planned-source-plugins)
- [Roadmap and documentation](#roadmap-and-documentation)
- [License](#license)

## What it does

- Keep immutable input evidence, deduplicated orders, append-only corrections, account scope, and dated observations.
- Show CAD/USD security holdings separately and group holdings by account, including supported TFSA, RRSP, and Non-registered accounts.
- Express the same portfolio in CAD, USD, and TWD, with saved rate dates and sources.
- Show native security cost/P&L, concentration, account/security matrices, allocation charts, and comparable history.
- Combine direct stocks with recursive ETF company holdings, rank the top 20 companies, and disclose unresolved exposure.
- Use official GICS, country/market classifications, and transparent geographic grouping with dates and coverage.
- Track Bull purchases/funding, original BTC/LBTC deliveries, monthly quantity-weighted CAD/BTC purchase rates, and BTC-equivalent valuation.
- Accept dated wallet-total declarations and known events, retaining unexplained differences for later reconciliation.
- Record normalized cash flows and explicit period coverage. Produce supported brokerage-period performance only when its conditions are satisfied.
- Preview inputs offline, without committing data or publishing reports.

The tool is a reporting ledger, not a broker connection or trading service. It does not log into Wealthsimple/Bull, read wallets, place orders, guess missing contributions, or independently verify on-chain ownership. Wallet reconciliation and combined brokerage+BTC period performance have separate completeness requirements.

## Install

Use **Python 3.12 or newer** and a new virtual environment:

```bash
git clone https://github.com/gh-slee/wealth-ledger.git
cd wealth-ledger
python3 -m venv .venv-portable
.venv-portable/bin/python -m pip install -r requirements.lock
```

On Windows:

```powershell
py -3 -m venv .venv-portable
.venv-portable\Scripts\python.exe -m pip install -r requirements.lock
```

For the remaining examples, replace `.venv-portable/bin/python` with `.venv-portable\Scripts\python.exe` on Windows. Multi-line commands use Bash continuations; use single-line commands in PowerShell. Rebuild the virtual environment when moving platforms rather than copying it between computers.

This release uses a source checkout and `requirements.lock`; it does not require installing a package from PyPI. SQLite and ODS packaging use Python's standard library; chart/PDF dependencies are included in the lockfile. Bundled fonts make generated chart labels and PDF text independent of the system's Chinese-font installation.

A clone contains public source, configuration examples, blank templates, and isolated synthetic fixtures. **It starts with no financial history.** Your inputs create private state under the project directory.

## Try an offline synthetic example

The demo uses invented accounts, holdings, orders, rates, and prices in an isolated temporary ledger. It does not touch your real `data/` or `reports/`, and does not fetch reference data:

```bash
.venv-portable/bin/python examples/demo.py --output work/demo
```

To see the optional BTC cost proxy:

```bash
.venv-portable/bin/python examples/demo.py --output work/demo-proxy \
  --btc-cost-policy bull_average_proxy
```

See [examples/README.md](examples/README.md) for the outputs and limitations. Synthetic rates and prices are only for that demonstration; never use them to value a real portfolio. Use the demo command rather than importing example holdings into your personal ledger.

## Report languages

Select a language for an update, preview, or command help:

```bash
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv --locale en-CA
.venv-portable/bin/python scripts/update.py /path/to/orders.csv --dry-run --locale zh-TW
.venv-portable/bin/python scripts/btc_events.py --locale zh-CN --help
```

| Language | Locale | Bundled report font |
|---|---|---|
| English (Canada) | `en-CA` | Noto Sans TC |
| Traditional Chinese (Taiwan) | `zh-TW` | Noto Sans TC |
| Simplified Chinese (China) | `zh-CN` | Noto Sans SC |

Precedence is explicit `--locale`, then ignored `config/local.toml`, then the project compatibility default. To choose a lasting preference, copy `config/local.example.toml` to `config/local.toml` and edit its existing section, preserving your cost policy:

```toml
[reporting]
locale = "zh-TW"
btc_cost_policy = "actual_only"
```

A command override applies to that invocation; it does not replace the stored preference. The first normal mutating operation persists the compatibility default. Read-only queries and previews do not write settings. Saved operations freeze their language and catalog/font metadata for safe resume. `en`, `zh-Hant`, and `zh-Hans` are aliases; ambiguous `zh` and unsupported variants are rejected.

All formats from a report use one locale, including chart labels and worksheet titles. Symbols, user account names, source company names, notes, references, JSON keys, CSV headers, and original evidence remain unchanged. Known missing values remain distinct from numeric zero. All three initial locales use explicit financial ISO dates, decimal points, comma grouping, and the same precision policy.

**To change only the language of saved data**, use the offline renderer rather than the normal updater:

```bash
.venv-portable/bin/python scripts/render_report.py \
  --from-report /path/to/saved-report-bundle \
  --locale en-CA \
  --output /path/to/new-english-edition
```

The saved bundle must contain `data.json`, a manifest, and frozen ETF analysis. Output must be a new directory outside that bundle. This command performs no downloads, imports, database writes, valuation/history additions, or `latest.json` updates. It preserves the source payload byte-for-byte and labels the saved official analysis as replayed. Legacy manifests without a data checksum provide metadata consistency checks, not full source authentication.

Daily CLI help/errors and generated reports are localized. This README is English; the detailed manual is Traditional Chinese. Developer Git/publication tooling remains English. Full documentation translation and additional locales are separate work. See the [locale contract and contributor guide](docs/i18n-plan.md).

## Start your own ledger

### Wealthsimple

Download a complete **Holdings report (CSV)** for your intended accounts. The importer requires the supported native columns and the `As of` footer, and currently accepts long CAD/USD holdings. It does not accept a screenshot, arbitrary spreadsheet, or native activity statement as a holdings input.

```bash
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv
```

The first valid snapshot becomes the baseline. Its assets already include earlier contributions and investment results: **do not also register its entire value as a new deposit**.

Account identity comes from the input, not from a hardcoded personal account list. A subsequent snapshot missing an expected account is marked incomplete, rather than assuming the missing account has zero assets.

### Bull Bitcoin

Export the supported CAD Funding/Buy Bitcoin order history. The first import must include an explicit opening declaration for the Bull orders-ledger scope:

1. Copy `config/bull-opening.example.json` to a private file.
2. Check its zero opening BTC, LBTC, and CAD assumptions against the ledger history being imported.
3. Replace the synthetic evidence text with your own declaration, then import:

```bash
.venv-portable/bin/python scripts/update.py /path/to/orders.csv \
  --bull-opening-file /path/to/private-bull-opening.json
```

Those zero assumptions are scoped to the original Bull orders ledger. If you held BTC before using Bull, keep that pre-Bull quantity separate: [manual section 18](docs/user-manual.md#18-補登使用-bull-前的-btc-持倉缺少交易史) describes an explicit opening declaration with unknown actual cost. Do not overwrite the original declaration or invent historical purchases.

The current Bull importer supports CAD Balance funding/purchases and BTC/LBTC delivery. Unsupported sale/payment types or economic conflicts stop the import; manual wallet events are a separate interface, not a way to silently bypass an unsupported Bull order.

Only Bull is enough to start a crypto-only ledger. Adding Wealthsimple later creates a new comparison scope; the added assets are not counted as investment growth.

## Daily updates and optional BTC balances

The updater identifies files by columns, not names. Either source may be supplied, or one of each in either order:

```bash
# Wealthsimple only
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv

# Bull only, after its first declared import
.venv-portable/bin/python scripts/update.py /path/to/orders.csv

# Both sources
.venv-portable/bin/python scripts/update.py /path/to/orders.csv /path/to/holdings.csv

# Extra brokerage observation
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv --kind interim

# Regenerate using the last saved valuation time
.venv-portable/bin/python scripts/update.py
```

`--kind monthly` is the default. Each source allows at most one file per update. The existing `--input` and `--bull-input` aliases remain available.

You can optionally supply the **BTC quantity** across all tracked wallets, including LBTC at a 1:1 equivalent, with either/both CSVs or with no CSV:

```bash
# Synthetic example: replace with the actual quantity and viewing timestamp
.venv-portable/bin/python scripts/update.py --btc-balance 0.02000000 \
  --btc-balance-as-of "2024-06-30T18:00:00-04:00" \
  --btc-balance-source "wallet display"
```

Use quantity, not CAD/USD market value. At most eight decimals are accepted, including valid zero. If viewing time is omitted, execution time is saved as a **user declaration**, not a program-read wallet balance.

Without a new balance, the tool uses the latest applicable observation plus later known changes; when no observation exists, it uses the applicable fixed opening and known ledger. Unexplained quantity differences remain visible. They do not become automatic fees, contributions, or replacement opening holdings.

Use stable IDs to add explanations, revise a transcription error, or void a duplicate. Observation-before fees are not deducted a second time. Full commands and examples are in [manual section 19](docs/user-manual.md#19-btc-餘額異動與差額對帳).

## Preview before importing

Normal updates validate, import, and generate reports. **`--dry-run` is optional**: it previews changes in an isolated disposable project, remains offline, and leaves the real database, archives, reference caches, backups, operations, reports, and latest pointer untouched.

```bash
.venv-portable/bin/python scripts/update.py /path/to/holdings.csv --dry-run
.venv-portable/bin/python scripts/update.py /path/to/orders.csv /path/to/holdings.csv --dry-run
.venv-portable/bin/python scripts/update.py --dry-run --json
```

Preview shows recognized sources/dates, planned new/duplicate/revised records, account coverage, carried sources, candidate cutoff, BTC expected/reported quantities, and blockers. It never invents FX or prices, retains provisional IDs, downloads latest ETF data, or generates reports.

| JSON status | Meaning | Exit code |
|---|---|---:|
| `checked` | In-scope local checks passed; latest ETF/report publication remain unvalidated | 0 |
| `pending_reference` | Applicable rates/prices are missing; completed structural/quantity checks are still available | 0 |
| `blocked` | Invalid input, conflict, time/quantity issue, corrupted reference, or concurrent update needs attention | 2 |

Read `pending_checks` and `simulation_complete` as well as the exit code. Code 0 does not guarantee a subsequent market download or report publication will succeed. Formal execution rechecks inputs rather than committing preview state. If viewing time is omitted, preview and later execution have different timestamps; provide the actual viewing time when comparing the same observation.

See [manual section 20](docs/user-manual.md#20-匯入預覽預檢fut-001) for restrictions and automation details.

## Contributions, withdrawals, and transfers

Holdings CSVs show assets, not complete contributions. Purchase spend and changing account value cannot establish net external cash flow.

1. Save the broker's native activity/statement evidence locally.
2. Obtain stable account IDs with the command below.
3. Copy `examples/templates/cash_flows.csv` to a private input and normalize verified flows.
4. Import it, then explicitly declare the period's coverage after checking all relevant accounts.

```bash
.venv-portable/bin/python scripts/cash_flows.py accounts
.venv-portable/bin/python scripts/cash_flows.py import /path/to/private-cash-flows.csv

# Synthetic coverage interval; replace only after verifying your actual records
.venv-portable/bin/python scripts/cash_flows.py coverage \
  --start 2024-05-31 --end 2024-06-30 --status complete
.venv-portable/bin/python scripts/update.py
```

Normalized flows use positive amounts and explicit `deposit`, `withdrawal`, `transfer_in`, `transfer_out`, `income`, `fee`, or `internal` types. A transfer between tracked accounts uses paired legs and one transfer ID; its effects cancel for the overall portfolio. A transfer from outside the tracked boundary can be external input, regardless of the broker's label.

`partial`, `complete`, and `no_external` coverage are explicit declarations, not inferred from missing files. Period boundaries are `(start, end]`, and date-only flows cannot resolve intraday timing. USD flows require a verified transaction-time CAD equivalent or FX source. Income retained inside the account is investment activity, not a new contribution.

Bull Funding adds CAD to its balance and Buy spends that same money; do not count both as contributions. Bull funding origins and transfers into the combined portfolio are not yet fully classified, so **combined brokerage+BTC Modified Dietz/XIRR are not enabled**. Eligible brokerage-only periods can be analyzed when estimates, coverage, scope, and transfers satisfy the existing contract.

Historical records may be normalized when reliable evidence exists. An annual total without transaction dates does not justify a made-up deposit date. Missing pre-tracking cost/contributions remain unknown. See [manual sections 5–8](docs/user-manual.md#5-供款提款與轉移怎麼分類).

## History, dates, and missing months

| Update | Timing and interpretation |
|---|---|
| Wealthsimple only | Use CSV `As of`; saved crypto data can be carried forward with original source dates |
| Bull only | Use execution time for BTC valuation; saved brokerage quantities/native prices retain their older timestamp |
| Both | Normally use holdings time; later completed Bull orders can move the combined valuation to execution time |
| New balance only | Record that observation; carry other sources with their dates and use the applicable cutoff |
| No new input | Regenerate at the last saved valuation time, without a new observation for today |

Monthly is an organizing convention, not a requirement to upload on a fixed date. If you submit after six weeks or two months, comparisons use the actual observed dates. Missing months are not interpolated, set to zero, or declared to have no contributions.

A cumulative Bull export is deduplicated by order identity and can restore dated purchase events. It cannot prove a missing month-end wallet balance. Repeated unchanged Bull data can still create a later price valuation on a later day without adding a transaction. Stock history retains real brokerage snapshots; mixed/carried-source totals are marked estimates.

Account additions, pre-Bull opening changes, and other scope changes use separate comparison baselines. Missing accounts do not become zero; adding a scope is not investment gain. Rates and BTC prices used for financial observations are frozen. Latest ETF lookthrough may have a different effective date and is a separate saved analysis.

For an explicit cutoff, use `--valuation-as-of` with a timezone-aware timestamp. Historical brokerage replay uses a saved snapshot ID. New CSVs/balances cannot be mixed with a saved `--lookthrough-run-id`; an ETF replay requires an identical valuation fingerprint.

## BTC actual cost and optional estimate

The public default is **`actual_only`**. Known Bull purchase spend remains numeric. Missing pre-Bull acquisition cost, unknown quantity adjustments, and unavailable disposal allocation prevent claims of complete actual cost/P&L; unknown fields are not zero.

The optional **`bull_average_proxy`** reports a reference-cost estimate:

```text
Reference CAD/BTC = Completed Bull CAD purchase spend / Delivered BTC+LBTC equivalents
Estimated cost CAD = Current BTC-equivalent quantity * Reference CAD/BTC
Estimated P&L CAD = Current market value CAD - Estimated cost CAD
Estimated return = Estimated P&L CAD / Estimated cost CAD
```

This proxy applies to **all current BTC-equivalent quantity**, including fixed opening quantity and unexplained differences. It does not reconstruct historical acquisition costs or settle reconciliation gaps. A new balance or fee changes quantity, not the reference average; new completed purchases can change the weighted average. Without completed Bull buys, no proxy average is available. With a valid average and zero holdings, estimated cost/P&L are zero and the rate is not applicable.

Choose it explicitly for a report:

```bash
.venv-portable/bin/python scripts/update.py --btc-cost-policy bull_average_proxy
```

Or copy `config/local.example.toml` to ignored `config/local.toml` and set:

```toml
[reporting]
btc_cost_policy = "bull_average_proxy"
```

The CLI override takes precedence over local configuration; absent a setting, the policy is `actual_only`. Actual ledger fields, contributions, realized P&L, and whole-portfolio actual returns are unaffected. Proxy text and its `btc-cost-estimate.json` attachment state the policy and assumptions. It is neither tax ACB nor a substitute for actual transaction history.

## Reports and official reference data

Successful output is saved as a new edition under `reports/YYYY-MM-DD_HHMM/rNN/`. Older editions are retained, and `reports/latest.json` points to the latest successfully published report:

| Artifact | Purpose |
|---|---|
| `portfolio.ods` | Formula-based totals/tables with embedded PNG charts and font licensing |
| `report.md` | Selected-language analysis, tables, and relative chart links |
| `report.pdf` | Fixed layout with embedded fonts and charts |
| `charts/` | Same-run standalone PNGs |
| `data.json`, `manifest.json` | Shared calculations, timestamps, sources, policies, and validation |
| `company-exposure.csv`, `unresolved-exposure.csv` | Full company lookthrough and unresolved reconciliation |
| `allocation-exposure.csv`, `classification-detail.csv` | Classification amounts, methods, dates, and evidence |
| BTC audit/estimate/reconciliation exports | Applicable opening evidence, optional proxy method, balances, and events |

Brokerage reports have nine worksheets; crypto-inclusive reports also have Bitcoin tracking and BTC reconciliation sheets. Actual chart/formula/page counts depend on available data. ODS formulas can be used for local what-if calculations, but edits do not write back to SQLite, re-download ETF data, reorder saved rankings, or redraw static charts. Regenerate for an authoritative consistent report.

CAD, USD, and TWD totals are three representations of the same assets, **not three balances to add together**. Original CAD/USD holdings remain separate. Unrealized holding P&L is not a period/annualized return.

FX comes from Bank of Canada CAD per USD and Taiwan central-bank TWD per USD references. BTC uses a saved Coinbase BTC-USD completed one-minute candle applicable to the cutoff, then converts using saved FX. Missing/invalid references stop dependent valuation; user-supplied verified reference JSON is supported. Example reference files are synthetic.

Normal report analysis queries the latest officially published holdings using these supported adapters:

| Fund | Official source | Adapter |
|---|---|---|
| TSX VEQT, VFV | Vanguard Canada | Official paginated holdings interface |
| TSX XCHP | BlackRock/iShares | Official holdings CSV |
| US SMH | VanEck | Official holdings workbook |
| TSX ZNQ | BMO | Official fund data interface |
| TSX FBTC | Fidelity Canada | Official fund data interface |
| TSX QQC | CI | Official fund page, including QQQM position |
| US QQQM | Invesco US | Official holdings interface |

“Latest” means the latest data published by that issuer, not necessarily today's holdings. Save effective dates, download time, raw evidence, SHA-256, parser versions, and analysis fingerprints. New/unsupported funds, stale publications, download failures, missing classifications, and rounding discrepancies are visible; partial holdings are never silently normalized to 100% or filled by an LLM.

Primary company percentages use all noncash investment value, including BTC. BTC/cash/bonds/unknowns cannot be assigned to a company. GICS is only accepted from an explicit official GICS field. Country classification is not revenue geography or listing currency; region is a disclosed grouping.

Normal no-input regeneration preserves financial valuation time but still requests latest official ETF data. Full replay of a saved official analysis is explicit:

```bash
# Replace 1 with the saved analysis ID for the identical valuation
.venv-portable/bin/python scripts/update.py --lookthrough-run-id 1
```

A replay is labeled frozen and does not claim fresh issuer data. It needs the matching saved ledger, rates, prices, and evidence; it is not an offline import mode for arbitrary new dates.

## Private storage and publication protection

```text
src/wealth_ledger/            Production ledger, calculations, reports
scripts/                     User commands and separate developer tools
docs/                        Public usage/development contracts
examples/                    Isolated synthetic demonstration
examples/templates/          Blank normalized cash-flow/BTC-event headers
config/*.example.*           Public configuration examples
config/local.toml            Ignored local locale and cost policy
config/publish.local.toml    Ignored developer publication authorization
data/                        Private SQLite, inputs, evidence, FX/prices
reports/                     Private immutable report editions
backups/                     Private SQLite recovery copies
private/                     Private notes/local agent guidance
work/                        Private build and QA artifacts
```

SQLite is unencrypted and has no database password. Protect the local project and backups using appropriate filesystem/backup controls. Same-disk SQLite backups do not replace a separate backup of the complete private project state.

The tracker downloads public reference data without uploading financial inputs. It does not authenticate with a broker/wallet. Reports can remain sensitive despite account masking, so publishing a report is a separate deliberate choice.

`.gitignore` excludes private state, but it does **not** remove already tracked files or financial text copied into otherwise-public files. The developer publication workflow uses a curated allowlist, staged/outgoing-content checks, and explicit local authorization. **Normal CSV imports and report generation never commit or push to GitHub.** Read [publishing guidance](docs/publishing.md) before using a checkout that also contains personal data. A local public-file check can be run separately:

```bash
.venv-portable/bin/python scripts/check_publication.py --worktree
```

Developer publication additionally checks the staged tree and outgoing history; the worktree check alone is not approval to push.

## Troubleshooting and recovery

| Symptom | Action |
|---|---|
| CSV not recognized | Obtain the supported native export; check required columns/footer, not its filename |
| First Bull import lacks a declaration | Supply your verified private opening JSON; do not borrow the synthetic example assumptions |
| Missing applicable FX/price | Check network/reference sources or provide verified cutoff-specific JSON; preview may report `pending_reference` |
| Issuer format changed/unsupported ETF | Inspect unresolved coverage/evidence; maintain the adapter with format tests |
| BTC total differs | Record the dated quantity, retain the difference, then add verified events using the specific balance ID |
| Missing account/flow coverage | Restore the missing input or keep the period partial; do not force zero/completeness |
| Reports saved, but charts look stale after ODS edits | Run the updater; embedded PNGs do not redraw from spreadsheet edits |
| Data committed but report failed | Query/resume the saved operation, without submitting the same balance again with a new implicit time |

```bash
.venv-portable/bin/python scripts/update.py --list-operations
.venv-portable/bin/python scripts/update.py --show-operation OPERATION_ID
.venv-portable/bin/python scripts/update.py --resume-operation OPERATION_ID
```

Query commands are read-only. Resume uses the accepted data and saved cutoff; later input revisions can make an unpublished operation stale. Prior successful reports remain available. Do not directly edit SQLite, delete raw archives, change source dates, or add fake reverse flows to repair an input mistake.

Use `--help` for each command and the [manual](docs/user-manual.md) for stable IDs, interval linkage, replacement, revision, void, and recovery examples. For security reports, follow [SECURITY.md](SECURITY.md) and avoid attaching personal data to public issues.

## Development, tests, and optional GitHub publishing

```bash
PYTHONPATH=src .venv-portable/bin/python -m unittest discover -s tests -v
```

Tests use isolated synthetic ledgers and public-format fixtures; they do not read a real portfolio. CI runs tests and an offline demo from a clean environment. ODS is written directly as OpenDocument 1.2, with cached formula results and embedded PNGs. Office software may be used for development visual checks but is never a production dependency.

Read [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md), [development guidance](docs/development.md), and [TODO.md](TODO.md). Implement features as reusable Python. LLM assistance during development is optional and must not become a runtime requirement or replace deterministic financial rules.

Developer publishing is separate from the tracker. The optional guarded workflow checks explicitly staged public files and outgoing commits, tests the public version, and requires ignored local authorization plus GitHub authentication before execution. It uses a **feature branch and PR**, and does not auto-merge `main`. GitHub CLI is only needed for that developer workflow; ordinary users do not need it. See [docs/publishing.md](docs/publishing.md) for concrete setup and commands.

## Extensibility: current adapters and planned source plugins

The code is partly modular today: official ETF providers use a registry, while financial CSV detection recognizes the two implemented Wealthsimple/Bull formats. It is **not yet a general installable broker/bank/exchange plugin system**.

A planned trusted-Python source-adapter registry will separate detection, normalization, ledger submission, and reports. Proposed kinds are `holdings`, `cash_flows`, and `crypto_transactions`, with explicit canonical records, source/account namespaces, stable transaction IDs, timezone/currency rules, corrections, and scope changes. Detectors must reject ambiguous matches rather than choose a provider by guesswork. Each adapter needs synthetic fixtures, duplicate/revision tests, transfer-boundary tests, and documented supported export versions.

Future bank statements can provide contribution/withdrawal evidence across the tracked investment boundary; importing a bank file must not silently add every bank balance to investment assets. Additional crypto exchanges require verified transaction/fee types and cost/quantity coverage, not a filename-based shortcut. Adapters will be trusted installed Python code; the tracker must not execute arbitrary code supplied in an uploaded CSV or resolve formats using an LLM.

Users will be able to implement their own trusted parsers against a versioned protocol, run contract tests, and register/install the parser through an explicit loader or package entry point. New parsers should not require changes to the ledger or report modules. API compatibility, namespaces, duplicate provider IDs, and detector ambiguity must be validated by the core.

This is a roadmap direction, not an available SDK/command or a claim that additional providers already work. See the [source-adapter design](docs/source-adapters.md) and source-adapter items in [TODO.md](TODO.md).

## Roadmap and documentation

The [TODO tracker](TODO.md) is the source for pending work. Offline preview (FUT-001) is available; unified status queries, historical export/index, ETF overlap, and market-value decomposition remain planned. Other work includes Bull funding origins/transfers, native activity conversion, cash-flow revisions/restore, combined performance, and additional broker adapters.

- [Traditional Chinese user manual](docs/user-manual.md)
- [Core API and data contracts](docs/core-api.md)
- [Report specification](docs/report-spec.md)
- [ODS implementation](docs/workbook.md)
- [Languages and locale contributor guide](docs/i18n-plan.md)
- [BTC reconciliation contract](docs/btc-reconciliation-plan.md)
- [Source-adapter/plugin roadmap](docs/source-adapters.md)
- [Development guidance](docs/development.md)
- [Public publishing workflow](docs/publishing.md)

## License

Project code is licensed under [MIT](LICENSE). Bundled fonts and third-party materials retain their own licenses; see `assets/fonts/` and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
