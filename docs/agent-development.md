# Agent-assisted development

[AGENTS.md](../AGENTS.md) is the single repository-wide source of shared agent rules.
Agents are optional development tools; no application feature needs an LLM.
Use [CONTRIBUTING.md](../CONTRIBUTING.md) for setup and
[development.md](development.md) for verification procedures.

## Official discovery

Codex discovers instructions when a session starts. At each directory from the
project root to its current working directory it selects at most one file:
`AGENTS.override.md` first, otherwise `AGENTS.md`, then configured fallback names.
Global guidance may also apply. A same-directory override replaces the shared file
in discovery; it does not automatically include it. This repository needs no global
configuration changes or custom fallback filenames.

Start a new local session with this repository as its project/current directory.
Changing into it during an existing chat does not prove startup discovery occurred.
After changing instructions, use a fresh session to verify discovery. See
[official AGENTS.md discovery](https://developers.openai.com/codex/guides/agents-md).

## Optional private owner guidance

`AGENTS.override.md` is ignored at every directory depth and explicitly denied by
the publication guard. Before creating one in another checkout, verify its ignore
rule first; an ordinary clone does not contain another owner's private guidance.

```bash
git check-ignore -v -- AGENTS.override.md
git ls-files -- AGENTS.override.md
```

The first command must identify the repository ignore rule; the second must print
nothing. An ignored path already tracked in Git is not protected by `.gitignore`.
Never force-add an override. Begin its content with this exact line:

```text
Before working, explicitly read ./AGENTS.md.
```

Keep personal conversation preferences, owner authorization boundaries and a short
current-state section there. Record current branch/commit, verified checks and their
scope, unfinished work and pending decisions. Revalidate branch/commit and replace
stale state instead of appending transcripts. Keep credentials out of it. Do not
paste its contents into issues, commits, PRs, shared links or public logs. Public
roadmap facts belong in TODO/topic docs, not private session state. Do not introduce
custom OWNER.md/HANDOFF.md discovery or agent-memory conventions.

A saved publication configuration is a tool capability gate, not evidence of
current owner consent. If private rules require approval for each push, show exact
files/commits, validation and privacy findings and obtain that approval first.
Changed scope requires new approval. Never infer approval from a previous session.

## Worktrees, clones and other agents

Official **local Codex-managed worktrees automatically copy an ignored
AGENTS.override.md**. No `.worktreeinclude` entry is needed for it. This does not
apply to ordinary clones, remote worktrees or manually created Git worktrees.
Files already present are not overwritten and source symlinks are skipped; verify
the result and its current state rather than assuming freshness. Do not use a broad
copy rule to transfer private CSVs, databases, credentials or local settings. See
[official worktree behavior](https://developers.openai.com/codex/app/worktrees).

For an ordinary clone/manual worktree, the owner must deliberately provision the
private override through a trusted local action. Confirm it is ignored/untracked
in the destination before copying, then update its branch/commit context. A public
clone without it follows only shared/global guidance and the current task; it must
not invent the original owner's preferences or publication authorization.

Vendor instruction files, if needed, should be thin adapters pointing to AGENTS.md;
retain genuinely tool-specific settings, not a second copy of project rules.
Only use subagents when explicitly requested. Give each the applicable shared rules,
necessary private constraints and bounded task context. Do not assume full chat
inheritance or expose private data in a public/remote agent context.

## Fresh-session verification

1. Open this repository as the project and start a **new** Codex session. For the
   CLI, `codex --cd /path/to/wealth-ledger` selects the intended repository.
2. Before editing, ask the following (do not request the full private file):

   > Without modifying files or accessing financial data, list the instruction
   > files discovered at startup and the files you explicitly read. If a root
   > AGENTS.override.md exists, follow its opening instruction to read ./AGENTS.md.
   > Summarize the project stack, one real test command, the private conversation
   > language and publication approval boundary. Report the current branch/commit
   > and any conflict with saved state. Do not quote private state or credentials.

3. In an owner checkout, verify the answer identifies the root override as the
   discovered file and AGENTS.md as explicitly read, and correctly states both
   shared constraints and the owner's private language/approval rules. A header
   labeled AGENTS.md alone does not prove which same-directory file was selected.
4. In a clean public clone without an override, expect shared AGENTS.md guidance
   only; absence of private owner rules is expected. Verify ignore/untracked status
   separately with the commands above. Repeat for any worktree actually used.
5. If the answer is incomplete or stale, inspect the selected project directory
   and any applicable overrides/size limits, then restart. Do not solve it by adding
   global fallback conventions or publishing private instructions.

File/guard tests can verify layout and leak protection. They cannot prove that a
particular fresh Codex session or a newly created worktree read/copied the files;
perform the corresponding check when that session/worktree is actually created.
