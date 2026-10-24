# UX-P0-001: First-use and empty-state guidance

Priority: **P0**

Status: **Implemented and merged through PR #13 (`0b62a8a`); deployment is a separate operator action**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Before this slice, new users lacked guidance from an empty portfolio to a trustworthy first report. Anonymous startup could incorrectly suggest session expiry, and pending portfolio loading could resemble no portfolios.

## Proposed scope

Provide an explicit no-published-report state and prepare/review/confirm sequence. Explain supported evidence, source identity/timezones, optional references, baseline selection, later contributions and exports. Keep financial actions explicit.

## Acceptance criteria

- [x] Anonymous first visit has no expired-session notice; actual authenticated expiry still clears the cache and returns to sign-in.
- [x] A pending portfolio request shows loading; an error shows retry, never a false create-first-portfolio message.
- [x] Creating an independent portfolio adds no financial facts. Empty analysis pages offer working import, records and settings links without zero-valued financial cards.
- [x] English, Traditional Chinese and Simplified Chinese have matching keys; keyboard, mobile and light/dark paths are reviewed.
- [x] Starting guidance makes no mutation, quote request, sample import, inferred opening or fabricated history. Existing import/approval and frozen-report tests stay green.

## Dependencies and boundaries

Existing owner initialization and default parser workflow. UX-P0-003 owns form restructuring, not this ticket.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Browser first-use/slow/error tests, actual session expiry regression, existing parser publication, build/source/locale/accessibility checks and a synthetic README empty-state image.

Local acceptance: the complete browser suite passed **12 cases**, including two
new first-use cases plus actual authentication-expiry/cache clearing, existing
parser publication, BTC-only submission and frozen report reading. The first-use
cases cover delayed/failed portfolio loading, metadata-only creation, all three
locales, light/dark Axe checks, 390px layout, keyboard activation and working links.
Frontend build, **14 unit tests**, **46 publication-policy tests**, formatting,
source/language checks and local document links passed. A targeted synthetic
empty-state gallery capture and visual/privacy review accompany this slice.

No financial model or API contract changed. The full Python financial suite and
Docker deployment tests were not rerun for this UI/documentation-only slice. New
remote CI, merge and deployment are separate; the real instance is not upgraded.
The two focused onboarding cases were also rerun successfully after the final
CSS step-marker correction. The targeted capture reported zero browser errors
and zero external browser requests.
