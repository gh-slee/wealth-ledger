# Ticket changes from the UI/UX backlog pass (2026-11-10)

Source of the changes: [UX_FEATURE_INVENTORY.md](UX_FEATURE_INVENTORY.md).
All new tickets are `status: backlog`, so `tickets.py next` does not offer them
until the owner releases them. No `gate_approval` was filled in. No done,
claimed, in-progress or in-review ticket was edited (WL-P1-006, WL-P0-007,
WL-P0-017 and WL-P0-018 are untouched).

## Counts

| | P0 | P1 | P2 | Total |
|---|---|---|---|---|
| Created | 12 | 11 | 6 | 29 |
| Improved in place | 8 | 1 | 1 | 10 |
| Of the improved: split into children | 2 (WL-P0-012, WL-P0-013) | | | 2 |
| Merged | 0 | 0 | 0 | 0 |
| Recommended for closure | 0 | 0 | 1 (WL-P2-005) | 1 |

The board now holds 89 tickets.

## Created

### Shipped application

| ID | Pri | Type | Gate | Title | Why |
|---|---|---|---|---|---|
| UX-P1-008 | P1 | feature | owner | Lead the Overview with the value and collapse evidence detail | Value is followed by two screens of evidence panel |
| UX-P1-009 | P1 | bug | none | Keep the selected edition while navigating and the currency across reloads | Edition silently lost on every sidebar click |
| UX-P1-010 | P1 | feature | none | Remember the interface language | Resets to English on each load |
| UX-P1-011 | P1 | bug | none | Fix the value chart time axis with few observations | First chart of every new portfolio shows repeated labels |
| UX-P1-012 | P1 | bug | none | Every label in the selected language; no internal codes | Wrong-language labels, raw check code, English sign-in text |
| UX-P1-013 | P1 | feature | owner | Date, time and zone controls instead of typed ISO timestamps | Users must type a UTC offset |
| UX-P1-014 | P1 | bug | none | Import page: right step, one introduction, distinguishable jobs | Step 3 current on arrival; identical job rows |
| UX-P1-015 | P1 | feature | owner | Compact mobile navigation for the current shell | Content starts 380 px down on a phone |
| UX-P2-006 | P2 | feature | owner | Separate cash from securities; label money columns | Cash shown with average cost and P/L |
| UX-P2-007 | P2 | bug | none | Tidy empty, not-found and settings states | Unknown page shows Overview; no password confirmation |
| UX-P2-008 | P2 | bug | none | Remove repeated headings; descriptive download names | Headings read twice; downloads named by file |

### V2 screens and their contracts

| ID | Pri | Type | Gate | Title | Why |
|---|---|---|---|---|---|
| WL-P0-011E | P0 | feature | owner | User preferences in the V2 identity API | Profile needs language, zone and currency; the API stores none |
| WL-P0-011F | P0 | feature | owner | App Settings and Profile pages | Two of eight destinations had no ticket |
| WL-P0-011G | P0 | feature | owner | Serve the frontend bundle from the V2 backend | V2 has no HTML or asset route |
| WL-P0-012A | P0 | feature | owner | Analysis read contract | Split from WL-P0-012 |
| WL-P0-012B | P0 | feature | owner | Stock/Bond page and shared toolbar | Split from WL-P0-012 |
| WL-P0-012C | P0 | feature | owner | Crypto page | Split from WL-P0-012 |
| WL-P0-012D | P0 | feature | owner | Total page and Home | Split from WL-P0-012 |
| WL-P0-012E | P0 | feature | owner | Exposures page | WL-P0-010 delivers the data; nothing built the page |
| WL-P0-013A | P0 | feature | owner | Render exports on demand | Split from WL-P0-013 |
| WL-P0-013B | P0 | feature | owner | Download panel | Split from WL-P0-013 |
| WL-P0-019 | P0 | decision | owner | V2 delivery order and first-release hardening scope | No ticket is claimable; the path is long and serial |
| WL-P0-020 | P0 | feature | owner | Legacy report archive in the V2 app | Migrated users would lose access to earlier reports |

### Supporting

| ID | Pri | Type | Gate | Title |
|---|---|---|---|---|
| WL-P1-007 | P1 | research | owner | Configurable time zone for display and month grouping |
| WL-P1-008 | P1 | chore | owner | Board drift and readiness check (`tickets.py doctor`) |
| WL-P1-009 | P1 | chore | owner | Owner inbox of open gates and decisions |
| WL-P2-006 | P2 | chore | owner | Python lint gate for new and changed code |
| WL-P2-007 | P2 | feature | owner | One-command synthetic demo instance |
| WL-P2-008 | P2 | research | owner | Retirement plan for superseded import paths |

## Improved in place

Each keeps its ID, status, gate and history and has a dated Log line.

| ID | Change |
|---|---|
| WL-P0-011 | Plan lists all seven children, including new 011E, 011F, 011G |
| WL-P0-011A | Current behaviour with file evidence; routes; coexistence and serving decisions; measurable phone, not-found and persistence criteria |
| WL-P0-011B | Identity routes and DTOs named; per-screen behaviour; password, recovery wording and invitation states |
| WL-P0-011C | Source routes and DTOs named; a plain list, not a storefront; conflict and confirmation states |
| WL-P0-011D | Step-by-step target flow; criteria from defects seen in the shipped import page |
| WL-P0-012 | Now the epic of 012A to 012E; `type: epic`, no resources; criteria unchanged |
| WL-P0-013 | Now the epic of 013A and 013B; `type: epic`, size L; criteria unchanged |
| WL-P0-010 | States that it delivers the exposure contract and that the page is 012E; names the code to port |
| UX-P2-003 | Mobile shell moved to WL-P0-011A and UX-P1-015; keeps page-level layout and balance privacy |
| WL-P1-005 | Covers all eleven open UX tickets that say "refreshed for V2", not two |

