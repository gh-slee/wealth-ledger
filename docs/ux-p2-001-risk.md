# UX-P2-001: Benchmarks and risk

Priority: **P2**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Benchmark comparisons, volatility and drawdown are recurring tracker features but sparse value observations do not establish a valid return series.

## Proposed scope

Add user-selected licensed benchmark data, matched currency/period and risk calculations only after eligible return series exist.

## Acceptance criteria

- [ ] Define total versus price returns, FX, calendar, risk-free assumptions and fees.
- [ ] Missing prices/flows or short/sparse series disable unsupported risk statistics.
- [ ] No forward-looking risk or benchmark outperformance claims from incomplete samples.

## Dependencies and boundaries

UX-P1-002; licensed dated benchmark/reference sources.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Independent series tests, missing intervals, dividends, FX and compatible-period comparisons.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
