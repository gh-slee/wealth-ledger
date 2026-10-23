# UX-P1-004: Targets and ETF overlap

Priority: **P1**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Current actual allocation and ETF company rankings lack user targets, drift and shared-company overlap comparisons.

## Proposed scope

Add opt-in target allocation/drift and FUT-004 weighted overlap using official frozen ETF evidence. Treat targets as user preferences, not trade advice or automatic rebalancing.

## Acceptance criteria

- [ ] Define target totals, cash scope, denominations and overlap formula/denominator.
- [ ] Incomplete ETF constituents show unresolved weight and effective/fetched dates; no re-fetch on page view.
- [ ] Targets do not change positions, cash flows, report history or create orders.
- [ ] Synthetic known overlaps and rounding/coverage cases verify every reported percentage.

## Dependencies and boundaries

FUT-004; official ETF identity/classification adapters and explicit target model.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Independent overlap examples, partial coverage, three-currency presentation and report checks.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