## Recommended, not done

These need the owner or touch tickets this pass must not edit.

| Ticket | Recommendation | Why not done here |
|---|---|---|
| WL-P2-005 | Close: saves one upload click, adds a watcher and a trust boundary | Closing is the owner's call |
| WL-P0-017, WL-P0-018 | Mark `done`; both are merged (PR #30, PR #34) | In review; PR #37 already flips 018 |
| WL-P0-007K | Fold into WL-P0-007C | The ticket asks the owner this question itself |
| WL-P0-007D, 007E, 007F | Add dependencies on 007J, 007K, 007L | Backend order; inferred from ticket text, needs an architect |
| WL-P0-009, WL-P0-014, WL-P0-007F | Split | Backend scope, outside a UI/UX pass |
| WL-P0-011, 011A, 016 | `ready` with an unapproved gate is misleading | Status changes belong to the owner |

## Owner decisions that block tickets

Most blocking first.

1. WL-P0-019: delivery order and first-release hardening. Informs everything in V2.
2. Gate A on WL-P0-011, and whether it covers 011E, 011F, 011G and the 012 and 013 children.
3. WL-P0-011A decisions: one bundle with two shells, and serving the bundle from the V2 app (WL-P0-011G).
4. WL-P0-011E: which preferences live on the server; whether a session list is in the first release.
5. WL-P0-012A: whether a thin first version may value securities from the import's own market values.
6. Whether to invest in the shipped UI: UX-P1-008, UX-P1-013, UX-P1-015, UX-P2-006.
7. WL-P0-020: where archived editions are served.
8. WL-P1-007: scope and default of the time zone setting.
9. Workflow and tooling: WL-P1-008, WL-P1-009, WL-P2-006, WL-P2-007.
10. Release of the ungated tickets: UX-P1-009, 010, 011, 012, 014; UX-P2-007, 008.

## Execution batches

A row is a lane. Lanes in one batch share no exclusive resource and have no
dependency between them. The three locale catalogs are one resource
(`frontend-i18n`), so tickets that add many strings run one after another.

### Batch 1: releasable today without a design decision

| Lane | Ticket | Tier | Resources |
|---|---|---|---|
| Shell | UX-P1-009 | standard | frontend-shell |
| Charts | UX-P1-011 | standard | frontend-charts |
| Labels | UX-P1-012 | standard | web-report-view, frontend-analysis, frontend-i18n |

### Batch 2

| Lane | Ticket | Tier | Resources |
|---|---|---|---|
| Shell | UX-P1-010 | any | frontend-shell |
| Imports | UX-P1-014 | standard | frontend-imports-ui, frontend-i18n |
| Workflow (after its gate) | WL-P1-008, then WL-P1-009 | standard, any | public-docs-agent-rules |

### Batch 3: after the owner's answer on the shipped UI

Serial on `frontend-i18n`: UX-P1-008, UX-P1-013, UX-P1-015, then UX-P2-006,
UX-P2-007, UX-P2-008. UX-P1-015 and UX-P2-007 also need `frontend-shell`, so
finish them before WL-P0-011A starts.

### Batch 4: V2 screens, after Gate A

| Step | Tickets | Parallel |
|---|---|---|
| 1 | WL-P0-011A (shell); WL-P0-011E (preferences); WL-P0-011G (serving) | Yes: three different resources |
| 2 | WL-P0-011B; WL-P0-011C; WL-P0-011F | Yes: identity, sources and settings UI resources |
| 3 | WL-P0-011D | After WL-P0-007E |
| 4 | WL-P0-012A | After WL-P0-008 and WL-P0-009 |
| 5 | WL-P0-012B, then 012C, then 012D; 012E after WL-P0-010 | Serial on frontend-analysis and frontend-i18n |
| 6 | WL-P0-013A, then WL-P0-013B | Serial |
| 7 | WL-P0-020 | After WL-P0-014 |

### Shared files to watch

| File | Tickets | Handling |
|---|---|---|
| `frontend/src/locales/*.json` | every UI ticket | `frontend-i18n` lock; keys in a block named for the ticket |
| `frontend/src/App.tsx` | UX-P1-009, 010, 015, UX-P2-007, WL-P0-011A | `frontend-shell` lock; shipped-shell tickets first |
| `frontend/src/components/analysis.tsx` | UX-P1-008, 012, UX-P2-006, 008 | `frontend-analysis` lock |
| `frontend/src/components/imports.tsx` | UX-P1-013, 014 | `frontend-imports-ui` lock |
| `src/wealth_ledger/web_v2/schemas.py`, `api.py` | WL-P0-011E, 011G, 012A, 013A, WL-P0-007E | Different resources; rebase before the PR, DTO blocks are additive |
| Migration numbering | WL-P0-011E, WL-P0-007D | `migration-order` lock |
| README screenshots | every UI ticket | Each ticket refreshes only its own page |

New resource names introduced: `web-report-view`, `frontend-reports-ui`,
`frontend-settings-ui`, `v2-frontend-serving`, `python-lint-config`. Resource
names are free text in the schema.

## What the tickets could not be given

- WL-P0-011D cannot name request and response fields until WL-P0-007E defines them.
- V2 page tickets cite no observed behaviour, because no V2 page exists; they
  cite the nearest shipped page and its observed defects.
- Criteria that need a browser were written from observation, but the Playwright
  suite itself was not run during this pass.
