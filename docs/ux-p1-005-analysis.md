# UX-P1-005: Analysis workbench and drill-down

Priority: **P1**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Existing analysis pages work but evidence, values, filters and detail discovery need a consistent task hierarchy.

## Proposed scope

Keep summary/evidence above layered detail. Add holding/account drill-down and compatible date/range filters; preserve selected scope and explain original versus display currency. Keep overview compact and audit evidence expandable.

## Acceptance criteria

- [ ] Every amount identifies saved edition, scope, currency and relevant date.
- [ ] Holding details explain quantity, cost status, direct/ETF exposure and source provenance.
- [ ] Search/sort/filter retain Decimal semantics and return meaningful empty states.
- [ ] Single observation and gaps are truthful; negative/unknown values remain legible in dark mode, mobile and keyboard use.

## Dependencies and boundaries

UX-P0-002; existing report reader and source-neutral DTOs.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Synthetic multi-account/multi-source filters, date gaps, selection isolation and accessibility.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
