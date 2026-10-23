# UX-P1-002: Eligible performance and attribution

Priority: **P1**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Value growth is available but complete combined period returns are disabled without sufficient evidence.

## Proposed scope

Expose eligibility first, then implement defined money-weighted/Modified Dietz calculations only for compatible valuations and full boundary cash-flow coverage. Separate price, quantity and FX effects with an explicit interaction policy; do not label sparse data as daily time-weighted returns.

## Acceptance criteria

- [ ] Value change, net contributions, investment result and return rate are separate concepts with interval and scope.
- [ ] Unknown/partial costs, flows, stale valuations, changed scope and transfer gaps block unsupported metrics with reasons.
- [ ] Specify XIRR multiple/no-root and short-period behavior, fees/income and FX policy before implementation.
- [ ] Independent numerical examples verify formulas, including negatives, zero bases, mixed currencies and irregular dates.

## Dependencies and boundaries

UX-P1-001; combined-performance track; FUT-005; compatible historical valuation evidence.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Finance formula/API/report/locale regressions; browser unknown and eligibility states.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
