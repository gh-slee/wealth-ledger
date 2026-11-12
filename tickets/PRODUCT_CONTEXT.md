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

## Confirmed on 2026-11-10 after discussion

| Topic | Decision |
|---|---|
| Delivery | Reach a usable V2 MVP as soon as possible. The owner is a real user and will give feedback from daily use. MVP scope and order are in [ROADMAP.md](ROADMAP.md) |
| Price data | Pluggable provider adapter. Bitcoin near real time from a public exchange API; FX from official daily sources; stocks, ETFs and bonds through an adapter the instance operator configures with their own API key, typically 15 minutes delayed or last close. Every value shows its "as of" time. The provider is chosen after a verification spike in WL-P0-009 |
| Sales in an exchange file | Tracked quantity is purchases minus sales reported by the same exchange file. Funding rows and withdrawals to the user's own wallet change nothing. A one-line notice appears when sales were counted |
| Where an asset appears | By asset class, not institution. A Bitcoin ETF is a security (Stock/Bond, and "Bitcoin through ETF" in Exposures). Coins held directly are Crypto. Total counts each holding once |
| Cost and gain | Shown where the source provides cost: live market value minus book cost. No cost means a dash, never zero. Bitcoin cost is the sum of purchase spending |
| Cash | Broker cash is in Total as its own "Cash" line, separate from securities |
| ETF lookup | Held ETFs: full underlying holdings, refreshed automatically, in P0. Searching an ETF the user does not hold: P1 (WL-P1-002) |
| Account absent from a newer broker file | Kept unchanged; the import preview asks "keep, or mark closed?". A position missing inside an account the file does cover is sold |
| Price sources | Bitcoin: Coinbase Exchange public API. FX: Bank of Canada daily rates plus Frankfurter for other currencies. Stocks, ETFs and bonds: pluggable adapter with the operator's own key, provider chosen after the WL-P0-009 spike |
| Unofficial market data | Included in the first V2 release as an optional adapter the operator enables (WL-P0-009A). It can break without notice and its terms of use are the operator's responsibility |
| Visual direction | Consumer-clear top, analyst depth below: large value with change, full-width chart with range buttons, key figures, allocation, holdings table, deeper analysis. Same skeleton on Stock/Bond, Crypto and Total. Layout patterns only; nothing copied from another product |
| Registration | Invite-only by default, with an administrator switch that opens self-registration. The switch is built after the MVP |

## Price data: what was found, and what is not known

Searched on 2026-11-10; figures come from secondary comparisons that disagree
with each other, so WL-P0-009 must verify them on the providers' own pages.

- Free tiers of the usual keyed providers are small and licensed for personal
  use: Alpha Vantage about 25 requests a day; Twelve Data about 800 a day with a
  delay reported as 15 minutes by one source and four hours by another; Finnhub
  about 60 calls a minute with disputed "real-time" status.
- None of the sources confirmed coverage of Toronto-listed securities. This is
  the first thing to test, because the built-in broker format is Canadian.
- FX: Frankfurter serves daily rates for many currencies without a key; no
  keyless source with intraday rates was found. The repository already uses the
  Bank of Canada Valet API.
- Bitcoin: the repository already uses the Coinbase Exchange public API.
- Many self-hosted trackers rely on unofficial market-data endpoints with broad
  coverage and no key. They can break without notice and their terms are
  unclear. If offered at all, such an adapter should be optional and off by
  default; that is an owner decision.

## Reference products for the "professional" look

Review sites consulted on 2026-11-10 (several are affiliate-funded, and no
Reddit thread was retrieved, so this is not a measure of what Reddit prefers):
Ghostfolio is the usual pick for a free self-hosted tracker; Sharesight for
performance, dividends and tax reports; Snowball Analytics for dividend income;
getquin for a broad free tier; Empower for free net-worth tracking in the US.
The owner finds Ghostfolio's interface too simple and prefers Wealthsimple's.
Confirmed direction: a consumer-clear top (one large
value with its change, a wide value chart with range buttons, a short row of
key figures) followed by denser analyst sections (allocation, holdings table
with cost and gain, exposure). Layout patterns only; no other product's assets,
colours or wording are copied.

## Owner answers recorded on 2026-11-11

| Topic | Decision | Consequence |
|---|---|---|
| Existing data in the SQLite application | Not migrated. V2 starts empty and the user imports their files again. The old application stays untouched and is where old reports are read | WL-P0-014 is a guide and a verification test, not a conversion tool. WL-P0-020 is P2 |
| Days between two imports on the value curve | Use the previous import's quantities with each day's closing price, and mark those days as estimates | WL-P0-009D. Nothing else (return, contribution, period gain) may be derived from estimated days |
| Platforms verified for release | Apple Silicon Mac with Docker Desktop. Linux amd64 through CI only; nothing else is claimed | WL-P0-015 |
| Post-MVP tickets | Gate A approved for WL-P0-009B to 009E, 010A, 010B, 014 and 015. Refresh: Bitcoin every 5 minutes, securities every 15 minutes in market hours, manual at most once a minute, daily when idle. Currencies: CAD, USD, TWD, EUR, GBP, JPY, AUD, CHF, HKD, SGD, CNY, KRW | Those tickets |
| Review | Agents review automatically; the owner reviews last on GitHub and merges | Reviews rule in [README.md](README.md); WL-P1-011 adds a reviewer in CI |
| Project name | Kurafolio: kura (the kanji U+8535), the storehouse where a family kept its valuables, plus "folio". Rename everything, old names stop working, done alone before parallel work. The README explains the name | WL-P0-024 |
| When the MVP is usable | The pull request of WL-P0-021 must say so, with the start command and first-use steps | WL-P0-021 |

## Still open

1. The named unofficial market-data endpoint, to be proposed by the WL-P0-009A
   spike and approved by the owner.
2. The official keyed quote provider, to be proposed by the WL-P0-009E spike and
   chosen by the owner.
3. The CI reviewer's service, spending limit and secret (WL-P1-011).
4. P1 and P2 tickets are refined after the owner has used the MVP.

Answered on 2026-11-10: WL-P0-007C's six questions (all recommendations accepted,
WL-P0-007K folded in); WL-P0-007J option (b); one bundle with the shell chosen
from the API version, served by the V2 application; unofficial adapter off by
default; Gate A for the eighteen MVP tickets.
