# Contributing

Wealth Ledger welcomes synthetic parser fixtures, financial regression fixes,
translations, documentation and portability improvements. Discuss new financial
models or source-adapter contracts before implementation. An independent trusted
parser registry, nonbooking CLI/API source plans, installable core and author SDK
are implemented. The [v2 canonical foundation](docs/source-ingestion.md) supplies the separate data-only API; the default v2 CLI/browser workflow now implements
financial preparation, mapping, exact approval and source-neutral publication.
See the [product review and priority tickets](docs/product-ux-review.md) for remaining
UX and analysis work. Optional API/worker workflows are implemented. See [TODO.md](TODO.md).

## Development setup

Use a source checkout and Python 3.12+. For the installable core/SDK and synthetic
plugin use [the packaging guide](docs/parser-sdk.md); no PyPI publication is claimed.
From the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python examples/demo.py --output work/demo-review
```

On Windows use `.venv\Scripts\python.exe` and set `PYTHONPATH` using your shell.
CI currently validates Linux/Python 3.12; this is not a claim of full Windows or
macOS acceptance. See [development procedures](docs/development.md) for focused
tests, report validation and the exact CI commands.

## Optional Web development

Install `requirements-web-test.lock` for API/security tests and run the same unittest
suite. Core-only installations intentionally skip optional Web tests. The API uses
FastAPI/Pydantic, pwdlib Argon2id, opaque sessions and an isolated metadata SQLite DB;
it must not import private ledgers or add runtime AI. See [Web operations](docs/web-operations.md)
for trusted host initialization and implemented endpoints.

Docker tests are opt-in and require a daemon. They build a minimal inspected context,
create uniquely named synthetic resources and clean up only those resources. Never
use a real instance for container/restart/security tests. Uploads/jobs have synthetic interruption and container acceptance tests; the React workflow has a dedicated synthetic browser fixture. See
[browser development](docs/web-frontend.md) for locked npm installation, API types,
unit/browser tests and accessibility. Keep broader release acceptance visible.

## Change expectations

- Follow [AGENTS.md](AGENTS.md) for the shared project constraints.
- Use English for public code, comments and canonical documentation.
  Program-owned report text supports en-CA, zh-TW and zh-CN. Canonical manuals are English;
  complete translated documentation editions are separate work.
- Financial values use Decimal/satoshis. Preserve unknown/zero distinctions,
  immutable evidence, explicit source timing and contribution coverage.
- Test with synthetic records and isolated temporary projects, never a personal
  ledger or a renamed broker export. Official-format fixtures must be minimal,
  synthetic and properly attributed; do not commit full downloaded responses.
- Update affected contracts when behavior changes. Report changes need affected
  formula/cache and ODS/PDF checks; do not regenerate real financial reports for
  documentation work. Locale changes follow the [i18n guide](docs/i18n-plan.md).
- Substantial UI changes must update affected README screenshots and captions.
  Follow the [screenshot maintenance guide](assets/readme/README.md#when-to-refresh-screenshots)
  using isolated synthetic data and visual/privacy review.
- Keep roadmap/acceptance facts in public docs; personal preferences, authorization
  and current-session state belong in an ignored private override.

## Pull requests

Use a feature branch. Describe the concrete problem, resulting behavior, validation
and limitations. Run relevant tests and the [publication/privacy checks](docs/publishing.md)
before publication. After the final reviewed commit, run `python scripts/check_pr_image.py`
for every PR/update, including docs-only changes; Docker must be available. See the
[isolated candidate gate](docs/development.md#pre-pr-candidate-image-gate). This builds
a local candidate without deploying it. Never attach private inputs, reports, credentials or session
transcripts. Stage explicit reviewed paths rather than `git add .`.

Agent-assisted contributors can use [the repository setup guide](docs/agent-development.md);
agents are optional development tools, not application dependencies. Owner-specific
publication approval is separate from a local tool's repository authorization.

Code and documentation contributions must be compatible with the MIT license.
Bundled fonts and dependencies retain their own terms; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
