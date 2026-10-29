# Spec-driven development

[AGENTS.md](../AGENTS.md) is the single shared instruction authority. This document
specifies the human-operated workflow; [capability status](capability-status.md)
records current product facts. A roadmap, discovered skill or proposed spec never
authorizes implementation. Use ordinary Markdown, Git branches and, when authorized,
GitHub Issues/PRs. No scheduler, command-line dispatcher or custom orchestrator is
installed or required.

## Evidence and roles

A spec records ID, revision, content SHA-256, outcome, scope/non-goals, priority,
size, risk/rationale, dependencies, decisions/ADRs, paths/contracts/exclusive
resources, financial/locale invariants, acceptance and negative cases, independent
expected values, verification owners and rollback. Priority, size, risk, review
state and execution state are separate fields. Links must identify accessible
sources; private approvals/evidence stay local and are never pasted into public
records. Requirements and plans express intent; source/tests establish capability;
Issues record remote execution, and PRs record reviewed implementation.

| Role | Responsibility and bounded handoff |
|---|---|
| PM | Problem/value, priorities, journeys/states, acceptance and independent business expectations; hand exact revision to Architect/human. |
| Architect | Source-backed contract, security, precision, migration and isolation review; return unresolved decisions or hand risks to Gate A. |
| Human | Gate A approves the exact spec; Gate B reviews concrete implementation evidence. Publication and deployment authorization remain separate. |
| Dispatcher | One designated human-operated coordinator checks approval/baseline/conflicts serially and records sole ownership. It does not invent approvals. |
| Developer | One approved, reserved scope; implementation, self-tests and current documentation; hand exact diff/evidence to independent QA. |
| Independent QA | Independently derive/check expected results, negative/fault/user acceptance and evidence; report defects, retest and hand to Gate B. |

Role guidance lives in exactly four repository skill files:
[PM](../.agents/skills/wealthledger-fintech-pm/SKILL.md),
[Architect](../.agents/skills/wealthledger-software-architect/SKILL.md),
[Developer](../.agents/skills/wealthledger-fullstack-developer/SKILL.md),
[QA](../.agents/skills/wealthledger-qa-automation/SKILL.md).
Use an explicitly assigned role or an authorized SDD workflow. Discovering these
files does not launch four agents. Delegate only with explicit authorization;
scale independent review to risk. A low-risk text edit need not run four concurrent
roles; financial/auth/migration changes require relevant independent review. A
coordinator adopting several perspectives must disclose that; Developer self-tests
and a different model name alone do not establish independent QA/oracles.

## Gate A: exact revision before READY

Review states are DRAFT, NEEDS_ARCH_REVIEW/NEEDS_REVIEW, CHANGES_REQUESTED,
APPROVED, REJECTED or SUPERSEDED. Agent-authored human approval fields stay null
until there is actual human evidence. Gate A records reviewer, revision, content
hash, approval reference/time, outcome, financial semantics, dependencies,
applicable ADR/open decisions, risks, negative/independent test plan and rollback.
Recompute the hash before readiness. Any material spec change increments revision
and changes hash, invalidates approval/READY, and returns for human review. A
historical approval for another revision or scope is insufficient.

Execution states are NOT_READY -> READY -> CLAIMED -> IN_PROGRESS -> IN_REVIEW ->
DONE. BLOCKED and PAUSED_QUOTA retain ownership. READY requires Gate A plus accepted
dependencies on the current integration baseline and a dispatcher conflict check;
it is not inferred from priority or a passed test. Drift in baseline/dependencies
requires revalidation; material outcome/contract drift requires renewed Gate A.

## Serialized reservations and Issues

One dispatcher performs the following sequence without another concurrent grant:

1. Inspect the latest available integration SHA, exact spec/hash/approval and
   dependency acceptance. Record freshness; if remote freshness is unavailable,
   state that limit and do not claim a remote check occurred.
2. Inspect every open, BLOCKED and PAUSED_QUOTA reservation, including other specs.
   Deny a duplicate spec owner or overlapping exclusive path/contract/resource.
   Worktrees do not isolate DBs, roles, ports, queues, caches, mocks or secrets.
3. Reserve one owner, branch/worktree and bounded scope. Record spec/revision/hash,
   human reference/time, base SHA, owner/dispatcher, status, Issue/PR references,
   paths/contracts/exclusive resources, isolation IDs, handoff owner and next action.
   Record absent resources as not applicable with reason; never include credentials,
   financial inputs or machine-specific private paths in a public Issue.
4. Re-read the recorded reservation before granting the Developer permission to
   write. One spec has one writer/branch/worktree/PR. Shared schema/migration
   changes have a single integration owner and explicit order.

For an authorized remote workflow, keep the current reservation and transitions in
one canonical Issue; link its PR and update the Issue before granting work. GitHub
labels/comments are human records, not an atomic lock or race-proof lease. If
coordination ownership is lost or the record disagrees with the writer, stop new
grants/writes until one dispatcher reconciles it.

