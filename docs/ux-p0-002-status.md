# UX-P0-002: Evidence status and next actions

Priority: **P0**

Status: **Implemented and merged through PR #13 (`0b62a8a`); deployment is a separate operator action**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Source dates and checks exist, but users lack one prioritized explanation of what is stale, unconfirmed or incomplete and what action to take.

The [concrete design brief](ux-p0-002-status-design.md) describes hierarchy,
frozen-versus-current evidence, state handling and implementation acceptance.
The implementation follows that direction; unavailable structured evidence remains unknown.

## Proposed scope

Extend FUT-002 with an owner/portfolio-scoped read-only status view: latest publication, observation date versus publication time, carried sources, BTC reconciliation, contribution coverage and job state. Group by impact and link to existing actions.

## Acceptance criteria

- [x] Each status has a stable reason, evidence date, severity and deterministic relevant next action.
- [x] A complete supplied source scope never implies a verified wallet, complete wealth or eligible returns.
- [x] Empty, unavailable and unknown states remain distinct; no invented calendar-age threshold or no-file-means-no-activity inference.
- [x] Reading status performs no ledger writes, reference fetching, publication or financial observation.
- [x] Tests cover mixed dates, unknown costs, unresolved balances, missing flow coverage, pending/failed jobs, portfolio isolation and all locales.

## Dependencies and boundaries

FUT-002; reuse frozen checks and current job DTOs before adding a public endpoint.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Local acceptance: the complete browser suite passed **15 cases**, including three
new status journeys. They cover historical-versus-current state, exact import and
financial job links, no financial mutations on read/navigation, unavailable job and
report-list requests, three locales, keyboard expansion, light/dark accessibility,
mobile overflow and unavailable requested jobs. Existing import/publication,
financial declaration, frozen-history, source-plugin and portfolio-isolation flows
remain green. **20 frontend unit tests** include six new evidence/operation tests.

Build, formatting, source/language checks and **48 publication-policy tests** passed.
Impeccable's targeted static scan reported no new-component findings and one
pre-existing login border treatment in the shared stylesheet; it was retained
outside this scope. Synthetic overview gallery images are refreshed separately
from the test service; no private portfolio is inspected.

No new API endpoint/schema, database migration, financial formula or original saved
report changes were needed. Missing numeric wallet gaps, complete flow coverage
intervals and full-return eligibility remain unavailable in the current DTO. Full
cost is only treated as supplied when its structured field is a valid nonnegative
decimal string, including valid zero. These limits are explicit, not zero balances
or successful reconciliation. FUT-002 retains broader structured status work.

The financial Python suite, new Docker deployment tests and remote CI were not rerun
for this frontend-only slice. Merge, publication and personal deployment are separate.
Earlier failed test setup/locator attempts are superseded by the complete passing
run; no failed result is treated as acceptance.

## Impeccable Operate-mode implementation direction

Use three layers: a brief status summary, only actionable issues with one relevant
next step each, then expandable evidence. Keep the saved amount and observation date
visible. Do not replace unknowns with reassuring green badges, guess source freshness,
or turn every informational notice into an interruption. This is a scoped refinement
of the existing workbench, not a new brand or a live valuation screen. Follow
[the optional design workflow](ui-design-workflow.md) during implementation.
