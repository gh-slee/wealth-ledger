# Public source and development publication

Normal imports, calculations and reports never use GitHub or upload financial
files. Git, GitHub CLI and the scripts below are optional development tools.
Owner-specific permissions live in ignored private guidance; this public document
explains the tool behavior, not a standing authorization to push.

## Public/private boundary

The public allowlist in `scripts/check_publication.py` admits reviewed code, tests,
synthetic examples, named example configs, documentation, fonts/licenses, hooks and
CI. Review a new path before extending it. Financial data, raw broker exports,
reports, backups, work directories, local settings, credentials, editor state and
private agent instructions are never public source.

`AGENTS.override.md` is ignored at every depth. The worktree manifest skips it,
but index/history checks explicitly reject the filename even if force-added.
The distinction is intentional: a private file may exist locally but must never
be committed. CI checks both the worktree manifest and index, so a tracked override
cannot be hidden by the source-manifest exclusion. See [agent setup](agent-development.md) for discovery and verification.

`.gitignore` does not untrack old files or remove old blobs. The guard scans the
**whole index** and reachable history, including deleted files. It rejects unknown
paths, symlinks, submodules, unresolved merges, common credentials/private keys,
machine-specific home paths and explicit private-fixture markers. Local author and
committer email must use a GitHub-provided `users.noreply.github.com` identity.
Historical commits additionally allow the exact GitHub system committer
`noreply@github.com`, while their authors still require the users.noreply domain.
This narrow privacy exception is not signature authentication.

**Pattern scans cannot prove absence of personal data.** Review the complete paths,
content and provenance; balances, names and ordinary prose may not match a pattern.
Never rename a real export as a synthetic fixture. Font/fixture provenance and
licenses need review too. CI runs after upload, so it cannot prevent an initial leak.

## Local review before publication

From the repository root, with locked dependencies installed:

```bash
python scripts/check_publication.py --worktree --manifest private/publication/worktree.json
python scripts/check_publication.py --staged --manifest private/publication/index.json
python scripts/check_publication.py --all-history --manifest private/publication/history.json
```

The worktree mode creates a source-only manifest, excluding intentionally private
files. Staged mode audits the whole Git index, not only changed files. History mode
requires a valid HEAD and fails closed if it cannot inspect it. `--outgoing origin/main`
can additionally inspect a range, but does not replace full-history review. Results
include path, size, SHA-256 and violations without printing credential matches.
Keep audit output private. Review `git diff --cached --check` and
`git diff --cached` as well. Stage explicit paths; never use broad `git add .` in a
checkout with financial state.

Before **each** owner-controlled push, present the exact staged/outgoing scope,
validation and privacy findings and obtain the approval required by local guidance.
Changed scope needs renewed approval. A previous push or `authorized = true` is not
proof of approval for a new scope. No automatic merge, force push or release.

## Optional publisher capability configuration

Copy `config/publish.example.toml` to ignored `config/publish.local.toml`. It contains
no credentials. Set the repository you maintain, host (`github.com`), remote,
feature prefix and `create_pr = true`. Keep `authorized = false` until intentionally
enabling the publisher under your own approval rules. The boolean is a repository
capability gate; the script cannot verify a conversation's human approval.

The fetch URL and every push URL must exactly match the configured target and be
credential-free HTTPS/SSH. The tool does not create repositories or log you in.
Authenticate GitHub CLI separately and use your GitHub-provided noreply identity.
Do not write tokens into source, URLs or chat. The remote default branch must be
known (`refs/remotes/origin/HEAD`); after verifying the remote, the maintainer can
refresh it with `git remote set-head origin --auto`. No global Git/Codex changes
are needed for this setup.

## Feature branch and pull request workflow

1. Complete only the requested implementation and relevant documentation/tests.
2. Review and deliberately stage the public paths, then commit the reviewed scope.
   Do not stage unrelated work.
3. Run the [pre-PR image gate](development.md#pre-pr-candidate-image-gate), including
   docs-only changes. Preserve the exact commit/image-ID evidence. Write a public-safe
   PR description into an ignored file, for example `private/publication/pr-body.md`,
   describing the problem, behavior and validation.
4. Generate a plan, present exact commits/files/checks/privacy to the owner and
   obtain any required approval before executing it.

```bash
python scripts/dev_publish.py \
  --branch feature/example-improvement \
  --message "Improve input validation" \
  --title "Improve input validation" \
  --body-file private/publication/pr-body.md
```

This example names a proposed branch; it does not create an example implementation.
Without `--execute`, the tool only plans and leaves branch/index/commits unchanged.
After approval, use identical arguments with `--execute`. Docker is required even
for documentation-only changes. The candidate check always invokes a build, permits
layer caching and records an immutable image ID; a failure stops before push/PR
creation. The publisher retains compatibility with reviewed staged inputs, but
owner rules requiring exact commit approval mean those inputs must be committed
before planning/approval. A final local commit may remain if its image check fails.
Manual publication must run the same gate explicitly; it is not a global GitHub
CLI/browser hook. The publisher verifies
local authorization, target, identities, index and full history before network
operations; confirms GitHub authentication/repository identity, fetches, rechecks,
runs the full unit suite, then checks again. Changed HEAD, branch, index or PR text
stops publication for renewed review. Only reviewed staged changes are committed;
the final committed source is built and smoke-tested by `check_pr_image.py`, outgoing
history is checked, a normal feature push occurs, and a PR is created or reused. If a Codex session creates a PR, attach it using that session's required app
tool; the publisher itself has no Codex dependency.

Tracked unstaged changes are rejected; untracked files are never auto-added. A new
branch may be created only from a default branch without extra local commits. To
continue an existing feature branch, switch to it deliberately first; the publisher
will not switch to unrelated existing work. It never pushes the default branch,
force-pushes or merges. It does not enforce a human approval gate cryptographically:
the operator remains responsible for following the applicable private rules.

If a stage fails, inspect current branch/index/remote state before retrying. The
tool does not roll back commits or delete work. A successful push followed by a PR
failure means the branch may already be public; retry on the reviewed feature
branch rather than force-pushing. Additional changes require renewed review.

## Local hooks and limitations

Optionally install the repository hooks (no global Git changes):

```bash
python scripts/install_git_hooks.py
```

`pre-commit` audits the full index. `pre-push` audits the full reachable history of
each proposed ref and rejects automatic branch deletion. Missing Git/Python or
incomplete checks block the operation. Hooks can be bypassed by a maintainer;
never treat them as a substitute for review or an upload-proof guarantee.

Audit exits: `0` passed, `1` violations, `2` unable to complete. Publisher failures
exit `2`. Tests use temporary synthetic repositories/mocked commands and do not
publish to a real remote or mutate a financial ledger.

## Local Python build artifacts

The [SDK guide](parser-sdk.md) documents an audited, minimal wheel/sdist build.
Its source allowlist is independent of Git ignore/index state; do not replace it
with a recursive checkout copy. Review artifact members with `scripts/check_packages.py`
as well as source/index/history before any separately authorized publication.
Building local artifacts does not publish them or authorize package-registry uploads.
