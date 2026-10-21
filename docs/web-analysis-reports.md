# Web analysis reports

**Analysis reports** is a readable edition of a published investment report, with
its tables, charts, analysis, methods and original downloads on the same page.
The overview dashboard remains a shorter summary. Opening either page is read-only:
it does not import data, fetch references, calculate a new valuation or publish.

## Read and download

1. Select a portfolio, then open **Analysis reports**. The initial selection is the
   latest publication in the library's server order.
2. Read its valuation cutoff and source evidence rail. Different source dates,
   carried holdings, observed subtotals, unknown values and unconfirmed BTC balances
   remain qualified. Publication time is separate from valuation time.
3. Use **Contents** to jump between the saved sections. Tables can be sorted by a
   column; longer tables can be filtered. Numeric sorting uses exact decimal
   comparisons of the displayed values, not binary floating point. Filtering does
   not change report totals or downloads. Wide tables scroll within their region.
4. Download `report.pdf`, `portfolio.ods` or `report.md` from the cover. **Download
   report ZIP** includes chart attachments needed by Markdown. Dataset CSV/JSON
   exports and their optional date filters remain available on the same page.
5. Expand **Evidence and attachments** for the remaining registered files.

The document follows the sections saved in that edition: multi-currency totals,
native-currency and account holdings, costs, concentration, company look-through,
classification coverage, cash, BTC acquisition/reconciliation, history, flows and
methods, where supported and present. New source-neutral reports retain their
observed-scope contract; they do not become complete wealth or portfolio returns
because they are displayed as a document. Unsupported or missing analyses are not
invented for older editions. ODS formulas remain spreadsheet functionality.

## Editions and history

**Report history** groups loaded publications by the same valuation instant and
frozen scope. Its latest entry is visible; earlier editions expand below it. A
scope change creates another group even at the same time. If a scope cannot be
established, editions stay separate. **Load more** fetches older pages; the group
count explicitly covers loaded data, not an asserted total across unseen pages.
The server order is retained within each group.

An edition is an output version, not another CSV import, month or financial
observation. Grouping never deletes reports or creates growth-chart points.
Each selection has a shareable-within-the-instance route:
`/app/<portfolio-id>/reports?report=<report-id>`. Authentication and portfolio
ownership are still required, including after refreshing or opening a deep link.

## Language, notices and appearance

Controls support en-CA, zh-TW and zh-CN. The saved document, chart images and
original downloads retain their publication language and assumptions; changing
interface language does not translate or rewrite them. The cover shows the
recorded report language, or Unknown if the edition has no trustworthy locale
metadata. A future-language setting affects future publications only.

**Report checks** summarizes error/warning/info counts. Expanding it shows grouped
messages, their stable codes, occurrence counts and affected account context.
Equal wording from two accounts does not lose either account when grouped.
The original document also retains its original quality/method sections.

**Appearance** offers Follow system, Light and Dark on both login and signed-in
pages. System follows OS preference changes. A manual choice persists only the
nonfinancial `wealth-ledger-theme` enum in browser localStorage; financial queries,
sessions and portfolio selections are never persisted there. Storage restrictions
fall back to an in-memory preference. Theme changes recolor native controls,
tables, notices and interactive charts. Saved PNGs/PDF/ODS retain their original
appearance and are not inverted or regenerated.

## Read contract and security

`GET /api/v1/portfolios/{portfolio_id}/reports/{report_id}/document` returns a
versioned `ReportDocument`, with a verified source Markdown artifact, original
locale, ordered sections and typed text/table/chart blocks. Its basis is
`saved_markdown`. The existing Python presentation model already feeds Markdown
and PDF; reading that frozen output preserves even historical wording without
replaying today's financial/presentation assumptions over old data.

The reader accepts only the emitted headings, paragraphs, pipe tables and local
`charts/<safe-name>.png` syntax. HTML and arbitrary links remain escaped text.
Only a PNG registered to that edition's own adjacent charts directory can supply
an image artifact ID. External URLs, traversal, other editions and unregistered
files never become image fetches. Images pass authenticated, portfolio-scoped
size/hash checks and a PNG MIME check before being shown with a temporary blob
URL; URLs are revoked on teardown. The CSP permits blob images, not blob scripts.

The Markdown reader has an 8 MiB input bound and limits sections, blocks, columns
and cells. Financial APIs use `no-store`, and query/blob state stays in memory.
An absent, unsupported or oversized saved Markdown document shows an explicit
reading error while preserving original download access. Integrity failures
remain errors. Legacy verification continues to mean migration-time capture,
not evidence of original publication authenticity.

Interactive alternatives currently cover account values and company exposure
in CAD, using exact saved DTO values. Their buttons state the unit. Other charts
show their verified original PNGs. No inferred historical samples, current quotes
or changing ETF downloads are introduced on a report read.

## Validation

Use the commands in [browser development](web-frontend.md) and [AGENTS.md](../AGENTS.md).
The document tests render invented three-locale reports and compare their saved
sections; source-publication and legacy-adoption tests exercise the same reader.
Browser tests cover grouped editions, deep links, three interface languages,
protected images/downloads, HTML escaping, session expiry, theme switching,
responsive overflow and accessibility. All instances and screenshots are synthetic.
Deployment of a rebuilt image is separate from changing the checkout.