Local-only approval can instead use a durable ignored reservation record under
`work/`. It must contain the same fields and be inspected serially; record Issue
and PR as null. This is local ownership, not an Issue claim, remote approval or
publication consent. Before moving to remote execution, obtain required remote
write approval, reconcile all local/remote owners, create/update the authorized
Issue and transfer the reservation explicitly. Never start a second writer during
that transition. Do not publish private approval transcripts or local state.

## Pause, transfer and resume

Before quota/context interruption, save spec/revision/hash/approval, branch/base/
HEAD, diff, test commands/actual results, synthetic fixture/oracle versions,
unresolved defects, reserved resources, current owner and exact next action.
PAUSED_QUOTA and BLOCKED retain the reservation; time passing, a quota reset or
an apparently idle chat never frees it.

Transfer requires confirmation that the old writer and any writing process are
stopped, its pending writes are fenced/cancelled, worktree/diff/evidence are
reviewed, and the dispatcher records former/new owner and resource transfer before
granting work. If the old writer cannot be stopped or ownership cannot be verified,
keep the claim paused; do not issue a replacement grant. On resume, revalidate
current ownership, exact approval/hash, baseline/dependencies and resource isolation
before the next write. A transferred former owner cannot resume on its old grant.

## Review, Gate B, merge and DONE

Developer evidence names exact source/base/HEAD and diff, synthetic fixture/oracle
versions, environment, commands, actual outcomes and NOT RUN limitations. QA
independently checks the approved outcome and relevant negatives/fault/security
boundaries, records defects and retests repairs. Stop the Developer writer for the
review handoff; repairs return through the same reservation rather than a second
writer. Architect reviews changed high-risk contracts. Update README/capability/
manual/SDK/API/deployment guidance as applicable; do not claim planned work shipped.

For PR authoring, use the [canonical template](../.github/pull_request_template.md)
and [authoring workflow](agent-development.md#pr-authoring-and-updates). Developer
handoffs include the exact base/HEAD, meaningful modules/interfaces changed, actual
commands/results/counts/skips, CI links/status, compatibility/rollback constraints
and NOT RUN gaps. QA/Architect handoffs identify independently checked scope,
expected results, outcomes and unresolved risks separately from Developer evidence.
Only verified public-safe summaries belong in the corresponding PR categories;
private authorizations, reviewer files and transcripts remain local. Human Gate B
and the existing independence/approval requirements are unchanged.

Before Gate B, revalidate the latest integration baseline, relevant tests, docs,
privacy/index/reachable-history audit and actual integration CI. Follow the
[pre-PR candidate image gate](development.md#pre-pr-candidate-image-gate) after the
final reviewed clean commit, including docs-only work. Record immutable image,
context and HEAD evidence. An unavailable/failed required check blocks the
corresponding submission; record the gap rather than substitute a real instance.
Gate B is explicit human review of the concrete PR and source/test/independent-QA/
docs/CI evidence. Exact push approval, PR publication, merge, release, deployment
and private financial migration retain their applicable separate authorizations.
Never auto-merge or force-push.

An implementation may remain locally IN_REVIEW with null Issue/PR and no remote
CI. It is not DONE. DONE requires approved acceptance, actual independent QA,
required checks, human Gate B, authorized merge with PR/merged SHA and integration
CI recorded, truthful public capability docs and dispatcher claim closeout.
Deployment/migration is separately approved and never follows from DONE alone.

## Synthetic examples

These examples are protocol illustrations, not real claims or approvals.

- SYN-101 revision 1 has hash H1 but human review names revision 2/H2: leave
  NOT_READY. Recompute/review the actual revision; do not copy the old approval.
- SYN-102 revision 1/H3 has a human reference and accepted baseline B1. Dispatcher
  D reserves owner A on branch `feature/synthetic-status`, exclusive resource
  `public-docs-agent-rules`, local record with null Issue/PR. Tests use a disposable
  temporary directory; DB/ports/jobs are not applicable to this documentation scope.
  A second SYN-102 claim is refused. SYN-103 requesting the same resource is also
  refused even on another worktree. Unrelated isolated work needs its own approval.
- A pauses SYN-102 at SHA C1 with a failing synthetic negative test and next command
  recorded. Owner B is refused while A is paused. After A and its writing processes
  stop, D reviews the diff and records transfer to B. A's later quota reset does
  not authorize resume. B rechecks hash/baseline/resources before repairing.
- B's self-tests pass and independent QA records the synthetic oracle and negative
  cases. The work stays local IN_REVIEW until remote publication is authorized.
  A local passing image receipt is not remote CI, a merged SHA or deployment.

For startup discovery and the four-file publication boundary see
[agent development](agent-development.md); for public/private review see
[publishing](publishing.md). Keep optional development agents outside the
deterministic application runtime.
