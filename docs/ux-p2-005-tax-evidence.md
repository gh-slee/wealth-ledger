# UX-P2-005: Cost and tax evidence exports

Priority: **P2**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Users often want cost and tax summaries, but recorded investment flows are not statutory contribution room or complete tax basis.

## Proposed scope

Improve dated acquisition/disposal and income evidence exports first. Treat jurisdiction-specific tax rules and registered-account room as separate opt-in models with appropriate source requirements.

## Acceptance criteria

- [ ] Exports expose lot policy, original/converted amounts, dates, fees, missing history and revisions.
- [ ] Unknown basis is never zero; proxy costs are distinctly labeled and excluded from actual tax-basis claims.
- [ ] Do not claim CRA room, tax filing correctness or universal tax support from holdings/flow totals.

## Dependencies and boundaries

UX-P1-001/003; complete tax-specific evidence and separate legal/tax requirements.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Synthetic missing basis, disposals, transfers, exports and locale cases.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
