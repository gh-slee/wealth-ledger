# UI/UX feature inventory and ticket coverage

Built on 2026-11-10 at `main` commit `b771301`. One row per screen and per
user-facing feature. Every row ends in a ticket or in "no change needed".
[TICKET_CHANGES.md](TICKET_CHANGES.md) lists what was written and the batches.

## How it was built

- Read the frontend (`frontend/src`), every HTTP route of both backends
  (`src/wealth_ledger/web/`, `src/wealth_ledger/web_v2/`), the product and design
  documents and all tickets.
- Ran the repository's disposable synthetic server (`scripts/web_browser_fixture.py`)
  on 2026-11-09 and 2026-11-10 and visited every page of the shipped application:
  a populated, an empty and a source-pipeline portfolio; 1024x768 and 375x812;
  dark and light themes; English and Traditional Chinese; reload, navigation,
  an unknown page and an unknown portfolio. Only invented data was used.
- Evidence marks: **V** observed in the running application, **S** read in source,
  **D** from documents.

Not run: the V2 backend (needs an opt-in PostgreSQL environment; it has no UI),
the Playwright suite (the audit sandbox cannot start a headless browser), a
screen reader, and Simplified Chinese page by page (catalog parity was checked:
499 keys in each of the three catalogs). V2 rows are therefore **S** or **D**.

Disposition: KEEP, IMPROVE, SIMPLIFY, CONSOLIDATE, COMPLETE, REMOVE, BUILD.

## Shipped application (SQLite, `/api/v1`)

