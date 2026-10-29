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


## Repository role skills

The four reviewed public skills are
[PM](../.agents/skills/wealthledger-fintech-pm/SKILL.md),
[Architect](../.agents/skills/wealthledger-software-architect/SKILL.md),
[Developer](../.agents/skills/wealthledger-fullstack-developer/SKILL.md) and
[QA](../.agents/skills/wealthledger-qa-automation/SKILL.md).
Each references the single shared AGENTS.md and the canonical
[spec workflow](spec-development.md). Select an explicitly assigned role or an
authorized SDD stage. Discovery is availability, not approval to implement,
delegate or start four agents. No global configuration or runtime AI is required.

Only these four exact `.agents/skills/<role>/SKILL.md` files have Git traversal and
publication exceptions. Everything else under `.agents/`, all `.codex/`, private
overrides and local planning artifacts remain outside the public allowlist. Do not
add a broad exception or `agents/openai.yaml`. Git ignore matching can vary with
filesystem case behavior and `core.ignorecase`; ignoring alone is never publication
authorization. The guard requires literal allowlisted paths and actual component
spelling. Worktree inspection reads the four
candidates only after checking every component for regular-file/directory safety;
symlinks, including dangling file or ancestor links, fail before reading targets.
Index and reachable-history checks still reject forbidden force-added content,
even when later deleted. Public role prose participates in the English check;
private instructions remain excluded. Source-only Docker contexts and Python
package source/artifact allowlists exclude role skills independently.

In a fresh session, additionally ask it to list the four available role names and
descriptions without invoking them, explicitly read the assigned skill and its
shared references, then summarize its bounded responsibilities. Verify real
startup discovery in the intended checkout; file layout/tests alone do not prove
that a particular Codex session discovered skills. Keep discovery evidence distinct
from role execution, independent QA, remote claims and deployment.

## Shared writing skills

The tracked setup script and AGENTS.md travel with a clone or pull. The downloaded
skills do not: `.agents/skills/caveman/` and `.agents/skills/humanizer/` are ignored
local copies, and publication checks reject them even if force-added. The four
reviewed repository role skills above remain the only public skill exceptions.
No private override, maintainer home path or personal language preference is needed.

At the first development task in a new session, AGENTS.md asks the agent to run:

```bash
python3 scripts/setup_writing_skills.py --ensure
```

For each missing skill, the helper resolves the public upstream default-branch HEAD
and downloads the skill and license/notice files from that exact commit. This keeps
one installation internally consistent without pinning future installations to a
repository-managed version. Caveman comes from [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman);
Humanizer comes from [blader/humanizer](https://github.com/blader/humanizer).
It downloads text only and runs no upstream installer, proxy, hooks or code. Each
`_origin.json` records the resolved commit, retrieval time and file hashes. Do not
commit any downloaded directory or receipt.

Existing valid SKILL.md files are kept without a network request, including manual
local copies. Their printed hash identifies the current bytes; presence alone is
not proof of freshness, upstream origin or an editorial quality check. A malformed,
partial or symlinked installation is reported for inspection and is never replaced.
Interrupted downloads leave no partial new skill directory. Each skill installs
independently; a successful first download is kept if the second fails.

Check availability without downloading or writing:

```bash
python3 scripts/setup_writing_skills.py --check
```

Exit status 0 means both skills are present with expected discovery metadata;
1 means one is missing, and 2 means setup could not complete. Review local changes
before moving or removing one generated skill directory to request a newer copy,
then run `--ensure` again. This is latest-when-missing, not an automatic overwrite
of working instructions on every task. Upstream changes may require a reviewed
bootstrap adjustment if metadata, paths or licenses change. HTTPS verification
stays enabled; an unavailable network or denied permission must be reported.

Use Caveman for transient agent-to-agent coding handoffs. Keep exact evidence and
clear permission boundaries. Use Humanizer for human-readable prose, with the
reader's purpose deciding structure and detail. Formal contracts and audit records
retain their required information. Repository instructions take precedence over
third-party style defaults. Load a relevant skill once and apply it while writing;
no separate LLM pass, external editing service or runtime AI is required.

Codex can discover repository-local skills under `.agents/skills/`. Start a fresh
session in this repository after pulling changed AGENTS.md instructions. Ask it to
identify the shared writing section, run the offline check and name which skill
applies to an agent handoff versus a PR. Verify any private override explicitly
includes AGENTS.md. See [official skill discovery](https://developers.openai.com/codex/skills/).
Other agent tools can read the same files manually or through a thin adapter to
AGENTS.md; they may not discover them automatically. A pull does not execute setup
by itself, and files/tests cannot guarantee that every human or agent follows a
writing style. Contributors remain responsible for the final text. CI performs
mocked offline bootstrap/privacy tests and never needs to download these skills.

## PR authoring and updates

[AGENTS.md](../AGENTS.md) routes every new PR and description update to the
[canonical template](../.github/pull_request_template.md). Its required sections,
evidence categories and conditional review aids take precedence over Humanizer's
stylistic suggestions. Prefer focused Markdown bullets and grouped modules. Keep
public descriptions free of private context; public review summaries must not link
to local reviewer files or expose owner approval evidence.

Before drafting, inspect the actual target base, head, full branch diff, current
implementation and relevant docs. Gather the Developer's commands/results, actual
CI runs and independently verified QA/architecture outcomes. Preserve missing
checks as NOT RUN and running CI as PENDING. Test skips do not establish coverage;
Developer self-tests do not establish independent QA. For a small PR, one summary
sentence, two change bullets and compact evidence entries can be enough.

Save the complete final body in an ignored file and run:

```bash
python scripts/check_pr_description.py --body-file private/publication/pr-body.md
```

The standard-library checker reads requirements from the template. It checks
headings/order, summary and file bullets, and explicit evidence statuses. It ignores
headings in comments/fenced examples and rejects empty optional sections. It does
not judge prose, verify test/CI/review claims, prove module coverage or authorize
publication. Review those separately and keep existing image/privacy/approval gates.

Use the exact validated file with `gh pr create --body-file` or
`gh pr edit --body-file`; an API tool must receive the same validated Markdown in
its body field. Never assume that GitHub inserts the template when a body is supplied.
Do not use commit-message autofill. After implementation or review changes, revise
the relevant sections as a whole, revalidate evidence/issue links and rerun the
checker instead of appending an unstructured status log. A lookup alone does not
update an existing PR: the local publisher explicitly sends its title and body.

In a fresh-session check, additionally ask the agent to locate the canonical PR
template, distinguish the four evidence categories and explain why Humanizer may
not collapse them into prose. File tests can verify routing and format behavior;
they cannot guarantee that every agent or contributor follows the standard.
