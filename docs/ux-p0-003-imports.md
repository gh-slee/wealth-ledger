# UX-P0-003: Understandable import and recovery

Priority: **P0**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

The import form exposes parser/context/reference controls early. Safe backend transitions exist but mapping, stale-preview and failed-publication recovery remain hard to explain.

## Proposed scope

Present source selection, required source details, mapping/references, exact review and outcome as clear stages. Keep advanced correction/compatibility controls available without making them the normal entry.

## Acceptance criteria

- [ ] Either CSV, both CSVs, BTC-only and saved-data flows remain supported with explicit observation times.
- [ ] Describe alias stability, timezone and evidence requirements; missing references point to the exact corrective step.
- [ ] Provider labels use trusted metadata or a safe generic fallback; an unknown enabled provider must never be mislabeled as Bull Bitcoin.
- [ ] Show ready versus blocked preview, exact reviewed inputs and explicit confirmation; editing invalidates approval.
- [ ] Published, data committed/report pending, interrupted, cancelled and unknown outcomes provide correct resume/new-preview/local-review actions. Never reimport uncertain commits.
- [ ] Keyboard/focus, mobile, all locales, idempotency/double clicks and no-network-preview semantics pass regression tests.

## Dependencies and boundaries

Existing jobs/recovery contracts and UX-P0-002. No ingestion or valuation-policy redesign.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Real synthetic mapping/publication/retry browser tests plus API stale-plan and receipt-recovery regressions.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
