# Portable prompt: set up tracked tickets for parallel agents

Wealth Ledger's `tickets/` workflow was set up with this prompt. To use it in
another repository, paste everything below the line into a coding agent (Codex,
Claude Code, opencode or another) started in that repository. The reference
implementation is this repository's [`scripts/tickets.py`](../scripts/tickets.py),
[`tests/test_tickets.py`](../tests/test_tickets.py) and [README](README.md). If the
agent can read them, it should copy and adapt them rather than rewrite from scratch.

---

You are setting up an agent-agnostic planning and ticket system in this repository.
Several coding agents will use it at the same time: for example Codex, Claude Code
and opencode with DeepSeek Flash. Each works on a different ticket, and any agent
must be able to resume a ticket another agent started but could not finish (for
example after hitting a 5-hour or weekly usage limit). Follow this repository's own
instruction files (AGENTS.md, CLAUDE.md, CONTRIBUTING and similar). Where they are
stricter than this prompt, they win.

## 1. Survey before you write

- Read the instruction files, README, roadmap/TODO files, existing specs or ticket
  documents, open GitHub issues and PRs (if `gh` is available), recent git history
  and any local untracked planning or state directories.
- Inventory existing work: what is done, what is in progress (including
  uncommitted changes and unmerged branches) and what is planned. Note exact
  remaining steps for in-progress work.
- Do not modify existing in-progress work. Do your work on a new branch in a new
  git worktree created from the latest default branch.

## 2. Plan the project end to end

Write `tickets/ROADMAP.md` with:
- Current state in a few bullets.
- Phases from now to the product goal, with the tickets in each phase.
- A dependency graph (Mermaid is fine).
- **Parallel lanes:** groups of tickets that share no exclusive resource and can be
  worked at the same time, plus a suggested split across several agents today.
- Owner decisions and approvals that would unlock more parallel work.
- Any priority changes you made and how old roadmap/TODO items map to tickets.

Prioritize as P0 (critical path / must have), P1 (important next), P2 (later or
optional). Re-prioritize existing items where the evidence supports it and say why.
Split any ticket too large for one or two agent sessions into child tickets under
an `epic`. Split along file and contract boundaries so children can run in parallel.

## 3. One Markdown file per ticket

Create `tickets/<ID>.md` for every existing and new item, done ones included so
dependencies resolve. Use stable IDs such as `<PREFIX>-P0-001`, with an optional
letter suffix for children (`-007A`). Use this front matter, using only these
keys and values:

```yaml
---
id: ABC-P0-001
title: Short imperative title
priority: P0            # P0 | P1 | P2 (authoritative even if the ID prefix differs)
status: ready           # backlog | ready | in_progress | paused | in_review | blocked | done | superseded
type: feature           # epic | feature | bug | chore | docs | review | decision | research
parent:                 # optional epic id
depends_on: []          # ticket ids
resources: []           # exclusive resources, lowercase kebab-case
risk: medium            # low | medium | high | critical
size: M                 # XS | S | M | L | XL
agent_tier: standard    # any | standard | frontier  (minimum model capability)
gate: none              # none | owner  (owner approval needed before work)
gate_approval:          # filled only when the owner actually approved: "owner YYYY-MM-DD, scope"
review: self            # self | independent (a different agent session must review)
branch:
pr:
spec:                   # optional link to a longer spec
updated: YYYY-MM-DD
---
```

Body sections, in order: `## Goal`, optional `## Context` (links), `## Acceptance
criteria` (verifiable checkboxes), `## Plan` (checkbox steps, each small enough for
one session), `## Decisions needed` (required when blocked: numbered questions with
options and a recommendation), `## Handoff`, `## Log` (append-only dated lines,
`YYYY-MM-DD tool/model: what happened`).

`## Handoff` is the resume point and is overwritten at every checkpoint:

```
- State: done and committed / uncommitted and why
- Next step: the single next action
- Verify: exact commands proving the current state
- Gotchas: traps found so far
- Open questions: anything waiting on the owner
```

Tier guidance: `any` is for low-risk, well-specified chores, docs and tests that
fast or small models can do. `standard` is for normal features with clear
contracts. `frontier` is for security, money, data migration, concurrency,
auth or anything critical. Give each ticket the lowest tier that is safe.

## 4. Claim tool for concurrent agents

Add `scripts/tickets.py`, using only the Python standard library, with these commands:

- `check`: validate every ticket (required fields, enums, ID equals file name,
  known dependencies and parents, no cycles, required sections, blocked tickets
  have Decisions needed, owner-gated active tickets have gate_approval, no
  machine-specific home paths or secrets).
- `list [--priority] [--status] [--all]`: the board, with live claims.
- `next --tier <tier>`: claimable or resumable tickets at or below the tier.
  A ticket is claimable when its status is ready (or active with no live claim),
  its dependencies are done, its gate is satisfied, it is not an epic and none of
  its resources is held by another live claim.
- `show ID` / `resume ID`: ticket text (preferring the newer copy on its branch),
  the claim, branch commits and worktree `git status`.
- `claim ID --agent tool/model [--worktree]`: create
  `<git common dir>/agent-tickets/claims/<ID>.json` with an atomic exclusive
  create (`O_CREAT|O_EXCL`), then lock each resource the same way under
  `resources/`, rolling everything back if any lock fails. Using the git common
  dir means every worktree and every agent product on the machine sees the same
  locks with no server. Record agent, timestamps, branch, worktree, a unique
  `isolation_id` and a `port_base`. Write a secret token to the worktree's ignored
  `work/agent-claim.json` and store only its hash in the claim. With
  `--worktree`, create or attach `work/worktrees/<id>` on branch
  `ticket/<id>-<slug>` (use `--no-track`).
- `heartbeat ID [--note]`: refresh the claim; only the token holder may do it.
- `takeover ID --agent ... --reason ...`: allowed only when the heartbeat is
  older than `STALE_MINUTES` (default 120, overridable by environment), or with an
  explicit owner-approved flag. Record the previous owner in the claim.
- `release ID`: drop the claim and its resources.

Add tests that use a temporary git repository: a duplicate claim is refused, a
shared resource blocks a parallel ticket until release, dependency and tier
filtering work, heartbeat needs the owning token, takeover needs staleness and
records history, `--worktree` creates an isolated branch, and validation catches
cycles, unknown dependencies and private paths. Also validate the real
`tickets/` directory in the test suite so CI catches broken tickets. If the
repository has a publication or path allowlist, allow `tickets/*.md` and add tests.

## 5. Isolation beyond worktrees

Worktrees do not isolate runtime resources. Find every fixed port, database name,
Docker or Compose project name, queue, cache or temp path used by tests and dev
servers. Make each configurable from the environment, keeping current defaults.
Agents then use their claim's `isolation_id` and `port_base`. Each hard-coded
resource you cannot fix now becomes an `any`-tier P0 ticket and a warning in the
README.

## 6. Protocol README and instruction wiring

Write `tickets/README.md` covering: quick start (fetch, `next`, `resume`, `claim
--worktree`), the work loop (status to `in_progress`, then update Handoff, commit,
push and `heartbeat` after every meaningful step, because you may be cut off
any time), finishing (acceptance passes, then required independent review, then
`status: done` and `pr:` in the PR's final commit, open the PR, `release` after
merge), tiers, the parallel-safety mechanisms, cross-machine use (a pushed ticket
branch with commits not on main means owned elsewhere), stale takeover rules (confirm
no process still writes in the old worktree first; never take a live claim without
owner approval), the file format, and these rules:

- Edit only your own ticket file in a ticket branch. File new tickets for
  follow-ups. This avoids merge conflicts between parallel PRs.
- Only the owner grants `gate_approval` or answers Decisions needed. Never infer
  approval from priority, a roadmap or passing tests.
- Independent review means a different agent session. A different model name
  alone does not count.
- Ticket text may be public: no secrets, personal data, private paths or private
  transcripts.
- Agents never merge, force-push, release or deploy unless the owner says so.

Add a short section to `AGENTS.md` that points to `tickets/` and summarizes the
loop: next, claim with worktree, Handoff first, heartbeat and push at checkpoints,
own ticket file only, owner gates. Make sure every agent tool in use loads
AGENTS.md. Claude Code reads CLAUDE.md; if it does not pick up AGENTS.md in this
setup, add a CLAUDE.md containing `@AGENTS.md`. Codex and opencode read AGENTS.md.
Point old roadmap or TODO files at `tickets/` as the authority for status.

## 7. Finish

Run `tickets.py check`, the new tests and the project's normal checks. Commit on
your branch and push. Open a PR only if the project rules allow it. In your reply,
give the board summary and the tickets claimable now per tier. Include the owner
decisions that unlock more lanes and anything you could not verify.
