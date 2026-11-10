# Product context for agents: what the owner wants and how the app is used

Recorded 2026-11-10 from the owner's V2 brief and the discussion that followed
the UI/UX backlog pass. Read this before any product, UX or analysis ticket. It
states intent in plain words; it approves nothing. [ROADMAP.md](ROADMAP.md)
orders the work and each ticket holds its own scope. Open questions at the end
are waiting for the owner; do not resolve them by assumption.

## The job the product does

One person tracks all their investments in one place: stocks, bonds and ETFs
held at a broker, and Bitcoin bought through an exchange. They export files
from each institution, import them, and see what they hold and what it is worth
now, in the currency they choose, without giving the app any brokerage login.

The owner's judgement of the shipped application is that the flow is confusing
and the front page overwhelming. V2 is an overhaul for a pleasant, obvious flow.
Generic by design: nothing in core code or labels may be tied to one broker or
exchange. Institutions are plugins.

## The end-to-end flow the owner described

| # | The user does | The app does | Tickets |
|---|---|---|---|
| 1 | Registers | Creates one account with exactly one portfolio | WL-P0-005 (done), WL-P0-011B |
| 2 | Signs in | | WL-P0-011B |
| 3 | Enables the Wealthsimple and Bull Bitcoin plugins in the plugin store | Only enabled plugins are offered at import | WL-P0-006 (done), WL-P0-011C |
| 4 | Imports a first Wealthsimple holdings file | Parses, reconciles, stores facts in the database; does not keep the file | WL-P0-007, WL-P0-011D |
| 5 | Opens analysis | Shows reports and analysis from Wealthsimple alone | WL-P0-008, WL-P0-012A, 012B, 012D |
| 6 | Imports a Bull Bitcoin transactions file | Same pipeline | WL-P0-007, WL-P0-011D |
| 7 | Opens analysis | Analysis now includes Bitcoin, updated at once | WL-P0-012C, 012D |
| 8 | Any time later, imports newer files of either kind | Consolidates with stored data; analysis is current again | WL-P0-007 |
| 9 | Later enables a newly supported plugin (for example Questrade, TD) | That institution's tracking appears | WL-P1-003, WL-P2-001 |
| 10 | Presses Refresh, or waits | FX rates and Bitcoin, stock and ETF prices are fetched at intervals and on demand | WL-P0-009, WL-P0-012B |
| 11 | Looks at ETF exposure, or searches any ETF | Underlying holdings are fetched and refreshed, for held and unheld ETFs | WL-P0-010, WL-P0-012E, WL-P1-002 |
| 12 | Switches display currency | Every holding, chart and report follows; more currencies than CAD, USD, TWD | WL-P0-009, WL-P0-011E, WL-P0-012B |
| 13 | Presses Download | PDF, ODS or Markdown is generated then, from what is on screen | WL-P0-013A, 013B |

## Rules the owner set

- Analysis is always live from the database. Report files are generated only on
  download, never as a side effect of import. No "report edition" concept.
- Imported files are not stored. Their content is parsed into database records
  able to hold any source's data (a holdings snapshot and a purchase transaction
  alike). The approved design keeps snapshots and events as distinct typed facts.
- Each plugin translates its institution's file format and the app reconciles
  new data with what is stored (overlaps, duplicates, corrections).
- Bitcoin: track only what was acquired through imported purchase records.
  No opening balance, no earlier holdings, no spending, no income, no wallet
  checks. Approved "Option A": every accepted purchase is assumed still held and
  its estimated value is part of Total. Wording is generic: never "Bull
  purchases", never "opening", never "self-custodied".
- No recorded cash flows. Keep it simple.
- One portfolio per user. No "New portfolio".
- Left navigation has exactly these: Home, Stock/Bond Investments (with Exposures
  as its child), Crypto Investments, Total Investments, Import Data, Parser
  Plugin Store, App Settings, User Profile and Settings. Stock/Bond and Crypto
  appear when a matching plugin is enabled.
