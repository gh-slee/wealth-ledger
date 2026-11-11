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

## Owner answers recorded on 2026-11-10

These are decisions. Tickets that contradict them are wrong and must be updated.

| Topic | Answer | Consequence |
|---|---|---|
| Who uses an instance | One self-hosted instance serves multiple users | Tenant isolation and per-user data stay P0. How a new user gets an account is still open (below) |
| Shipped SQLite application | Do not change it. All effort goes into V2; V1 was built before the use case was planned | UX-P1-008 to UX-P1-015 and UX-P2-006 to UX-P2-008 are superseded; their findings are criteria in the V2 tickets |
| Display currencies | Convert to other popular currencies at the latest exchange rate | WL-P0-009 must deliver a currency list beyond CAD, USD and TWD; its "none until requested" recommendation is withdrawn |
| Position missing from a newer broker snapshot | Treat as sold | Reconciliation and positions (WL-P0-007, WL-P0-008); see the refinement proposed below |
| Value history | A daily line revalued with fetched prices, not only import dates | WL-P0-009 needs historical daily prices and FX; WL-P0-012A needs a daily series |
| Price refresh | The app can refresh any stock, ETF or bond the user holds, close to real time, so values and charts are current | No hard-coded symbol list; WL-P0-009 |
| Plugin store name and form | "Parser Plugin Store"; a simple list with enable switches is fine | WL-P0-011A, WL-P0-011C |
| Who can add plugins | Only official plugins: written by the owner or contributors, reviewed and merged in the repository. Users cannot create, upload or enable their own | The brief's "test your own plugin in the app" is dropped. WL-P1-003 becomes a contributor guide and test harness for pull requests |

## Recommendations awaiting the owner's confirmation

The owner asked for a recommendation on each. None is approved yet.

1. Price data. Free and truly real-time data for arbitrary stocks and ETFs, with
   the right to serve it to several users, is not generally available. Proposal:
   Bitcoin near real time from a public exchange API; FX from an official daily
   source plus a free intraday source where one allows it; stocks, ETFs and bonds
   through a provider adapter that the instance operator configures with their
   own free-tier API key, typically 15 minutes delayed or last close. Every value
   shows its "as of" time. A paid real-time provider can be plugged in later
   without changing pages. Provider names and current terms must be researched
   and verified before coding; none is asserted here.
2. Missing positions. Treat a position as sold only when the newer file covers
   its account. If a whole account is absent from the file, keep it unchanged and
   ask at preview "Account X is not in this file: keep it, or mark it closed?",
   because a file may be exported for one account only.
3. Sales in an exchange file. The Bull Bitcoin export has an order-type column
   (the synthetic example holds "Funding" and "Buy Bitcoin"), so it is not
   buy-only by format, and other exchanges will report sales. Proposal: tracked
   Bitcoin equals purchases minus sales reported by the same exchange file;
   funding rows and withdrawals to the user's own wallet change nothing. Still no
   opening balance, wallet check or income. A one-line notice appears when sales
   were counted.
4. Where an asset appears. By asset class, not by institution. A Bitcoin ETF is a
   security: Stock/Bond, and "Bitcoin through ETF" in Exposures. Coins held
   directly appear under Crypto, whether the record came from an exchange plugin
   or a broker plugin. Total counts each holding once.
5. Cost and gain. Show book cost and unrealized gain where the source provides
   cost (the Wealthsimple holdings file does), computed as live market value
   minus book cost. Where a source gives no cost, show a dash, never zero. For
   Bitcoin, cost is the sum of purchase spending.
6. Cash. Include broker cash in Total as its own "Cash" line, separate from
   securities, so Total matches what the broker shows.
7. ETF lookup. First release: full underlying holdings for every ETF the user
   holds, refreshed automatically. Searching an ETF the user does not hold stays
   P1 (WL-P1-002).
8. Registration. Invite-only by default, with an administrator switch that opens
   self-registration for instances meant for the public.

## Still open

1. How a new user gets an account on a multi-user instance: an invitation from
   the administrator, open self-registration, or the switch proposed above.
2. A visual reference for "professional": a product or report whose charts and
   tables the three investment pages should resemble.
3. WL-P0-019: build a thin end-to-end V2 slice first, or finish each layer fully.
