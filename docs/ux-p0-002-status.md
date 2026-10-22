# UX-P0-002: Evidence status and next actions

Priority: **P0**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Source dates and checks exist, but users lack one prioritized explanation of what is stale, unconfirmed or incomplete and what action to take.

## Proposed scope

Extend FUT-002 with an owner/portfolio-scoped read-only status view: latest publication, observation date versus publication time, carried sources, BTC reconciliation, contribution coverage and job state. Group by impact and link to existing actions.

## Acceptance criteria

- [ ] Each status has a stable reason, evidence date, severity and deterministic relevant next action.
- [ ] A complete supplied source scope never implies a verified wallet, complete wealth or eligible returns.
- [ ] Empty, unavailable and unknown states remain distinct; no invented calendar-age threshold or no-file-means-no-activity inference.
- [ ] Reading status performs no ledger writes, reference fetching, publication or financial observation.
- [ ] Tests cover mixed dates, unknown costs, unresolved balances, missing flow coverage, pending/failed jobs, portfolio isolation and all locales.

## Dependencies and boundaries

FUT-002; reuse frozen checks and current job DTOs before adding a public endpoint.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Synthetic core/API/browser status cases; no private portfolio inspection.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
