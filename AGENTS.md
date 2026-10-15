# Wealth Ledger development instructions

Scope: this repository. These instructions guide development; the production tracker does not read them and never requires an LLM.

## Start here

- Read `README.md`, `docs/development.md`, and `TODO.md`, then the relevant usage, API, reporting, and reconciliation contracts.
- If present, optionally read ignored `private/AGENTS.local.md` and `private/session-handoff.md` for local preferences and operational context. They are private and must never be staged, published, copied into public documentation, or used as production defaults.
- Follow the current user's language preference. Use English for code, identifiers, comments, and machine-readable contracts. Product reports support en-CA, zh-TW, and zh-CN; product settings do not prescribe contributor conversation language.
- A TODO entry does not authorize implementing it. Follow the current task and preserve explicit reporting/configuration policies.
- For local state, read `reports/latest.json` and its manifest without running an update. Do not create report or valuation revisions merely to inspect a project.

## Portable, deterministic production

- Use portable Python 3.12+. Do not add runtime dependencies on LLMs, agents, Codex, Node.js, local LibreOffice, or a particular user's paths/environment.
- Data downloads, parsing, calculations, report text, charts, and failure handling must be reusable code. Report prose is deterministic template output, not runtime AI generation.
- Support documented Wealthsimple/Bull formats and explicit CAD/USD/TWD, `America/Toronto`, and the documented three-locale reporting contract. Do not claim arbitrary broker/currency/language support without implementation and tests.
- Never hardcode a user's accounts, wallet quantities, baseline dates, acquisition cost, source documents, credentials, or chosen proxy policy. Keep user configuration ignored and explicit; use synthetic examples publicly.
- Financial calculations use `Decimal`; BTC uses eight-decimal satoshi precision. Unknown values remain unknown, while valid zero values remain numeric zero.

## Localization invariants

- Use shared static catalogs and context-scoped presentation. New ledgers default to en-CA; legacy ledgers preserve zh-TW. Locale changes must not alter financial identities, raw evidence, saved payloads, or history.
- Preserve source/user names, notes, and references verbatim; localize program-owned text only. Unknown financial values must remain distinct from zero in every language.
- Use stable sheet IDs and generated quoted references, localized bundled fonts, and locale-aware presentation checks. New keys require all supported catalogs with identical named parameters.
- Use scripts/render_report.py for language-only offline editions; do not run normal update just to switch language. See docs/i18n-plan.md for contracts and contribution checks.

## Ledger and input invariants

- `scripts/update.py` accepts either supported CSV, one of each, optional BTC quantity, or no new input. Identify sources by content and preserve documented timing/carried-source behavior.
- `--dry-run` must be entirely offline and use a disposable isolated project. It cannot modify the real database, archives, prices/FX caches, backups, operations, analysis runs, or latest report. Do not expose new temporary IDs, invent references, or commit its simulation results.
- Preserve raw source evidence, checksums, immutable financial history, and report editions. Corrections append revisions; never mutate old inputs or introduce reverse fake transactions to fix transcription mistakes.
- Missing files/months do not establish no activity. Retain source dates, completeness, and scope. Do not manufacture observations or count scope expansion as investment growth.
- Contributions require real cash-flow evidence and explicit coverage. Holdings changes and purchase spend are not contributions. Bull Funding and Buy use the same money; tracked-account transfers cancel at the portfolio boundary.
- BTC+LBTC use 1:1 BTC-equivalent presentation while preserving delivery types. Keep opening declarations, orders, observations, and events distinct.
- A pre-Bull opening declaration fixes quantity once from explicit user attribution. Imports do not automatically recompute it; original assumptions remain auditable.
- Wallet balances/events require stable IDs, unique source references, explicit revision/void reasons, and validated intervals. An observed balance anchors later known changes; events included before the observation are not deducted again.
- Unexplained differences stay unresolved. A later matching observation does not erase older gaps, and quantity agreement is not independent verification.
- Mutating CLI operations use backup, project lock, and atomic data submission. Data commit and report publication are separate; failures resume the saved operation/cutoff rather than repeating an unspecified-time balance.

## BTC reporting policies

- `actual_only` is the public default. Do not fill unknown actual historical cost, contributions, realized P&L, or complete actual holding P&L with a proxy or zero.
- `bull_average_proxy` is explicit opt-in via ignored local configuration or CLI. Reference average is completed Bull CAD spend divided by delivered BTC+LBTC equivalents; estimated cost is current quantity times that average. Estimated P&L uses current market value. It includes opening quantity and unexplained differences while preserving reconciliation and actual unknown fields.
- A balance/event does not change the reference average; completed purchases can. No purchases means no average. With an average and zero holdings, estimated cost/P&L are zero and the rate is not applicable.
- Quantity source, cost policy, and event/fee coverage are independent labels. An opening declaration can describe its own reference-time total, but cannot create a new observation. Never guess or deduct unknown fees.

## Official ETF analysis and reports

- Normal analysis fetches latest published official issuer data through code. Preserve effective date, fetch time, evidence, SHA-256, and parser version. Unsupported/failed portions remain unresolved; stale caches cannot masquerade as newly verified data.
- New adapters/format changes need isolated format tests. Company identities, recursion, ADR/share classes, and unresolved/rounding components remain auditable.
- Top-20 exposure combines direct and recursive ETF equities. Its principal denominator is all noncash investments, including BTC. Do not normalize partial holdings to fabricate full coverage.
- Sector uses explicit official GICS. Preserve ICB/unconfirmed issuer labels separately. Country uses official classifications, not MIC/currency/ISIN guesses; region is transparent grouping, not revenue geography.
- CAD/USD/TWD are alternative equivalents. Freeze historical FX/prices; do not revalue saved history using today's references.
- ODS directly writes standard ODF with formulas, numeric caches, embedded PNGs, and font licensing. Do not introduce hand-written native charts in place of the verified image approach. Development readers cannot become runtime dependencies.
- All formats use shared payload/templates. Effective state belongs in everyday reports; superseded assumptions belong in audit attachments/history. Presentation checks must pass before `latest` publication.
- `--lookthrough-run-id` replays saved analysis only for identical financial fingerprints and cannot mix with new CSVs/balances.

## Testing, documentation, and publishing

- Use a clean virtual environment and `PYTHONPATH=src python -m unittest discover -s tests -v`. Tests use synthetic inputs/public-format fixtures and isolated projects, never a real portfolio.
- Verify financial identities and relevant regression scenarios. Report changes require formula/cache and affected ODS/PDF checks; documentation-only work does not regenerate financial reports.
- Update TODO and affected public contracts with actual behavior/verification. Keep local handoffs under ignored `private/`; never publish report counts, balances, source filenames, account IDs, addresses, or credentials from a user's project.
- Read `docs/publishing.md`. Stage explicit curated public files, check staged/outgoing content, and test the public version. Avoid broad `git add .` where private data exists.
- Developer publishing is separate from normal imports. Auto-push requires explicit local authorization, tests/privacy checks, a feature branch, and a PR. Never auto-merge or push financial data.
