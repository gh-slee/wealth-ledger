# UX-P2-004: Operations and account security UX

Priority: **P2**

Status: **Planned**

Parent: [Product and UX review](product-ux-review.md)

## Problem

Full backup/restore and host authentication controls exist but need clearer operator discovery and deployment-specific security decisions.

## Proposed scope

Expose safe backup/version/recovery instructions and evaluate optional second-factor/trusted-proxy support as separate threat-modelled changes. Keep restoring and installing code on the trusted host.

## Acceptance criteria

- [ ] Distinguish report ZIP/data export from complete secret-containing instance backup.
- [ ] Explain exact-image restore to a separate empty target and off-device backup responsibilities.
- [ ] Remote access keeps TLS/origin/CSRF/rate-limit boundaries; never add browser account claiming.
- [ ] Any new authentication/recovery mechanism has lockout, session-revocation and backup compatibility tests.

## Dependencies and boundaries

WEB-005/007, SECURITY.md and deployment runbooks; no household-role expansion by implication.

All features run deterministically in code. Use isolated synthetic data. Keep
unknowns, explicit confirmation, original evidence and frozen editions. No private
data migration, live revaluation on read, publication or deployment is authorized
by this ticket. Future UI changes update affected README screenshots and captions.

## Validation and completion evidence

Synthetic recovery and auth cases; no personal volume or real credentials.

No completion claim yet. Record actual checks, limitations and merged status here
when this ticket is implemented; do not substitute a checked roadmap row for tests.
