# UX-P2-003: Mobile and balance privacy

Priority: **P2**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Existing responsive pages/dark mode are useful; dense workflows and screenshots can still expose balances during shared-screen use.

## Proposed scope

Improve phone/tablet navigation and add an optional conceal-balances mode. Evaluate installable PWA behavior without offline financial caches.

## Acceptance criteria

- [ ] Touch, keyboard, focus and zoom work for imports, tables and report navigation.
- [ ] Concealment covers accessible text, chart tooltips and key amounts with a clear reveal action; exports remain explicitly sensitive.
- [ ] No financial data, credentials or session tokens enter persistent browser storage or a service-worker cache.

## Dependencies and boundaries

Existing theme/accessibility/privacy contracts; PWA is optional and separately reviewed.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Phone/tablet/desktop, screen-reader, concealment/tooltip and storage/network assertions.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
