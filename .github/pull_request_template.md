<!-- This file is the canonical PR format. Keep the three required sections and
all four evidence categories, even for a small PR. Replace placeholders, use real
results, and remove unused conditional/recommended sections. Humanizer may improve
wording but must preserve this structure, technical facts and validation gaps.
The pr-standard comments identify requirements for the lightweight validator. -->

<!-- pr-standard: required -->
## Change Summary

<One sentence stating the problem and resulting behavior.>

- <Important functional change or meaningful before/after behavior.>
- <What users/developers can do, or a significant implementation decision.>
<!-- Use 2-6 focused bullets. Keep small changes short. -->

<!-- pr-standard: required -->
## Files Changed

- `<repository-relative path>`: <What changed and why it matters.>
<!-- Group meaningful modules rather than repeating the diff inventory. Summarize
large PRs in roughly 3-10 bullets; never omit an important area to meet a target.
Mention significant additions, removals, migrations and interface changes. -->

<!-- pr-standard: required -->
## Testing & Evidence

<!-- pr-standard: evidence -->
### Local Verification

- <STATUS>: <Actual command/suite, result, and relevant pass/fail/skip counts.>

<!-- pr-standard: evidence -->
### CI Verification

- <STATUS>: <Verified run link and result; distinguish push and PR CI when useful.>
<!-- Use NOT RUN before a remote run exists; PENDING while it runs. Never invent
CI success. Link evidence rather than pasting logs. -->

<!-- pr-standard: evidence -->
### Independent QA / Architecture Review

- <STATUS>: <Actual independent review scope and outcome, or why NOT RUN.>
<!-- Developer self-tests are not independent QA. Do not publish private review
files, authorization evidence, transcripts or machine-specific paths. -->

<!-- pr-standard: evidence -->
### Required Pre-PR Validation

- <STATUS>: `python scripts/check_pr_image.py` after the final reviewed commit; commit `<SHA>`, image `sha256:<digest>`, and actual smoke results or an explicit gap.
<!-- Status values: PASS, FAIL, NOT RUN; CI may use PENDING. A skipped/incomplete
check is not a PASS. Preserve required checks, privacy and owner approval gates.
Checkboxes, if used, must represent verified results rather than intentions. -->

## Behavior & Compatibility

- <Existing behavior, API/schema/CLI/config changes, opt-in flags, upgrade needs or data migration requirements.>
<!-- Conditional: distinguish implemented behavior from planned features. -->

## Risks, Limitations & Rollback

- <Material limitation, isolation/security concern, migration risk and safe recovery/rollback constraint.>
<!-- Conditional: omit boilerplate for low-risk documentation-only changes.
Reverting code does not automatically reverse a database migration. -->

## Reviewer Focus

- <Highest-value behavior, architectural decision or risk to examine.>
<!-- Recommended for medium/large PRs: use 1-3 focused bullets. -->

## Screenshots / Visual Evidence

- <Synthetic before/after evidence and a short explanation of visible changes.>
<!-- UI changes only. Keep README screenshot maintenance requirements. Never add
this as an empty placeholder to a backend-only PR. -->

## Related Issues / Documentation

- <Verified relevant Issue, public spec/ADR or documentation link.>
<!-- Conditional. Use Closes/Fixes only if the PR completes the issue; otherwise
use Refs. Never invent an issue, review, approval, screenshot or evidence link. -->
