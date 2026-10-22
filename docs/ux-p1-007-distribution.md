# UX-P1-007: Pull-only self-host installation

Priority: **P1**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Current installation requires a source checkout and local image build; a generic ready-to-pull image is not yet published.

## Proposed scope

Deliver WEB-008 with reviewed version/digest-pinned multiarch images, pull-only Compose and clean installation/upgrade/recovery instructions. Retain local source builds.

## Acceptance criteria

- [ ] Document supported Linux containers/CPU and Docker Desktop host matrix with actual evidence.
- [ ] Fresh install, owner setup, independent empty portfolio, first synthetic import, restart and full backup/empty restore succeed.
- [ ] Publish image provenance/notices/inventory and perform appropriate vulnerability review.
- [ ] Image/registry publication requires separate explicit approval; no invented public tag or universal-host promise.

## Dependencies and boundaries

WEB-008; existing operations/backup/upgrade runbooks.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Clean pull on accepted target matrix, browser workflow and exact-image restore checks.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
