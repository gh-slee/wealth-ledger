# UX-P0-002 design brief: evidence status and next actions

Status: **Implemented and verified locally; not yet merged or deployed**

Parent: [UX-P0-002](ux-p0-002-status.md). Visitor mode: **Operate**.
Visual authority: [DESIGN.md](../DESIGN.md), existing Overview and synthetic gallery.
Product facts: [PRODUCT.md](../PRODUCT.md). This refines the existing workbench.

## Job and outcome

An owner returning after an import or an irregular update needs to know which
saved figures they are reading, what the supplied evidence establishes, and the
most relevant next action. Success is identifying an evidence limitation or an
unfinished job without mistaking it for a new valuation or a verified wallet.

The primary interaction is **open the relevant existing workflow**. Merely reading
or expanding status never imports, reconciles, retries, publishes or fetches prices.

## Selected direction

Keep the existing heading, edition/currency controls, source-date rail and saved
portfolio amount. Insert one evidence-status section before the analysis charts,
using three layers rather than repeating all report notices in the summary:

1. **Summary:** a concise statement and counts of items needing review and unknown
   evidence. Never a whole-portfolio health score or an unconditional success badge.
2. **Next actions:** at most three prioritized groups initially, each with a reason,
   its scope/date when known, and one destination. Always show the full group count
   and an explicit control to reveal all remaining groups, including further errors.
3. **Evidence:** expandable source dates, reason codes, account/record contexts,
   repeated occurrence counts and informational disclosures. Keep every saved notice
   accessible. An informational limitation can remain visible without an action.

Separately show **Current processing** when relevant jobs exist. Label this as live
operational state, outside the selected edition's evidence summary. Selecting an
older edition does not change current jobs or make them part of that old report.

Proposed hierarchy (descriptive wireframe, not a shipped screenshot):

```text
Overview                         Display currency | Saved edition
Source evidence dates            Valuation cutoff | Publication time
Saved portfolio value            Scope of supplied sources

Current processing               Only when pending / unresolved
  Data saved; report not published                   [View job]

Evidence for this saved edition  Review / unknown counts
  Source dates differ. Figures mix observation times. [Review sources]
  BTC quantity is estimated; wallet not confirmed.    [Financial records]
  Contribution coverage is unknown.                  [Financial records]
  [Show all next actions]   [Expand saved evidence and checks]

Existing history chart | Account breakdown | Other analysis
```

The example rows are conditional, not claims every portfolio has those issues.
Use plain factual copy; no prompts to trade, price forecasts or investment advice.

## Frozen evidence versus current operations

| Concern | Existing evidence | Proposed behavior / unavailable fallback |
|---|---|---|
| Selected edition | `ReportView.report.id`, `valuation_as_of`, `published_at`, `verification_basis` | Label observation cutoff and publication time separately; migration capture is not original publication proof. |
| Latest publication | Portfolio-scoped report summaries | Distinguish latest published edition from selected historical edition. Fetch failure is unavailable, not no reports. |
| Source timing | `source_dates[].provider`, `as_of`, `usage`; supported structured saved basis/checks | Preserve snapshot/order/observation meanings. Different dates alone do not prove stale prices or carried sources. Show carried-forward only when saved evidence says so. No arbitrary age threshold. |
| BTC quantity | Supported `btc.quantity_status`, `quantity_basis`, `valuation_blocked` and saved checks | Distinguish estimated/declared/blocked/unknown quantity. A declaration is not independent wallet verification; no numeric gap without structured evidence. |
| Contributions / returns | Supported `source_basis` coverage fields and saved checks | Distinguish recorded flows from complete coverage. Missing/unsupported fields or empty flows mean unknown, not zero contributions or eligible returns. |
| Saved checks | `issues` severity, code and available contexts; original `findings` | Stable codes drive known actions. Unknown codes remain readable with a generic details destination. Never parse translated prose into financial facts. |
| Current processing | Owner/portfolio-scoped `JobView.id`, `status`, `updated_at`, `error_code` | Separate current operational time from financial observation time. Loading/error is explicit; no changes to frozen report evidence. |

