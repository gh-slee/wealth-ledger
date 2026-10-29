# Parser SDK: build, install and test

The [default parser import workflow](source-projections.md#default-daily-workflow)
prepares explicit approval through the regular CLI/browser, including optional
BTC-only and saved-data inputs. The legacy CLI requires `--native-import`; its
projection guard remains necessary on canonical workspaces. See the workflow guide
for saved contexts, corrections, reference caches and migration boundaries.

SRC-003 provides an installable Python core, one shared version-1 contract,
`wealth_ledger.source_testing`, and an independently packaged synthetic parser.
Everything runs in code. No runtime LLM, local LibreOffice or institution login is
required. No package has been published to PyPI by this work.

**The v1 SDK example is for nonbooking source plans.** Its plans retain
`ingestible: false` and `booking_blocker: protocol_v1_not_bookable`; successful
normalization is not financial import. The same installed core also provides the
implemented [protocol-v2 pipeline](source-ingestion.md) and
[default financial preparation/approval workflow](source-projections.md#default-daily-workflow).
Wealthsimple and Bull Bitcoin use pure v2 built-ins through that workflow, including
source-neutral valuation and publication. Compatible externally installed v2 parsers
can use the same pipeline after explicit host enablement and acceptance; the v1
example does not silently become v2. Only the two specified real CSV formats are
built in; do not advertise arbitrary bank or exchange exports. See
[the first-use/plugin explanation](getting-started.md#how-parser-plugins-work-now).

## Optional domain-v1 development types

`wealth_ledger.domain` supplies a separate [strict fact contract](canonical-domain.md)
and explicit one-way saved parser-v2 archive bridge. It does not register parser API
3, replace `source_protocol`/`source_v2`, upgrade a v1 parser or alter entry points.
The bridge requires caller-supplied UUID/listing/account/leg-role mappings and always
returns `ingestible=False`; it never invokes the adapter. Exact original archives
remain recoverable when the new candidate is blocked. These standard-library
modules are additive development interfaces, not a new install, financial routing,
PostgreSQL, provider or deployment capability.

## Build local artifacts

Use Python 3.12+. These commands are run from a reviewed source checkout. On Windows
use each environment's `Scripts\python.exe` instead of `bin/python`.

```bash
python3.12 -m venv .venv-build
.venv-build/bin/python -m pip install -r requirements-build.lock
.venv-build/bin/python -m build --no-isolation --outdir work/sdk-dist
.venv-build/bin/python -m build --wheel --no-isolation examples/parser-plugin --outdir work/sdk-dist
```

The default core build produces a source distribution, then builds its wheel from
that distribution. Build tools stay in a separate environment: setuptools startup
`.pth` hooks are deliberately rejected by the parser runner's environment checks.
Do not install build tooling into the runtime environment. The backend uses pinned
[setuptools](https://setuptools.pypa.io/en/stable/build_meta.html) through
[PyPA build](https://build.pypa.io/en/latest/).

`build_backend.py` stages only audited Python modules, exact locale catalogs,
README/license notices, public font resources and canonical company aliases. It
builds from a fresh temporary tree, independently of Git's index and ignore rules.
Private workspaces, reports, backups, local configuration and agent overrides are
excluded even if present or accidentally staged. Symlinks and privacy violations
in selected inputs fail the build. Review source before building: a Python backend
and plugins are trusted executable code, not a security sandbox.

The wheel contains locale catalogs, licensed fonts and canonical aliases under its
own installation. It does not ship the React build or checkout `scripts/` wrappers.
The supported full Web UI remains the source-built Docker image. For original
financial CLI commands, continue using a checkout and an explicit private workspace.
Installed programmatic core users must supply a private workspace; the default
never writes into site-packages. Editable installation is intentionally unsupported.

## Independently installed acceptance

Use a new disposable environment, not a daily ledger's environment:

```bash
python3.12 -m venv .venv-sdk
.venv-sdk/bin/python -m pip install -r requirements-web-test.lock
.venv-sdk/bin/python -m pip install --no-index --no-deps work/sdk-dist/*.whl
python scripts/check_packages.py --artifacts work/sdk-dist --python .venv-sdk/bin/python
```

The wildcard above selects the two wheels just built; use their explicit filenames
in shells without wildcard expansion. Do not mix unreviewed wheels into that folder.
Runtime dependencies are installed from the existing lock first; `--no-deps` does
not waive dependency requirements. The independent example requires core version 0.1.0 and API
version 1. The same core also packages the separate v2 foundation; it does not
silently upgrade a v1 parser. Both must be updated/retested together when the contract changes.

Acceptance audits core wheel/sdist and example-wheel members and compares code/resources to reviewed
public inputs. It imports installed modules outside the checkout, tests real entry
points and shared class identity, runs synthetic author fixtures and installed
API/isolated-worker acceptance, verifies CLI receipt revalidation, also runs v2 canonical foundation tests from the installed wheel, and renders
ODS/Markdown/PDF offline in en-CA, zh-TW and zh-CN. Temporary test ledgers/reports
are deleted. This verifies synthetic operation, not a user's portfolio or deployment.

## Write a parser

Start with [the independent example](../examples/parser-plugin/README.md) and
[the canonical contract](source-adapters.md#implemented-protocol-surface-src-001).
Import dataclasses from `wealth_ledger.source_protocol`; do not vendor copies.

1. Declare stable provider/adapter IDs, API/adapter/export versions and supported kinds.
2. Detect necessary format features from bytes. Ambiguity needs explicit selection.
3. Normalize with Decimal, aware source times, source-issued IDs/revisions and
   currency/network-qualified identities. Preserve unknowns as `None`, not zero.
4. Declare partial/complete scope from actual evidence. Row count does not prove
   completeness. Do not infer contributions from purchases or balances.
5. Return `AdapterRegistration(ProviderInfo(...), adapter)` from a no-argument factory.
6. Publish its metadata under entry-point group `wealth_ledger.source_adapters`.
   Package publication is an independent maintainer action, not performed by the tool.

`check_contract(adapter, raw)` validates detection/metadata/normalization and exact
replay, returning a small digest/count result. `check_rejected(...)` requires a bad
fixture to fail via ValueError or structural validation; implementation errors
propagate. `record_index(batch, raw)` exposes validated provider/account/kind/source
identities for overlapping-export and revision assertions. These helpers do not
perform ledger deduplication, resolve revisions or match transfers.

The example covers exact headers/markers, BOM, stable overlap, explicit corrections,
unknown versus zero cost, partial scopes, invalid timestamps/currency/numbers,
duplicate IDs and common-IO smoke checks. Core toolkit tests also exercise transfer
references, unknown fees and BTC satoshi precision. Add source-specific malformed,
pending/cancelled, fee/cash-counterpart and privacy cases. Smoke checks cannot prove
side-effect freedom; audit every plugin and dependency. Use synthetic fixtures only.

The example's deterministic `fetched_at` equals source time and carries a warning.
It does not assert a real retrieval time. V1 has no host parse context; new adapters
should use [v2](source-ingestion.md) and its default financial approval workflow.
V1 remains separate and nonbooking. Never invent dates or financial values to fit v1.

## Explicit native enablement

After reviewing/installing a pinned plugin into the same runtime used for parsing,
create a private host JSON file (for example `work/example-parser-host.json`):

```json
{
  "schema_version": 1,
  "enabled": [{
    "distribution": "wealth-ledger-synthetic-parser",
    "version": "0.1.0",
    "entry_point": "synthetic",
    "adapter_id": "synthetic.holdings"
  }],
  "bindings": []
}
```

Save this invented input as `work/sdk-input.csv`:

```csv
format,account,id,revision,supersedes,change,as_of,symbol,market,currency,quantity,value,cost,scope_revision
synthetic-holdings-v1,demo-account,position-001,r1,,original,2024-01-31T16:00:00-05:00,DEMO,XTSX,CAD,1.25,125.00,,scope1
```

```bash
.venv-sdk/bin/wealth-ledger-source-parsers work/sdk-input.csv --config work/example-parser-host.json > work/sdk-plan.json
.venv-sdk/bin/wealth-ledger-source-parsers work/sdk-input.csv --config work/example-parser-host.json --verify work/sdk-plan.json
```

Windows uses `Scripts\wealth-ledger-source-parsers.exe`. The equivalent checkout
wrapper remains `python scripts/source_parsers.py`. Keep receipts private. For Web,
the host administrator writes `<instance>/admin/source-parsers.json`; the API never
enables Python packages from browser uploads. Stop API/worker before changing the
installed environment, deploy identical code/configuration to both, restart, then
create fresh plans. Stale fingerprints must not be bypassed.

## Derived Docker image

The existing source-built image already supplies the shared core under `/app/src`.
Build the example wheel above, then create a separate minimal directory containing
only that reviewed wheel and this Dockerfile. `BASE_IMAGE` must identify your
reviewed local base image built with `scripts/docker_context.py`, not an invented
public image tag:

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY wealth_ledger_synthetic_parser-0.1.0-py3-none-any.whl /tmp/wealth_ledger_synthetic_parser-0.1.0-py3-none-any.whl
RUN python -m pip install --no-index --no-deps --no-cache-dir --no-compile /tmp/wealth_ledger_synthetic_parser-0.1.0-py3-none-any.whl
USER 10001:10001
```

Keep the wheel's actual filename: pip validates wheel filenames. No core wheel is needed in this source image. For a real plugin,
review/pin all additional dependencies and include their wheels explicitly; do not
use `--no-deps` to conceal missing dependencies. Configure both Compose services
to use the same derived image and remove their source `build` blocks. Do not mount
site-packages or install Python code into the financial volume. Keep the host-owned
parser configuration private in the instance's persistent admin directory.

To verify the source image and example together using disposable synthetic state:

```bash
python scripts/docker_context.py --output work/sdk-image-context
docker build --tag wealth-ledger-sdk-base:test work/sdk-image-context
python scripts/check_plugin_image.py --base-image wealth-ledger-sdk-base:test --wheel work/sdk-dist/wealth_ledger_synthetic_parser-0.1.0-py3-none-any.whl
```

This creates/removes only a uniquely named derived test image, runs seven example
and API/worker tests with no network, a read-only filesystem and temporary state,
and never mounts a financial volume. The supplied base image is retained. These
commands need a running Docker daemon; CI also runs them on Linux. Source images
use `python -m wealth_ledger.source_cli` rather than the wheel-installed console.

Retain nonroot/read-only operation, resource limits, isolated workers and backup
contracts. Restoring data never installs missing plugins; reading frozen reports
can work without them, while new plans need compatible installed code. There is no
marketplace, automatic download or plugin upload form. See
[Web operations](web-operations.md) and [backup rules](web-backups.md).

## Explicit-context built-in previews (SRC-004B1)

The installed core also includes `source_builtin.registrations()` and
`source_context_pipeline`. They support the current Wealthsimple/Bull grammars and
explicitly enabled compatible v2 plugins. The v1 example package and its commands
remain unchanged. See [context schema and CLI/API examples](source-ingestion.md#explicit-context-previews-src-004b1).
These developer preview commands do not confirm financially. The separate default
source preparation/approval path supports compatible v2 financial publication. Do not claim generic
bank/exchange support from the ability to register or normalize a parser.

Installed acceptance copies only named public synthetic tests/fixtures outside the
checkout. It exercises 35 canonical foundation tests, 29 built-in/context tests, 22 frozen-submission tests, 29 source-model tests and 33 legacy/wallet projection tests,
the independent v1 plugin tests, real child/CLI/API paths and three report locales.
Build artifacts remain subject to source/member audits before any publication.

The installed core also exposes `wealth-ledger-source-ingestion` for explicit frozen
preview/confirmation and receipt-only recovery. Its [B2 guide](source-ingestion.md#frozen-submission-and-recovery-src-004b2)
requires exact account mapping review and the no-report acknowledgement. This does
not change the v1 example plugin's nonbooking contract. Installed acceptance invokes
the new console and verifies its actual child/CLI data-only flow outside checkout.

The installed core includes [C1 internal projections](source-projections.md), tested
without loading a parser. The separate [C2 compatibility function](source-projections.md#legacy-and-wallet-compatibility-src-004c2)
adds identity-bound legacy/wallet/frozen-history read projections. C3A uses this model for BTC
opening/balance/event declarations; its 25-case suite also runs outside the checkout
against installed wheels. These data-only edits do not enable daily import/report
cutover. V1 parser plans remain nonbooking.


C3B adds 35 installed source-report acceptance cases, covering explicit saved-data
valuations, frozen histories and three-locale ODS/Markdown/PDF/charts outside the
checkout. The source-report API consumes verified facts rather than calling an
adapter. This does not turn the v1 example into a bookable plugin or enable ordinary
CLI/Web publication; see [C3B semantics and remaining C3C gates](source-projections.md#source-report-payloads-and-frozen-valuations-src-004c3b).


## Independent v2 reporting example

The example wheel additionally registers `synthetic_v2` /
`synthetic.holdings-v2` from `synthetic_parser.v2`. Its separate
`synthetic-holdings-v2` marker avoids ambiguity with the unchanged v1 example. It
exports invented partial positions with original IDs and unknown/zero costs. This
is not a real bank/broker format and does not establish complete cash/activity.
Enable that exact entry point/version in trusted host configuration; no plugin is
automatically enabled by an uploaded CSV. The v1 example remains nonbooking.

The installed test runs real CLI preview, mapping approval, confirmation and ODS/MD/
PDF publication, then verifies an unchanged published retry after removing the
original CSV/plan/configuration. The opt-in source-report API has no provider
branch for this adapter. See [C3C1 commands and limits](source-projections.md#frozen-source-report-publication-src-004c3c1).
The container plugin test runs the same independent cases without a financial volume
or external network; its temporary filesystem is 256 MiB for report artifacts.
Default CLI/Web integration is implemented; additional real provider formats remain separate work.

The installed example acceptance now also drives `synthetic_v2` through the opt-in
source-report API and real isolated workers, then selected-report JSON, holdings
export and original three-format ZIP. The installed/derived-image plugin suite has
13 cases. No financial volume or external network is needed. Ordinary automatic
CSV upload/context/mapping forms now use the default shared preparation core.
The installed acceptance includes 257 core/source cases, including default routing,
reusable contexts, corrections and manual source-account flows; plugin13 remains
a separate independently installed/immutable-image suite.


## Optional full-product V2 source contract

The current parser SDK/protocol2 remains supported. The separate, locally
implemented [source lifecycle profile](web-v2-sources.md) is under review and wraps
existing parser2 output or direct domain1 payloads in source-transport1. These three
version numbers have independent meanings. Descriptors bind exact reviewed
package/artifact/image content; menus read inert metadata rather than executing
entry points. Minimal child input excludes database/session/realm authority; strict
host admission remains nonbooking. Direct-domain reference/provenance declarations
must match caller-owned expected mappings/graphs, not permissions derived from
candidate output. See [native test fixtures](../tests/fixtures/source_capabilities/README.md)
for the offline file/API parity recipe. This is not a live connector API, automatic
plugin marketplace or production V2 uploader. The existing SDK/core wheels contain
application modules and exclude the synthetic worker/fixture image context.