- The three investment pages carry charts, tables and analysis that are clear,
  concise, detailed and professional, in one consistent style.
- The home page must not show: "Evidence for this saved edition", "Partial
  source scope", "Carried forward", "Provided", "Next steps", "Saved evidence
  and checks", "Report edition".
- Exposure must show every country that has holdings, Taiwan included
  (fixed in WL-P0-001).
- The plugin store teaches how to write a plugin and submit it to the repository
  for review, and a user can test their own plugin locally before it is official.

## Decisions already taken after the brief

Recorded in the planning package and reflected in tickets: Python/FastAPI
modular monolith; PostgreSQL for V2 with safe migration from SQLite; canonical
data model with plugin adapters and a projection engine; plugins may later be
real API sources as well as files; README and docs must match what is shipped;
brand name not chosen.

Proposed and still awaiting the owner: invite-only registration by default;
plugin installation by the operator only, with local testing in a separate
developer instance instead of uploading code in the browser; ETF search for
unheld funds and the authoring tutorial delivered as P1; extra currencies only
when a data provider is chosen.

## How the shipped application is used today (for comparison)

Sign in with the owner account created on the host, create a portfolio, open
"Import & jobs", upload a Wealthsimple holdings CSV and/or a Bull Bitcoin orders
CSV, review the preview, confirm, wait for the worker to publish a frozen report
edition, then read Overview, Holdings, Exposure, History, Bitcoin and the report
reader, and download ODS, Markdown or PDF. Values are those saved at import; they
do not refresh. This is the flow V2 replaces.

## Where the tickets and the brief differ

| Brief | Current plan | Status |
|---|---|---|
| "Register a new user" | Invite-only by default; an admin issues an invitation link | Proposed, owner to confirm |
| "Parser Plugin Store" | Called "Data Sources" in WL-P0-011A and 011C, built as a short list | Naming and form to confirm |
| Test an unofficial plugin by enabling it | Local developer instance; no code upload in the browser | Proposed for safety, owner to confirm |
| Search any ETF, live | P1 (WL-P1-002); P0 covers held ETFs | Owner to confirm the priority |
| More than CAD, USD, TWD | WL-P0-009 currently recommends none until requested | Conflicts with the brief; owner to name currencies |
| Prices fetched automatically | Blocked on choosing a quote provider (WL-P0-009) | Owner decision |
| One transactions table | Typed snapshot and event facts | Approved deviation |

## Open questions for the owner

1. Who will use an instance: only you, your household, or strangers who
   self-register? This decides invite-only versus open registration and how much
   abuse protection the first release needs (WL-P0-019, WL-P0-007J).
2. Should agents still fix the shipped SQLite application (UX-P1-008 to
   UX-P1-015, UX-P2-006 to 008) while V2 is built, or put everything into V2?
3. Stock and ETF prices: is a free, delayed source acceptable, or a paid licensed
   one? How fresh must a price be (end of day, 15 minutes, near real time)?
4. Which display currencies beyond CAD, USD and TWD?
5. A Wealthsimple holdings file is a snapshot. When a newer file omits an account
   or a position, is that position sold (zero), or unchanged since last seen?
6. Value history: should the chart show only the dates you imported, or a daily
   line revalued with fetched prices between imports?
7. Bitcoin: if a file shows a sale or a withdrawal, ignore it (Option A) or warn?
   Are crypto positions held at the broker, or Bitcoin ETFs, shown under Crypto,
   under Stock/Bond, or both?
8. Do you want cost and unrealized gain shown where the import provides cost, and
   is broker cash part of Total?
9. Is "Parser Plugin Store" the name you want on screen, and is a simple list
   with enable switches acceptable while only two plugins exist?
10. Is testing your own plugin in a separate local developer instance acceptable,
    or must the running app accept an unofficial plugin?
11. Is ETF search for funds you do not hold needed in the first V2 release?
12. What does "professional" look like to you: name one or two products or
    reports whose charts and tables you want this to resemble.
