# Tickets and the parallel agent workflow

This directory is the single tracked backlog for Wealth Ledger. Any coding agent
(Codex, Claude Code, opencode with DeepSeek or another model, or a human) can pick
up any ticket, including one another agent started and could not finish. Several
agents can work on different tickets at the same time.

Nothing here depends on a particular vendor. The protocol is Markdown files, Git
branches and worktrees, and one standard-library script:
[`scripts/tickets.py`](../scripts/tickets.py). [AGENTS.md](../AGENTS.md) stays the
authority for safety, finance and publication rules. A ticket never widens those rules.

- [ROADMAP.md](ROADMAP.md) has the end-to-end plan, phases and parallel lanes.
- `python3 scripts/tickets.py list` shows the live board.
- `python3 scripts/tickets.py next --tier <tier>` lists the tickets you may claim.

## Quick start for an agent

Run all commands from a checkout of this repository. The script finds the shared
Git directory itself, so it works from the primary checkout or any worktree.

```bash
git fetch origin
python3 scripts/tickets.py next --tier standard
python3 scripts/tickets.py resume WL-P0-018
python3 scripts/tickets.py claim WL-P0-018 --agent opencode/deepseek-flash --worktree
```

`claim` creates or attaches `work/worktrees/<ticket-id>` on the ticket branch. Do
all work there, never in the primary checkout. Then:

1. Read the ticket's **Handoff** section first, then Goal and Acceptance criteria.
   Read only the docs the ticket links, plus AGENTS.md.
2. Set `status: in_progress` and `updated:`, add a Log line, and commit.
3. Work through the Plan checkboxes. After each meaningful step, update Handoff,
   commit (WIP commits are fine on a ticket branch) and run
   `python3 scripts/tickets.py heartbeat <ID> --note "<one line>"`.
4. Before you stop for any reason, write the Handoff (see below), commit and push
   the ticket branch. Assume you can be cut off at any moment by a usage limit.
5. When the acceptance criteria pass and any required independent review is
   recorded, set `status: done` and `pr:` in the PR's final commit, then open the
   PR using the repository PR rules. Because only the owner merges, the ticket reads
   `done` on `main` only after the merge. While the PR is open, its branch copy
   and the live claim show it as under review. If review requests changes, keep
   the claim and set `status: in_review` until the repair is pushed.
6. After the merge, run `python3 scripts/tickets.py release <ID>`. If the PR is
   closed without merging, set the ticket back to `ready` with a Log line.

## Capability tiers

Each ticket has an `agent_tier`. Pass your own tier to `next`; it shows tickets
at or below it.

| Tier | Typical agents | Tickets |
|---|---|---|
| `any` | fast or small models, for example DeepSeek Flash | Low-risk, well-specified chores, docs and tests with no financial, SQL, auth or migration semantics |
| `standard` | mid-size coding models | Normal features with clear contracts; medium risk |
| `frontier` | the strongest available models | Critical or high-risk finance, SQL/RLS, auth, migration, concurrency and recovery |

A smaller model may still *review* or *write tests* for a higher-tier ticket if a
ticket of type `review` says so. It must not implement one.

## Running several agents at once

Parallel safety comes from four mechanisms. All of them are enforced by the
script or by review, not by trust.

1. **One ticket, one writer.** `claim` creates
   `<git-common-dir>/agent-tickets/claims/<ID>.json` with an atomic exclusive
   create. A second claim on the same ticket fails, even if it comes from a
   different worktree or a different agent product on the same machine.
2. **Exclusive resources.** A ticket lists `resources:` such as `ingestion-schema-sql`
   or `frontend-shell`. Claiming locks each one atomically. Tickets that share a
   resource cannot be worked at the same time, which keeps two agents out of the
   same schema, migration order, locale catalog or contract.
3. **One worktree and branch per ticket.** Never share a worktree. Never check
   out another ticket's branch for writing.
4. **Isolated runtime resources.** Each claim records an `isolation_id` and a
   `port_base`. Use the isolation ID as a prefix for Docker/Compose project
   names, PostgreSQL test environments (`scripts/postgres.py test-environment
   --output work/pg-tests-<isolation_id>`), temp directories and queues. Use
   ports from `port_base` to `port_base + 99`. When running the browser suite
   in parallel, set `WEALTH_LEDGER_E2E_PORT` to your claim's `port_base` before
   running `npm --prefix frontend run test:e2e` in your own worktree. The browser
   suite uses port 8765 when the variable is unset.

Lanes that can usually run in parallel are listed in [ROADMAP.md](ROADMAP.md).

Claims are local to one machine. If agents work on different machines, the
pushed ticket branch is the shared record: before you claim, run `git fetch`, and
if `origin/<branch>` has commits not in `main`, treat the ticket as owned
elsewhere unless the owner says otherwise.

## Picking up interrupted work