| Screen / feature | User goal | Works today | Problems found | Missing capability | Tickets | Disposition |
|---|---|---|---|---|---|---|
| Sign-in | Enter the instance | Yes (V) | Decorative text stays English in zh-TW (V, `App.tsx:212-218`); raw error code after the message (S, `App.tsx:226-228`) | In-browser recovery (host only by design) | UX-P1-012 | IMPROVE |
| Session expiry and sign-out | Leave safely | Yes (S, browser suite) | None | None | no change needed | KEEP |
| Shell and navigation, desktop | Reach nine pages | Yes (V) | Nine destinations; V2 reduces to eight | None | WL-P0-011A | KEEP until cutover |
| Shell and navigation, phone | Reach content on a phone | Poorly (V) | Content starts at 380 px, value at 989 px; three of nine destinations visible; 37 px targets | Compact menu | UX-P1-015 | IMPROVE |
| Unknown page or portfolio | Understand a wrong link | No (V) | Unknown page renders Overview; unknown portfolio offers a useless retry | Not-found states | UX-P2-007 | IMPROVE |
| Interface language | Read in my language | Partly (V) | Reset to English on every load (`main.tsx:25`) | Persistence, browser default | UX-P1-010 | IMPROVE |
| Appearance (light, dark, system) | Comfortable reading | Yes (V) | None | None | no change needed | KEEP |
| Display currency | See CAD, USD or TWD | Partly (V) | Survives navigation; resets on reload (`App.tsx:299`); offered on three pages only | Persistence | UX-P1-009 | IMPROVE |
| Report edition selector | Read an earlier edition | Partly (V) | Selection lost on every sidebar navigation (`App.tsx:396`); hash-like labels | Carry selection; notice | UX-P1-009 | IMPROVE; REMOVE in V2 |
| Time display | Know when | Yes (V) | Fixed to Toronto (`lib/format.ts:52`, `chart-view.tsx:115`, seven core modules) | Configurable zone | WL-P1-007, WL-P0-011E | IMPROVE |
| Portfolio selector and creation | Separate ledgers | Yes (V) | No rename or delete | None wanted: V2 has one portfolio | WL-P0-011A removes it | REMOVE (V2) |
| First-run guide | Know what to prepare | Yes (V) | Full guide repeated on four other pages under an inert currency selector | Short pointer | UX-P2-007 | SIMPLIFY |
| Overview | What is it worth | Yes (V) | Value followed by two screens of evidence panel (`analysis.tsx:60`) | Value-first layout | UX-P1-008; WL-P0-012D | SIMPLIFY |
| Value chart | See change over time | Broken with one observation (V) | Eight repeated axis labels (`chart-view.tsx:105-118`) | None | UX-P1-011 | IMPROVE |
| Evidence status and next steps | Know what is uncertain | Yes (V) | Raw check code shown (`lib/evidence-status.ts:182`) | Localized titles | UX-P1-012, UX-P1-008 | SIMPLIFY |
| Holdings | See positions | Yes (V) | Cash rows as securities; native and display currency mixed; one account label in the wrong language (`web/reports.py:259`) | Cash table; labelled columns | UX-P2-006, UX-P1-012; WL-P0-012B | IMPROVE |
| Exposure and ETF look-through | Underlying companies, sectors, countries | Yes (V) | Heading repeated as caption | Denominator choice (V2) | UX-P2-008; WL-P0-010, WL-P0-012E | KEEP |
| History | Value by observation | Yes (V) | Same chart defect | Ranges (UX-P1-005) | UX-P1-011 | IMPROVE |
| Bitcoin and flows | BTC quantity and cost | Yes (V) | Provider-specific wording; funding and cash flows mixed in | Generic acquisition view | WL-P0-012C (V2); no change on the shipped page | SIMPLIFY (V2) |
| Import: upload, preview, confirm | Add an observation | Yes (V, browser suite) | Typed ISO timestamps (`imports.tsx:507,521`); step 3 current on arrival (`:170-176`); duplicate introduction; identical job rows | Pickers; truthful steps | UX-P1-013, UX-P1-014; WL-P0-011D | IMPROVE |
| Import recovery (stale, uncertain, resume) | Recover safely | Yes (S, browser suite) | None found | None | no change needed | KEEP |
| Financial records (declarations) | Record BTC totals, events, cash flows | Yes (V) | Seven record types on one form; typed timestamps | None wanted: V2 drops it from navigation | UX-P1-013 (timestamps only) | RECONSIDER; REMOVE from V2 navigation |
| Report reader | Read a saved edition | Yes (V) | Downloads labelled by file name; attachment captioned by file name | Descriptive labels | UX-P2-008 | KEEP |
| Report downloads and data export | Take files away | Yes (V) | None beyond labels | On-demand export (V2) | WL-P0-013A, WL-P0-013B | KEEP; becomes on demand |
| Settings | Report language, BTC cost policy, password | Yes (V) | One new-password field; unrelated closing sentence | Confirmation | UX-P2-007 | IMPROVE |
| Backup, restore, adoption | Protect data | Yes, host commands (D) | Not discoverable in the UI | UI entry points | UX-P2-004 | KEEP |
| Headings and table names | Scan by structure | Partly (V) | Heading repeated as hidden caption on four panels | None | UX-P2-008 | IMPROVE |
| Locales (three) | Use the product in my language | Yes (V, parity checked) | See language and labels rows | More locales | WL-P2-004 | KEEP |

## V2 (PostgreSQL, `/api/v2`): planned screens