The current report DTO does not guarantee a numeric wallet reconciliation gap,
coverage intervals or structured reasons for every historical edition. Do not fill
those gaps by joining today's declarations into old reports. Prefer existing fields;
if a missing structured fact is necessary, add a narrow, typed, read-only projection
with proven provenance and legacy fallback. No ledger schema migration is proposed.

## States, ordering and navigation

| State | Summary and destination |
|---|---|
| No reports | Keep P0-001 first-use guidance; processing can explain that the first publication is pending. No zero portfolio cards. |
| Report loading / failure | Existing loading or retry state; do not render an empty/healthy evidence summary. |
| Differing source dates | Explain which dates and uses differ; expand the existing source-date evidence. Missing uploads never imply no activity. |
| Estimated / unknown BTC | State the supported quantity basis; go to Financial records for an explicit declaration. Do not invent a balance ID or assume a fee. |
| Unknown acquisition cost / contribution coverage | State which conclusion is unavailable; go to Financial records or saved report details as applicable. No forced data entry. |
| `queued`, `running` | Current processing with job link; retain the last saved report amount. |
| `data_committed`, `report_failed` | Distinguish saved data from unpublished report; open the saved job and its supported recovery controls. Never suggest reimport as a generic fix. |
| `interrupted`, `needs_review` | Current processing needs review; link to that job. No automatic retry or promise that retry is allowed. |
| No known saved issues | Say no issues are recorded in supplied evidence, while retaining unknown/not-applicable scope. Do not claim complete wealth or a confirmed wallet. |
| Unsupported provider / unknown reason / absent date | Readable provider fallback and saved text; explicit unavailable date/meaning. No parser-specific app branch or invented explanation. |
| Job query fails | Operational state unavailable with retry; saved report can still be read. |

Prioritize blocked publication/review errors, then evidence limiting interpretation,
then informational detail. Use stable code plus applicability, scope/account/record
identity when grouping actions; preserve every distinct context and repeated count.
The existing notice grouper groups severity/code/message and retains contexts;
new action grouping must not silently change or discard that evidence. Sorting must
be stable across locale changes; translation text is not an action identifier.

## Layout, accessibility and constraints

Use existing panels, buttons, focus treatment and light/dark tokens. On narrow
screens stack the reason and destination; wrap dates, account names and source
labels. Dense tables remain in expandable evidence, not a new dashboard tile grid.
The visible summary never disappears just because details are closed.

Use native expandable controls with descriptive names, keyboard access, correct
expanded state and visible focus. Text explains severity alongside color. Avoid
moving focus or announcing the whole page on each job poll; announce meaningful
operational changes politely. Preserve en-CA, zh-TW and zh-CN keys, decimal strings,
user timezone rendering and scoped query-cache clearing on logout/portfolio switch.

## Implementation and acceptance after confirmation

1. Define a pure, typed status/action mapper over verified frozen fields and a
   separate current-job input. Document supported reason codes and unknown cases;
   add only a narrowly necessary read model after reviewing its provenance.
2. Add the bounded Overview section and navigation to existing records/jobs/report
   evidence. Preserve saved-report reading, editions and import approval contracts.
3. Verify synthetic mixed dates, carried-forward evidence, unknown costs/flows,
   estimated/declared BTC, structured gap and missing-gap states, multiple accounts,
   unknown providers, no reports, failed/loading requests and every current job
   status. Prove old editions never inherit new financial facts or live job meaning.
4. Verify owner/portfolio isolation, logout/switch cache clearing, read-only behavior,
   no quote/source-fetch side effects, all three locales, keyboard, mobile and both
   themes. Run relevant unit/API/browser checks and refresh affected synthetic
   README images after the actual UI implementation.

No whole-app redesign, new financial formulas, inferred fees/contributions,
retroactive payload rewriting, personal data access, deployment or publication is
part of this brief. The proposal adds no runtime AI or local office dependency.

## Delivery boundary

The implementation follows the three-layer section, separate current-processing
area and initial limit of three action groups with explicit access to all groups.
Existing DTOs do not expose numeric wallet gaps or complete cash-flow coverage
intervals; these remain unavailable rather than inferred. No new read model or
ledger migration was needed. Completion evidence belongs in the parent ticket;
merge and deployment remain separate from local implementation.
