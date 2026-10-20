# Locale contract and contribution guide

Supported locales: `en-CA` (English/Canada), `zh-TW` (Traditional Chinese/Taiwan),
`zh-CN` (Simplified Chinese/China). This is the implemented contract; publication
status is tracked separately in TODO. Reports/daily CLI use static catalogs and
Python code, with no runtime LLM, translation service or system locale.

## 1. Selection and compatibility

Precedence: `--locale` -> ignored `config/local.toml` `[reporting].locale` -> project
default. New projects use `en-CA`; legacy projects with an existing SQLite/latest
use `zh-TW`. The first normal write saves the project default. Temporary CLI overrides
do not change preferences; read-only queries/previews do not write configuration.

Aliases `en`, `zh-Hant`, `zh-Hans` are accepted after case/underscore normalization.
Ambiguous `zh` and unsupported regions such as `en-US` are rejected rather than
silently downgraded. Invalid locales fail before financial submission. Existing
BTC cost policy is preserved.

```toml
[reporting]
locale = "zh-TW"
btc_cost_policy = "actual_only"
```

```bash
python scripts/update.py /path/to/holdings.csv --locale en-CA
python scripts/update.py /path/to/orders.csv --dry-run --locale zh-TW
python scripts/btc_events.py --locale zh-CN --help
```

Operations freeze locale, catalog hash, format/render version and font hash. Retry
does not apply new preferences. Changed saved resource versions stop retry rather
than silently changing text. Older operations/ODS without locale metadata use the
legacy Traditional Chinese compatibility behavior.

## 2. Presentation and financial invariants

`i18n.py` uses `ContextVar` for per-render isolation; `formatting.py` only formats
Decimal/date values. Financial logic, parsers, event IDs, JSON/CSV headers, history
and deduplication retain their contracts.

```text
raw CSV / saved ledger / frozen analysis
                  |
       original values + stable codes
                  |
       presentation context + locale
          /          |          \
        ODS       Markdown     PDF / PNG
```

`src/wealth_ledger/locales/` contains `registry.json`, three catalogs and `legacy.json`.
Extracted messages use stable `message.<hash>`/`cli.<hash>` IDs; new messages may use
meaningful English namespaces. Wording changes must not rename keys. `legacy.json`
is a closed compatibility map for old program text, not an arbitrary translator.
Older payloads are not rewritten; presentation uses a deep copy. Templates accept
fixed named parameters; missing keys/parameters, extra parameters or cross-catalog
parameter mismatches are errors.

Source names, symbols, account labels, references and notes remain verbatim even
when they differ from the UI language. `SourceText` explicitly marks untranslated
source text. Program-owned categories/synthetic BTC labels are localized. Do not
expand compatibility logic into unrestricted search-and-replace.

## 3. Numbers, dates, fonts and formulas

The initial profiles use `.` decimals, `,` grouping and explicit financial ISO dates.
Timezone remains `America/Toronto`. CAD/USD/TWD are alternative equivalents of the
same assets; locale does not change currency, timezone or tax policy.

Explicit standard-library profiles and Decimal require no Babel/platform dependency.
These profiles do not yet need a general CLDR engine; future rules require formatter
extensions or a separately reviewed portable locked package. Display strings never
feed financial calculations. Unknown, not applicable, disabled, not calculable and
valid zero remain distinct; small nonzero values cannot format as zero.

Internal sheet IDs such as `overview`, `positions`, `btc_tracking` are English;
display names depend on locale. Cross-sheet references use escaped ID mappings.
Functions, numbers and caches retain OpenFormula machine syntax. Validators read
ODS locale metadata; older files without metadata use Traditional Chinese names.

en-CA/zh-TW use bundled Noto Sans TC; zh-CN uses Noto Sans SC. PDF font-registration
names include locale/font hashes to isolate sequential renders. PDF `/Lang`, ODS
style language and document locale agree. Manifests record catalog/font versions.
See [font notices](../assets/fonts/README.md). ODS charts remain embedded PNGs,
independent of LibreOffice.

## 4. Offline language editions and history

To change only a saved report's presentation language:

```bash
python scripts/render_report.py \
  --from-report /path/to/saved-report-bundle \
  --locale en-CA \
  --output /path/to/new-english-edition
```

Input needs `data.json`, a manifest and frozen ETF analysis. Output must be a new
directory outside the source bundle. Validate data checksum where present, cutoff,
analysis ID and financial fingerprint where present, and recheck source integrity
after generation. A legacy manifest without checksums supports only
`legacy_metadata_consistency`, not full source authentication.

No ledger reads/writes, network, quote/FX/ETF updates, observations or latest changes
occur. Output data.json is byte-identical to input. The new manifest records render
time, locale versions and source-manifest hash; analysis is explicitly frozen replay.
Normal financial updates still fetch latest published official data. Do not run an
update merely to change language.

Machine exports/audit supplements retain their schema/source language. Offline
editions do not fill missing actual costs, contributions or events or revalue history.

## 5. Additional languages and acceptance

1. Register locale, name, direction, formatting, bundled font and license. A new
   country does not imply new broker, tax or currency support.
2. Create independent UTF-8 JSON from the complete English key set. Review terms,
   named parameters and unknown/zero semantics; no runtime translation. Shared new
   keys must be added to all three existing catalogs.
3. Check `validate_catalogs()`, font cmap coverage, formulas/caches, PDF extraction/
   Lang, ODS locale, long English labels and CJK wrapping. Inspect PDF/PNG visually.
4. Render the same synthetic payload across locales. Match Decimal totals, financial
   fingerprints and formula counts; preserve original payload/SQLite. Exercise
   unknown costs, wallet gaps, zero holdings and minimum BTC quantities.
5. Reject missing keys/parameters/fonts, invalid locales and changed retry resources;
   prove offline editions cannot query the network, overwrite source or alter latest.
6. Update CI/README/manual/public allowlist. Review new catalog/font paths explicitly;
   do not allow arbitrary JSON/font downloads or private documents.

Future plugins may use provider message namespaces; the parser SDK does not implement those presentation namespaces.
Raw errors, system diagnostics and source-company names are not guaranteed translated.
Developer Git tools and translated documentation editions are separate work.