| Screen / feature | User goal | Backend today | UI today | Tickets | Disposition |
|---|---|---|---|---|---|
| Bundle delivery | Open V2 in a browser | No HTML or asset route (S, `web_v2/api.py:26-38`) | None | WL-P0-011G | BUILD |
| Shell, eight destinations, phone menu, not-found | Find everything | n/a | None | WL-P0-011A | BUILD |
| First setup, registration by invitation, sign-in | Get an account | Merged (S, `web_v2/api.py:310-346`) | None | WL-P0-011B | BUILD |
| Invitation management | Admin invites people | Merged (S, `:361-377`) | None | WL-P0-011B | BUILD |
| Data Sources: enable, connections | Choose my institutions | Merged, explicit profile (S, `:412-437`) | None | WL-P0-011C | BUILD |
| Import Data: upload, review, confirm, history | Add data | SQL about half merged; no routes (D) | None | WL-P0-007E (routes), WL-P0-011D (UI) | BUILD |
| Preferences: language, time zone, currency | Same settings on every device | Missing: `Me` has none (S, `schemas.py:109-112`) | None | WL-P0-011E | BUILD |
| Profile and App Settings pages | Manage my account and defaults | Password change exists (S, `:346`) | None | WL-P0-011F | BUILD |
| Analysis read contract | Consistent numbers | Missing (S) | n/a | WL-P0-012A | BUILD |
| Stock/Bond page and shared toolbar (currency, refresh, download) | See securities now | Needs 012A | None | WL-P0-012B | BUILD |
| Crypto page | See acquired Bitcoin | Needs 012A | None | WL-P0-012C | BUILD |
| Total page and Home | Combined picture; where to go next | Needs 012A | None | WL-P0-012D | BUILD |
| Exposures page | Underlying concentration | Contract in WL-P0-010 | None | WL-P0-012E | BUILD |
| Price and FX refresh | Current values | Missing | Toolbar control in 012B | WL-P0-009 | BUILD |
| Download panel | Take a report away | Needs 013A | None | WL-P0-013A, WL-P0-013B | BUILD |
| Legacy report archive | Read my earlier reports after migration | Not defined | Reader exists in the shipped app | WL-P0-020 | BUILD |
| ETF search for unheld funds | Look up any ETF | Missing | None | WL-P1-002 | BUILD later |
| API source connection | Sync without CSV | Missing | None | WL-P1-001 | BUILD later |
| Plugin authoring guide | Add an institution | SDK exists | Link from Data Sources | WL-P1-003, WL-P0-011C | BUILD later |
| Drill-downs, targets, overlap | Deeper analysis | Missing | None | UX-P1-004, UX-P1-005, WL-P1-004 | BUILD later |
| Page-level mobile layout, balance privacy | Use on a phone in public | n/a | None | UX-P2-003 | BUILD later |
| Operations and account security UX | Back up from the app | Host commands | None | UX-P2-004 | BUILD later |
| Activity, performance, income, risk, goals, tax exports | Returns and planning | Out of the approved baseline | None | UX-P1-001 to 003, UX-P2-001, 002, 005 (all wait on WL-P2-002) | Deferred by decision |

## User journeys

| Journey | Steps | Covered by |
|---|---|---|
| Evaluate before installing | README, screenshots | WL-P2-007 (synthetic demo) |
| Install and first sign-in (shipped) | Source build, host owner setup | UX-P1-007 (pull-only install, after V2 release) |
| First import (shipped) | Import page, preview, confirm, open report | UX-P1-013, UX-P1-014 |
| Read the result (shipped) | Overview, Holdings, Exposure, History, Bitcoin, Reports | UX-P1-008, 009, 011, 012; UX-P2-006, 008 |
| Return next month (shipped) | Sign in, import, compare editions | UX-P1-009, UX-P1-010 |
| Use on a phone (shipped) | Any page at 375 px | UX-P1-015 |
| Recover from a wrong link or typo | Not-found, password change | UX-P2-007 |
| V2: invitation to first analysis | Register, sign in, enable a source, import, see Stock/Bond | WL-P0-011G, 011A, 011B, 011C, 011D, 012A, 012B |
| V2: add Bitcoin and see the total | Import orders, Crypto, Total, Home | WL-P0-012C, 012D |
| V2: refresh and download | Refresh prices, download PDF | WL-P0-009, 012B, 013A, 013B |
| V2: set language, zone and currency | Profile | WL-P0-011E, 011F |
| V2: migrate and keep old reports | Cutover, archive | WL-P0-014, WL-P0-020 |

## Coverage check

Every row above names at least one ticket or "no change needed". Rows marked
"no change needed": session expiry and sign-out, appearance, import recovery,
and the shipped Bitcoin page (replaced in V2, left alone meanwhile).

Known limits of this inventory: V2 rows describe intended screens, not observed
ones; the V2 import routes are not built, so WL-P0-011D's field-level detail
waits on WL-P0-007E; contrast and screen-reader behaviour were not measured.
