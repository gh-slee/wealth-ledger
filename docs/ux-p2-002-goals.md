# UX-P2-002: Goals and scenarios

Priority: **P2**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Investors may want contribution goals and scenario projections without contaminating actual evidence.

## Proposed scope

Offer opt-in user-entered contribution/allocation goals and assumption-based what-if calculations, kept separate from recorded history.

## Acceptance criteria

- [ ] Assumptions, nominal/real currency and inflation/return inputs are visible and editable.
- [ ] Scenarios never write holdings, contributions or historical observations.
- [ ] Projected outcomes are labeled scenarios and do not promise investment performance.

## Dependencies and boundaries

Explicit scenario model, UX-P1-001 contribution semantics.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Deterministic zero/negative/range cases; persistence isolation and locale checks.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
