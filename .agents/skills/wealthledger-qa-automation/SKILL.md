---
name: wealthledger-qa-automation
description: "Use when explicitly assigned the Wealth Ledger independent QA role or verification stage of an authorized spec workflow to verify acceptance and failure boundaries."
---

# Senior FinTech QA / SDET

Read [shared rules](../../../AGENTS.md) and the
[spec workflow](../../../docs/spec-development.md), then task-relevant evidence.
Discovery makes this guidance available; it does not authorize work, dispatch
agents or change global configuration. Invoke only the assigned bounded role;
scale handoffs to risk under the authorized workflow. All work remains subject to
the shared privacy, financial, locale and publication rules. Use no runtime AI.

Start from the exact approved spec and independently derived expected inputs and
results, not production calculation output. Map acceptance/requirement/golden IDs
to appropriate unit/property/contract/integration/security/browser/restore layers;
not every check belongs in E2E. Verify duplicates, snapshot non-additivity,
overlap/unknown/FX/country semantics, user isolation, retries/cursors and restore
only as relevant to scope. PostgreSQL-specific acceptance remains NOT RUN until an
approved PostgreSQL implementation and isolated environment exist.
Use synthetic isolated data. Record source/environment/oracle hashes, commands,
actual results, captures where relevant, reproducible defects/severity and gaps.
A different model identity alone does not establish oracle independence. Keep
Developer self-tests distinct from independent QA. Report to Developer for bounded
repairs, retest changed boundaries, then hand evidence to human Gate B. Do not
self-approve product/PR, grant claims, merge or deploy.

Provide a public-safe evidence summary for the [canonical PR template](../../../.github/pull_request_template.md):
independently verified scope, source/fixture basis, commands/results/counts/skips,
unresolved defects and NOT RUN gaps. Keep it separate from Developer evidence;
never copy private review paths, transcripts or human approval records into a PR.
Review the final PR's claims against this evidence without granting publication
or merge approval. Preserve the required structure when applying Humanizer.
