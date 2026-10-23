# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Individuals and households who track investments from institution CSV exports and
want a durable, inspectable record without providing brokerage login credentials.
One self-hosted instance serves one owner or household with separate portfolios.
Parser authors can extend supported formats through the trusted Python SDK.

## Product Purpose

Wealth Ledger preserves financial source evidence, dated observations and explicit
financial declarations, then produces reusable portfolio analysis and downloadable
ODS, Markdown and PDF reports. Success means understanding what the recorded assets
are worth, what changed, and which conclusions the supplied evidence supports.

## Positioning

The application is a local-first investment ledger with an extensible CSV parser
boundary. Its direction covers bank, brokerage and Bitcoin-platform exports; its
currently implemented real formats are Wealthsimple holdings and Bull Bitcoin
orders. This is not a claim of universal institution support. Shared core code
owns storage, finance rules, confirmation and immutable report publication.

## Operating Context

- The Python CLI and optional self-hosted Web App share the financial core. The Web
  App uses React/TypeScript/Vite, FastAPI, a Python worker and SQLite storage.
- Users can provide either supported CSV, both, or explicit financial declarations.
  Update dates may be irregular. Original CSVs and source dates are retained.
- A new portfolio starts with an import preview, explicit approval and publication.
  Later corrections and declarations preserve revision and evidence history.
- Reports are saved observations, not live brokerage balances. The Web reader and
  its downloads refer to the selected saved edition. Observation cutoffs differ
  from publication times and the dates of individual sources.
- Docker self-hosting and copy-verified legacy CLI adoption have documented
  procedures. Deployment, backup/restore and migration are operator actions;
  public pull-only multiarchitecture distribution remains a roadmap item.

## Capabilities and Constraints

- CAD, USD and TWD are alternative reporting equivalents, never additive totals.
  Keep native currencies, reference dates, prices and FX evidence visible.
- BTC and LBTC retain their delivery identities while totals may use 1:1 BTC
  equivalents. Purchases, opening declarations, wallet observations and events
  have different evidence meanings. Orders alone do not confirm wallet balances.
- Holdings changes and purchase spending do not establish contributions. Transfers
  within tracked accounts are not new portfolio contributions. Incomplete flows
  limit period-return conclusions; unknown values remain distinct from zero.
- Official ETF look-through uses deterministic issuer adapters, dated raw evidence,
  hashes and parser versions. Partial classifications and unresolved exposure
  remain visible; covered weights are not silently normalized to the full portfolio.
- Existing parser plugins are trusted, explicitly installed host code. Uploaded
  files do not install code. New formats need adapter validation and acceptance tests.
- Application calculations, data fetching, charts and report prose run in code.
  No runtime LLM, Codex or local LibreOffice installation is required.
- Preserve append-only evidence, frozen editions, explicit approval, recovery and
  isolation between portfolios. Reading a report does not create observations.
- Product locales are en-CA, zh-TW and zh-CN. Public developer documentation and
  generic examples use English; user/source text retains its original meaning.

## Brand Commitments

The name is Wealth Ledger. Its voice is factual and calm: distinguish observations,
estimates and unknowns, and describe a concrete next step without implying trading
advice or unsupported assurance.

## Evidence on Hand

The [README gallery](assets/readme/README.md) contains invented demonstration data
rendered through the real UI. [Examples](examples/README.md), tests and locked
build inputs support reproducible verification. These are not customer balances,
endorsements, measured popularity or promises that every format/platform is supported.
See [the first-use guide](docs/getting-started.md), [parser SDK](docs/parser-sdk.md)
and [roadmap](TODO.md) for supported workflows and remaining work.

## Product Principles

- Make evidence and its limits understandable alongside the result.
- Preserve history rather than recomputing or silently replacing earlier facts.
- Keep institution-specific parsing behind the shared contract.
- Require explicit, recoverable approval for financial mutations.
- Keep the deployed application independent of development AI tools.
