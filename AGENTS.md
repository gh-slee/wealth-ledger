# Agent development guide

Wealth Ledger is a local-first Python 3.12+ investment ledger. It imports supported
Wealthsimple/Bull CSVs into SQLite and generates ODS, Markdown and PDF reports.
Production downloads, calculations, charts and report prose are deterministic code;
no runtime LLM, Codex or local LibreOffice is required. An optional FastAPI API
supports bounded uploads, offline preview and isolated Huey/SQLite report jobs.
The React/TypeScript/Vite UI remains planned; advanced financial forms stay in the CLI.

## Working agreement

- Inspect the working tree and relevant code before editing; preserve existing work.
- Follow the requested scope. Roadmap entries do not authorize implementation.
- Read detailed documents according to the task using the map below, not all docs
  before every edit. Keep implemented behavior distinct from planned interfaces.
- Use English for public code, identifiers, comments, canonical documentation and generic examples.
  Preserve intentional locale catalogs, compatibility strings and source/user text.
  Personal conversation preferences belong only in the ignored override.
- Keep public guidance here; vendor integrations should reference it rather than
  duplicate it. Private preferences and session state never belong in this file.
- Start new sessions in this repository. If subagents are explicitly requested,
  provide applicable shared/private rules and bounded context; do not assume they
  inherit the conversation. Never include private context in public artifacts.

## Verified commands

Run from the repository root using Python 3.12+ and the locked dependencies:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python examples/demo.py --output work/demo-review
.venv/bin/python scripts/check_language.py
.venv/bin/python scripts/check_publication.py --worktree
.venv/bin/python scripts/check_publication.py --staged
.venv/bin/python scripts/check_publication.py --all-history
```

An existing equivalent virtual environment is fine. For Web changes install
`requirements-web-test.lock` and run the same full suite; core-only installations
skip optional API tests. `scripts/web.py` manages trusted host initialization/upgrade/serve/worker.
`python scripts/docker_context.py --output work/docker-context` prepares a new
source-only image context. Container acceptance is explicitly opt-in:
`WEALTH_LEDGER_DOCKER_TEST=1 PYTHONPATH=src python -m unittest discover -s tests -p 'test_web_docker.py' -v`.
It requires a running Docker daemon and uses only unique disposable synthetic resources.
There is no frontend build or installable package build yet. CI runs Linux/Python 3.12 tests
and offline synthetic report demos for default/proxy policies and three locales.
Use focused tests while iterating; report changes also need affected formula/cache,
ODS/PDF presentation and locale checks. Documentation edits do not require real
portfolio updates. Report the checks actually run and any gaps.

## Safety and implementation boundaries

- Use `Decimal` for finance and eight-decimal satoshi precision for BTC. Unknown
  values are not zero. Do not infer contributions from holdings or purchase spend.
- Preserve original evidence, stable IDs, append-only revisions, source dates,
  completeness, historical FX/prices and frozen report editions. Missing inputs
  are not evidence of zero activity. Do not revalue history or invent observations.
- Preserve backup/lock/atomic-submit and operation recovery contracts. Data commit
  and report publication are separate; resume a saved operation after failure.
- Use synthetic isolated fixtures/tests. Never run updates, migrations or report
  regeneration on a real portfolio merely to inspect it; read saved manifests.
- Keep accounts, wallet data, user settings, credentials and private instructions
  out of code, fixtures, screenshots, commits and public descriptions. Never
  derive public defaults from a maintainer's private configuration.
- `actual_only` is the default BTC cost policy; `bull_average_proxy` is opt-in.
  It estimates costs and cannot establish actual acquisition costs or resolve gaps.
- Preserve en-CA/zh-TW/zh-CN contracts, stable localization keys/sheet IDs and unknown
  semantics. Official ETF data needs effective/fetch dates, hashes and parser
  versions; partial/unresolved coverage must remain visible.
- Stage reviewed paths explicitly. Before publication inspect staged content and
  reachable history with the guards; do not bypass checks. Publication needs the
  applicable owner approval. Never auto-merge, force-push or publish a release.

## Task-specific references

- Setup, tests and CI: [CONTRIBUTING.md](CONTRIBUTING.md), [development](docs/development.md).
- Discovery, private overrides and fresh sessions: [agent setup](docs/agent-development.md).
- Imports, dates and recovery: [user manual](docs/user-manual.md), [core API](docs/core-api.md).
- BTC quantities/costs/events: [reconciliation](docs/btc-reconciliation-plan.md).
- Reports and ETF analysis: [report spec](docs/report-spec.md), [ODS](docs/workbook.md).
- Locale changes: [i18n contract](docs/i18n-plan.md).
- Web security, host commands and experimental containers: [Web operations](docs/web-operations.md), [imports/jobs](docs/web-imports.md).
- Planned work: [TODO](TODO.md), [source adapters](docs/source-adapters.md),
  [self-hosted web app](docs/self-hosted-webapp.md).
- Publication/privacy: [publishing](docs/publishing.md), [SECURITY.md](SECURITY.md).
