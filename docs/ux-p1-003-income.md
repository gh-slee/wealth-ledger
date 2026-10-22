# UX-P1-003: Income, fees and corporate actions

Priority: **P1**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Users expect dividend/income and fee tracking, but holdings alone cannot provide realized results or corporate-action history.

## Proposed scope

Add explicit cash income, taxes/withholding, fees and security actions from evidenced transaction formats. Distinguish recorded income from optional future estimates; define acquisition/disposal cost allocation.

## Acceptance criteria

- [ ] Gross/net income and fees retain original currency, effective dates and source evidence.
- [ ] DRIPs, splits, mergers, sales and partial disposals conserve quantities/costs according to a documented policy.
- [ ] Realized and unrealized P/L remain unknown until compatible lots and disposal evidence exist.
- [ ] No automatic entitlement or future-dividend promise is inferred from a holdings snapshot.

## Dependencies and boundaries

Transaction sources, UX-P1-001, separate lot/cost and corporate-action contracts.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Synthetic income/DRIP/split/sale/fee and missing-cost cases, frozen report and locale checks.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
