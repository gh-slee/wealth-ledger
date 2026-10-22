# UX-P1-001: Activity, contributions and transfers

Priority: **P1**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Holdings and Bull purchases cannot establish external contributions; flows are scattered and Bull funding origins are unclassified.

## Proposed scope

Build a scoped activity/contribution timeline and evidence-driven funding classification/transfer matching. Add append-only correction/void design before allowing edits; integrate a real activity parser only with a specified export.

## Acceptance criteria

- [ ] Purchases, income, external deposits and internal transfers have distinct labels and never double-count funds.
- [ ] Pairs retain source IDs, dates, currency/FX, fees and unresolved differences; classifications are explicit and revisable.
- [ ] Filters, exports and coverage intervals expose missing history rather than zero activity.
- [ ] Backfill does not overwrite frozen editions or manufacture acquisition costs.

## Dependencies and boundaries

Cash-flow track; native Wealthsimple activity conversion; source-aware manual-flow and transfer contracts.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Synthetic transfers, overlap, revisions, unknown origins and historical coverage cases.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
