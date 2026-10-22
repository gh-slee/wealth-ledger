# UX-P1-006: Source capabilities and extension UX

Priority: **P1**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Two real format parsers and the extension pipeline exist, but users cannot easily inspect supported exports, parser versions or installation requirements.

## Proposed scope

Add a read-only source-capability catalogue from trusted registry metadata and an author-oriented v2 example path. Group supported real formats separately from enabled synthetic/developer examples. Prioritize additional institutions using supplied sanitized formats and user demand evidence.

## Acceptance criteria

- [ ] Show provider, format/API version, record kinds, installed/enabled state and data limits without host paths or secrets.
- [ ] No parser code is installed or enabled from a browser upload, CSV cell or network discovery.
- [ ] A new compatible v2 parser passes detection, identities/revisions, fees/coverage, reports and backup/restore acceptance without new provider branches.
- [ ] V1 nonbooking support is never presented as a financial importer; bank movements do not imply bank asset balances.

## Dependencies and boundaries

SRC-001 through SRC-004 implemented; SDK/registry trust contract remains unchanged.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Metadata-only API/browser tests; synthetic independent parser and invalid/ambiguous format cases.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
