# UX-P0-003: Understandable import and recovery

Priority: **P0**

Status: **Implemented and merged through PR #13 (`0b62a8a`); deployment is a separate operator action**

Parent: [Product and UX review](product-ux-review.md)

## Problem

The import form exposes parser/context/reference controls early. Safe backend transitions exist but mapping, stale-preview and failed-publication recovery remain hard to explain.

## Proposed scope

Present source selection, required source details, mapping/references, exact review and outcome as clear stages. Keep advanced correction/compatibility controls available without making them the normal entry.

## Acceptance criteria

- [x] Either CSV, both CSVs, BTC-only and saved-data flows remain supported with explicit observation times.
- [x] Describe alias stability, timezone and evidence requirements; missing references point to the exact corrective step.
- [x] Provider labels use trusted metadata or a safe generic fallback; an unknown enabled provider must never be mislabeled as Bull Bitcoin.
- [x] Show ready versus blocked preview, exact reviewed inputs and explicit confirmation; editing invalidates approval.
- [x] Published, data committed/report pending, interrupted, cancelled and unknown outcomes provide correct resume/new-preview/local-review actions. Never reimport uncertain commits.
- [x] Keyboard/focus, mobile, all locales, idempotency/double clicks and no-network-preview semantics pass regression tests.

## Dependencies and boundaries

Existing jobs/recovery contracts and UX-P0-002. No ingestion or valuation-policy redesign.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Local acceptance: the complete browser suite passed **18 cases**. Three new
import-review journeys verify double-submission guards, unchanged request/key
retries after a lost confirmation response, editing/switching invalidation, exact
digest confirmation, linked formal jobs, missing-reference navigation, stale approval,
report-only resume, unknown/local-review outcomes, three locales, keyboard focus,
light/dark accessibility and narrow layouts without financial submissions. Existing
native single-CSV, parser mapping/publication, both-input and BTC-only flows remain
green; saved-data requests are covered by the new review journey.

**25 frontend unit tests** include five new approval/provider/outcome tests.
**45 existing synthetic Web API tests** passed across native imports, automatic
source imports and source reports, including offline preparation, expiry/state
revalidation, atomic commit and receipt/report-only recovery. **48 publication-policy
tests**, build, formatting and source checks passed. Targeted Impeccable static
inspection reported no new-component findings and one pre-existing login border
in the shared stylesheet; it remains outside this scope. The import README image
is refreshed from the isolated synthetic fixture, without upload or confirmation.

No financial endpoint/schema, parser, database migration, formula or runtime AI was
added. The bounded job list cannot prove an absent linked operation never ran;
copy explicitly avoids that inference and backend approval remains authoritative.
Draft invalidation is local to the current tab; closing/reloading discards unsent
fields and requires original inputs to be selected again for a new preview. A proven
saved report can resume independently of the draft. No persistent browser finance
cache, automatic reimport, cancellation rollback or forced recovery is introduced.

The full financial Python suite, new Docker acceptance and remote CI were not rerun
for this frontend-only slice; the focused API checks above were run. Local verification
is separate from publication, merge and deployment. Visual review also caught and
corrected historical published-job copy leaking into the new-draft progress state;
the final complete browser run covers that regression. An earlier browser locator failure
was corrected and superseded by the complete passing run.

## Impeccable Operate-mode implementation direction

Reduce simultaneous decisions through source selection, required source details,
then exact review/confirmation. Reveal advanced corrections and compatibility only
when needed. Keep familiar controls, visible progress, a recoverable draft, and clear
outcomes for committed data versus published reports. Preserve all existing explicit
approval/idempotency guards. Follow [the design workflow](ui-design-workflow.md);
this direction does not itself implement or approve new financial behavior.