A claim carries a heartbeat. If the heartbeat is older than
`WL_TICKET_STALE_MINUTES` (default 120), the previous agent is presumed stopped,
for example by a 5-hour or weekly usage limit.

```bash
python3 scripts/tickets.py resume WL-P0-007A     # ticket from its branch, claim, git state
python3 scripts/tickets.py takeover WL-P0-007A --agent codex/gpt-5.5 --worktree --reason "previous agent hit usage limit"
```

Before you take over, confirm that no process is still writing in that worktree. Then:

- Read Handoff and the last commits on the branch. Run `git status` in the worktree:
  uncommitted changes are the previous agent's unfinished step. Keep them.
- Re-run the Handoff **Verify** commands before trusting any claim in it.
- Add a Log line naming the former and new agents.

Never take over a live (non-stale) claim unless the owner tells you to
(`--owner-approved`). Time passing alone does not make a non-stale claim free.

## Ticket file format

File name equals ID: `tickets/WL-P0-007A.md`. The ID prefix shows the priority the
ticket was created with. The `priority` field is authoritative if it changes later.

```markdown
---
id: WL-P0-018
title: Make browser and dev-server test ports configurable for parallel agents
priority: P0            # P0 | P1 | P2
status: ready           # backlog | ready | in_progress | paused | in_review | blocked | done | superseded
type: chore             # epic | feature | bug | chore | docs | review | decision | research
parent:                 # optional epic ID
depends_on: []          # ticket IDs that must be done first
resources: [browser-test-harness]
risk: low               # low | medium | high | critical
size: S                 # XS | S | M | L | XL
agent_tier: any         # any | standard | frontier
gate: none              # none | owner
gate_approval:          # set only when the owner approved, e.g. "owner 2026-11-05, scope as written"
review: self            # self | independent
branch:                 # set when work starts
pr:
spec:                   # optional link to a detailed spec
updated: 2026-11-05
---
```

The body must contain these sections, in this order:

- `## Goal`: the user outcome in two to five sentences.
- `## Acceptance criteria`: checkboxes that can be verified.
- `## Plan`: checkbox steps small enough for one session each.
- `## Decisions needed`: required when `status: blocked`. Each question gives options
  and a recommendation. Only the owner answers.
- `## Handoff`: the resume point (format below).
- `## Log`: append-only dated lines, `YYYY-MM-DD agent: what happened`.

### Handoff format

Keep it current. Overwrite it at each checkpoint; the Log keeps history.

```markdown
## Handoff
- State: what is done and committed, what is uncommitted and why.
- Next step: the single next action, specific enough to start without re-reading everything.
- Verify: exact commands that prove the current state (tests, checks).
- Gotchas: traps found so far (sandbox limits, flaky tests, environment needs).
- Open questions: anything waiting on the owner (mirror into Decisions needed).
```

## Rules that keep the board consistent

- **Edit only your own ticket file** in a ticket branch. To change another ticket,
  for example to file a follow-up, create a new ticket file, or note it in your
  Handoff for the owner. This keeps parallel PRs from conflicting.
- **New tickets:** copy an existing file and use the next free number in that
  priority. `python3 scripts/tickets.py check` catches duplicate IDs and broken
  dependencies after a merge.
- **Gates:** `gate: owner` tickets need `gate_approval` before work starts. Only the
  owner grants it, in conversation with an agent, and the agent records the date and
  scope. Never infer approval from priority, a roadmap or a passed test.
- **Reviews:** `review: independent` means a different agent session than the
  implementer reviews the diff against the acceptance criteria. The reviewer records
  findings in the ticket Log, or in a linked `review` ticket. The same session
  cannot self-certify. Using a different model is welcome but does not by itself
  count as independence.
- **Public repository:** ticket text is public. Never write credentials, financial
  data, account names, personal paths or private approval transcripts. Detailed
  private evidence stays under ignored `work/`; reference it only by a relative path.
- **Done** means the PR is merged by the owner, required CI passed, and the
  capability docs are truthful. Agents never merge, force-push or deploy.

## Script reference

| Command | Purpose |
|---|---|
| `check` | Validate every ticket file (fields, enums, dependencies, cycles, sections, privacy). Runs in the test suite. |
| `list [--priority P0] [--status ready] [--all]` | Board with live claims. |
| `next [--tier any\|standard\|frontier]` | Claimable or resumable tickets for your tier. |
| `show ID` / `resume ID` | Ticket text (newest copy from its branch), claim and git state. |
| `claim ID --agent NAME [--worktree]` | Atomic claim plus resource locks; writes `work/agent-claim.json` in the worktree. |
| `heartbeat ID [--note TEXT]` | Refresh the claim from the owning worktree. |
| `takeover ID --agent NAME [--worktree] --reason TEXT` | Take a stale claim; records the previous owner. |
| `release ID` | Drop the claim and its resources. |

Agent names use `tool/model`, for example `codex/gpt-5.5`, `claude/opus-5.5` or
`opencode/deepseek-flash`. The board uses them to show who is working.
