# Canonical ingestion and parser previews

SRC-004A implements an explicit-context parser-v2 contract and a stateful canonical
store in the existing financial SQLite database. It is a **trusted developer API**,
supplemented by the opt-in frozen CSV submission path described below. No runtime LLM or new application dependency
is used. Wealthsimple/Bull financial imports, browser upload confirmation and the
existing reports retain their current paths.

SRC-004B1 supplies pure built-in v2 parsers and nonbooking context previews.
SRC-004B2 provides explicitly confirmed data-only submission/recovery.
SRC-004C1 adds an [internal read-only projection model](source-projections.md).
C2 adds read-only legacy/wallet/history compatibility. Source-neutral daily
declaration/import routing and report publication remain SRC-004C3; that acceptance is not complete. Do not advertise arbitrary bank/exchange imports. A structurally valid
parser batch does not establish complete costs, portfolio membership or investment
performance. The [architecture blueprint](source-adapters.md#implementation-blueprint-planned-src-002-through-src-004)
remains the integration acceptance contract.

## Safety gate and intended use

Use only synthetic, disposable workspaces for this phase. `prepare_ingestion` is
read-only; `commit_ingestion` preserves canonical facts/effects but returns
`report_projection_ready: false`, `contributions_calculated: false` and
`report_published: false`. There is no implicit report generation or valuation.

A workspace containing canonical-v2 batches **cannot generate a new legacy financial
report**: `core.make_payload` and `combined.make_combined_payload` reject it with
`report_projection_unavailable`. This prevents a report silently excluding the new
facts. Reading/exporting existing frozen publications and backing up/restoring them
remain supported. Ordinary workspaces with no v2 batches retain their behavior.
Remove this gate only after compatibility/projection acceptance in SRC-004B/C.

Do not import real accounts into this foundation as a shortcut to new broker support,
reimport an existing portfolio or switch a daily workspace. A private user's formal
migration requires its own reviewed plan and authorization.

## Contract version 2

`wealth_ledger.source_v2` imports the same `AccountKey`, `AssetKey`, `Money`,
`RecordKey`, `CryptoLeg`, `Detection` and `AdapterInfo` primitives as v1. Adapters
must explicitly declare `api_version=2`. V1 normalization/validation and canonical
serialization are unchanged; v1 batches are not coerced into v2.

| Type | Information retained |
|---|---|
| `ParseContext` | Host evidence time, source reference, optional account alias/timezone/format selection, record and scope parent-revision choices |
| `Account`, `Membership` | Namespaced identity, account type/label/masked display, investment/crypto/funding role, explicit full/partial/unknown membership and scope revision |
| `Snapshot`, `Coverage` | Source observation ID/time/revision, account membership, per-kind/account observation coverage and revision lineage |
| `Position` | Instrument name/type/market/exchange, reported quantity, market value, unit price, separate native/CAD costs and source unrealized amount |
| `CashFlow` | Positive currency-qualified amount, explicit incoming/outgoing direction, status, boundary and typed counterpart/purchase-cash-leg references |
| `CryptoTransaction`, `Fee` | Signed asset/network legs, native/CAD acquisition costs, unknown versus explicit fees, fee allocation to legs/cost and revision reason |
| `Lifecycle`, `AssetAmount`, `Rate` | Creation/completion/sent times, source type/subtype/statuses, pay-in/pay-out quantities/assets/methods and source exchange/index rates |
| `Evidence`, `Diagnostic` | Raw hash, exact host context, source time, stable-ID policy, mappings, coded findings and bounded audit-only source fields |

Unknown cost/price/fees remain `None`; explicit zero remains zero. Source CAD cost
is preserved, never recalculated with today's FX. No unit price is inferred by
quantity division. BTC/LBTC remain distinct networks with whole-satoshi precision.
Funding accounts are explicitly different from investment assets. Arbitrary audit
fields are never used for financial decisions.

`normalize(raw, *, export_version, context)` receives immutable host input and no
workspace/database handle. It must not call a clock, network, subprocess or file IO.
Required parent choices cannot be silently changed or omitted. New snapshots,
source IDs and source revisions need a documented policy, independent of filenames.
Adapters lacking provider-issued revisions may use an explicit content-based policy
and host-reviewed parent context; the core never guesses lineage from equal amounts.

`validate_batch` checks metadata, finite Decimal values, aware times, exact source
hash/context, accounts, coverage, snapshot relationships, directions, references,
fees and revision reasons. `canonical_json` preserves all fields. `decode_batch`
accepts only canonical encodings of known core schemas: no duplicate/unknown JSON
keys, JSON financial floats, unbounded nesting, module names or dynamic parser
imports. Saved evidence can be verified/replayed without executing the source parser.

The registry can inspect/detect v1 and v2 adapters. The existing **v1 source-plan
CLI/API** still uses its original contract: it rejects a v2 match with
`protocol_v2_context_required`, rather than calling a context-free normalizer or
making it financially confirmable. Use `source_testing.check_contract_v2` for
explicit-context author tests. The independent example package remains v1.

## Planning, identities and commit

The trusted API in `wealth_ledger.source_ingestion` provides:

1. `SourceInput(batch, raw)`: original bytes and a validated v2 batch.
2. `Binding(account, ledger_account_id, target_kind)` or `new_binding(account)`:
   explicit choices scoped to this portfolio, never global instance aliases.
3. `prepare_ingestion(project, inputs, bindings=...)`: read-only structural and
   stateful checks, recording financial-state/code/policy/canonical/binding digests.
4. `commit_ingestion(workspace, plan, operation_id=None)`: the existing
   `ApplicationService.record` lock, pre-change database backup, isolated staging
   and atomic data/completion-marker transaction. IDs use the existing `OP-...` format.
5. `verify_store(project)` and `read_facts(project)`: read-only archive/fact/effect
   integrity and canonical observations. These are not report payloads or returns.

Inputs are bounded to five batches, 10 MiB raw per batch, 25 MiB raw overall and
4 MiB canonical per batch; a plan may supply up to 200 account bindings. All
configuration/context choices are explicit values in the plan. The environment
hash covers actual core/runtime/dependency files. A state, binding, code, policy or
canonical-data change invalidates the plan; code/state are checked again inside
staging. There is no automatic code installation or parser execution at commit.

Bindings are immutable and injective. A provider cannot silently claim another
provider's ledger account. `legacy_holdings` binding requires the existing ID and
matching type/masked identity; `legacy_crypto` requires matching provider/source
account. `canonical` targets cannot impersonate existing legacy IDs. Historic IDs,
rows and archive paths are retained. Binding declarations are saved as immutable
hashed evidence, alongside original CSV and canonical batches.

`src_schema` version 1 is an additive sub-schema: it does not rewrite the legacy
`schema_info` version or create a second database. Its eight tables are
`src_schema`, `src_bindings`, `src_batches`, `src_records`, `src_batch_records`,
`src_scopes`, `src_snapshot_records` and `src_effects`. Creation happens only in
an explicitly committed staged operation. Future/partial schemas fail closed.
Legacy importers do not create these tables during ordinary updates.

## Reimports, revisions, scopes and economic links

- The same source identity/revision/content has one fact. Later retrieval evidence
  can be retained without duplicating effects. Conflicting content under the same
  revision is rejected. Replaying an old revision never resets the current head.
- Corrections/voids require the current parent and an explicit reason; void events
  are cancelled. Rows remain append-only. Active effects follow the current revision.
- Membership/coverage/snapshot scope revisions have explicit parents. Conflicting
  overlapping input scopes are rejected. Missing positions in partial snapshots
  never create disposals or zero holdings. Different observation dates remain
  separate; never sum historical observations as current assets.
- Completed CAD/USD cash changes and long CAD/USD cash/security observations are
  supported by the foundation. Completed crypto effects initially support a
  CAD debit plus BTC or LBTC purchase, with explicit separate/included fees.
  A purchase may explicitly debit a separately declared funding account while
  delivering crypto to its declared crypto account. Cross-account purchase fees
  must belong to the matching cash or crypto leg. Completed sales/swaps/other unsupported effects block the whole batch; pending
  and cancelled evidence may remain without effects.
- A completed purchase cash-leg reference must resolve to exactly the same account,
  currency and signed quantity in a completed crypto event. Its cash effect is
  recorded once. A second claim to the same cash leg is rejected.
- Internal cash transfers match only with reciprocal references, equal amounts and
  currency, opposite directions and the same transfer reference. Missing counterparts
  remain unresolved; wrong claimed counterparts fail. No amount/date-only matching
  or automatic external-contribution classification is performed.
- Unknown wallet fees/coverage remain unknown. Source changes do not verify a wallet
  total, establish complete acquisition cost or imply a portfolio contribution.

## Recovery, backups and verification

A committed receipt remains complete even if staging cleanup or response delivery
fails afterward. Retrying that operation returns the saved result without parsing,
recalculating effects or requiring the newly installed plugin environment. An
uncommitted failure retains the existing failed/review recovery boundary.

`verify_store` compares raw/canonical hashes, strict decoded records, bindings,
revision order, scope membership and expected effects. It does not load plugins.
These facts participate in the existing financial-state fingerprint. Legacy dry-run
copies include their evidence. Web backup and CLI adoption checks reject missing or
changed canonical evidence; full instance backups preserve the new tables/files.
An empty-target restore never installs a plugin. Original archives may remain after
a database rollback, as immutable evidence; they do not create financial effects.

Focused synthetic checks:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_source_v2.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_source_ingestion.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_web_source_ingestion.py' -v
```

The full suite, [installed SDK acceptance](parser-sdk.md) and opt-in Docker suite
also verify the foundation. Docker acceptance includes canonical facts in a separate
synthetic portfolio, then a full backup and restore to an empty volume while existing
legacy/frozen reports remain readable. These are synthetic tests, not a personal
migration or a statement that all environments have passed remote CI.

## Explicit-context previews (SRC-004B1)

This increment supplies `WealthsimpleHoldings`, `BullBitcoinOrders` and explicit
trusted `source_builtin.registrations()`. The default empty registry and v1 planner
are unchanged. `source_formats` is the single byte-only grammar implementation
shared with legacy financial import facades. Neither pure parser receives a path,
clock, network, process, database or workspace. Existing legacy imports still write
only their original tables/archives and use their original report paths.

### Source mapping and identity

- Wealthsimple uses the original hashed account IDs, source security keys, explicit
  footer time/offset and source-native/CAD book values. One UTC observation and
  semantic snapshot revision cover its rows. Row order, file name, retrieval time
  and equivalent numeric spelling do not change financial identities. Hashes use
  normalized financial numbers; serialized canonical values use the same spelling.
  Source math inconsistencies produce coded findings and retain the source values.
- Bull requires an explicit stable `account_alias`; it never assumes one from a
  filename or guesses which person's export it is. Original provider/alias/order
  keys and normalized order-content revisions are retained. CAD funding is a
  separate funding account; purchases debit it and deliver BTC/bitcoin or LBTC/liquid
  into a crypto account. The source creation/completion/sent times, statuses,
  pay-in/pay-out methods, rates and acquisition amounts survive normalization.
- Funding is `unclassified` at the portfolio boundary. Purchase spend does not
  create another contribution. Fees remain unknown, including after wallet
  delivery. Missing rate units remain unknown with their source fields retained;
  no rate unit, opening quantity, wallet total or tax cost is invented.
- Both formats declare unknown portfolio membership and partial exported-row
  coverage. Their rows do not establish absence of outside activity, missing
  accounts, earlier balances or wallet fees. Evidence time must not precede the
  observed source time. Explicit source offsets/UTC take precedence; an optional
  declared timezone is retained as context, not used to reinterpret those times.
- Changed records/scopes require explicit host parent choices. The parser does not
  query history or guess those parents; canonical preparation validates lineage.
  Unsupported types/statuses/network combinations or unrepresentable zero pending
  amounts reject rather than silently creating effects. Production migration is
  still gated until the complete native compatibility surface is accepted.

### CLI example and closed context schema

These are developer previews. For two **synthetic example** exports create an empty
trusted host configuration at `work/parsers.json`:

```json
{"schema_version": 1, "enabled": [], "bindings": []}
```

Save this private context file as `work/source-context.json`. Each context corresponds
to the input at the same position. External enablement still follows the strict
[source configuration](source-adapters.md#host-configuration) contract:

```json
{
  "schema_version": 1,
  "inputs": [
    {
      "evidence_at": "2024-03-01T12:00:00+00:00",
      "source_reference": "synthetic-holdings-export"
    },
    {
      "evidence_at": "2024-03-01T12:00:00+00:00",
      "source_reference": "synthetic-orders-export",
      "account_alias": "synthetic-bull"
    }
  ]
}
```

```bash
python scripts/source_parsers.py examples/data/wealthsimple-holdings.csv examples/data/bull-orders.csv --config work/parsers.json --context work/source-context.json
```

An installed wheel uses `wealth-ledger-source-parsers` with the same arguments.
Either single input is accepted with exactly one corresponding context; Bull still
requires its alias. `--select 1=wealthsimple.holdings` resolves explicit selection.
`--verify work/saved-plan.json` checks a saved summary and rejects any changed
context/CSV/configuration/environment/normalized output. Output is JSON only; save
private evidence deliberately. Preview creates no financial database or report.

A context has required `evidence_at` (aware ISO timestamp), `source_reference`, and
optional `account_alias`, `source_timezone` (IANA), `format_selection`, `revisions`
and `scope_revisions`. A record-parent item has `account` (`provider`, `account_id`),
`kind`, `source_id`, `observation_id` (empty for events), `supersedes_revision`.
A scope-parent item has `kind`, `scope_id`, `supersedes_revision`; coverage also
requires `account`, `record_kind`, and an observation ID for holdings. These are
host-reviewed choices, not a parser-generated transaction history. No unknown keys,
Python module/path, plugin enablement or workspace path can be supplied in context.
Combined context is bounded to 64 KiB/200 parent choices per input.

### API and result boundary

`POST /api/v1/portfolios/{portfolio_id}/source-context-plans` uses a separate typed
request: `upload_ids`, `contexts` (the `inputs` array above), optional `selections`
and `previous_plan_id`. It retains owner auth/CSRF, per-portfolio uploads, idempotency,
state/config/environment pinning, worker isolation and source-plan expiration.
Use `source_csv` uploads; host configuration is still trusted-host only, never an
API choice. There is no new browser form. See [Web imports](web-imports.md).

V2 summaries use schema version 2, `status: plan_only`, `ingestible: false` and
`booking_blocker: production_v2_pipeline_pending`. They contain hashes/counts and
adapter metadata, not account aliases, source references, row values or canonical
financial records. A valid empty normalized batch may report zero observed rows
without establishing zero assets or complete activity coverage. Raw/canonical bytes
stay in mode-restricted temporary files,
strictly decoded/validated by the parent and removed after return. The trusted
`parse_sources` API additionally returns private typed batches/raw bytes in memory;
`plan_context_sources` returns only the summary. No automatic archive/booking occurs.

A ready plan cannot be confirmed through financial jobs or financially resumed.
Context-free v1 plans keep their original schema/blocker. The canonical developer
API's report phase gate still applies. A separate SRC-004B2 frozen ingestion preview/confirmation is required to commit
canonical data. SRC-004C must complete source-neutral report projections before any
daily workflow switch; this nonbooking preview is not a production migration.

## Frozen submission and recovery (SRC-004B2)

B2 adds an **opt-in canonical data-only path**, separate from the existing daily
update workflow and both nonbooking source-plan APIs. It parses once in a bounded
child, validates the complete batch and portfolio mappings, freezes original and
canonical bytes, then requires an exact approval fingerprint and acknowledgement
that reports are unavailable. Confirmation never invokes the parser or downloads
references. It commits through the existing lock, backup, staging transaction and
atomic financial completion marker. No runtime LLM or new dependency is involved.

A successful receipt has `status: canonical_committed`, `report_published: false`,
`report_projection_ready: false` and `contributions_calculated: false`. This is not
a current valuation, return, contribution total, report publication or personal
migration. Use a disposable synthetic workspace for evaluation. Native daily
cutover is still blocked by SRC-004C; do not import a daily portfolio here as a shortcut.

### Mapping review and preserved identities

Each declared account requires an explicit portfolio-scoped choice. Missing choices
produce `status: mapping_required` with `account_review`/`suggested_choice`; no frozen
bundle or financial database is created. Review those suggestions before supplying
bindings. Already stored canonical mappings are retained. Host-global source-plan
bindings do not assign financial identities across portfolios.

A binding file has `schema_version: 1` and `bindings`. Each item has `provider`,
`source_account_id`, `target_kind`. `new` explicitly chooses a deterministic new
canonical ID. `canonical`, `legacy_holdings` and `legacy_crypto` also require
`ledger_account_id`. A detected matching legacy account must use its original ID;
choosing `new` cannot silently duplicate it. Type/masked-identity/provider/source
checks still apply. Existing legacy rows, IDs, FX, report editions and archive paths
are never rewritten. The new facts/evidence are additive.

Native compatibility policies remain isolated in `source_native_compatibility`:
completed Bull economics/creation/completion times cannot be changed or reverted;
source metadata updates still require explicit revision parents. Previously archived
revisions can replay without replacing current heads. Wealthsimple backfill before
the established baseline is rejected. Unsupported/unrepresentable native cases
remain rejected; this does not broaden current format support or complete cutover.

### CLI: inspect, freeze, confirm and recover

The checkout command is `python scripts/source_ingestion.py`; the installed console
is `wealth-ledger-source-ingestion`. All subcommands require an explicit existing
`--workspace`. They never fall back to an installation or the maintainer's workspace.
The following example uses only the public synthetic Bull fixture.

Create a dedicated empty `work/canonical-demo` directory and these private files:

`work/parsers.json`:

```json
{"schema_version": 1, "enabled": [], "bindings": []}
```

`work/bull-context.json`:

```json
{"schema_version": 1, "inputs": [{"evidence_at": "2024-03-01T12:00:00+00:00", "source_reference": "synthetic-orders-export", "account_alias": "synthetic-bull"}]}
```

First discover account mappings without committing or saving a bundle:

```bash
python scripts/source_ingestion.py preview examples/data/bull-orders.csv --workspace work/canonical-demo --context work/bull-context.json --config work/parsers.json --plan-directory work/bull-frozen
```

Review the returned `account_review`. For this synthetic empty portfolio, save
`work/bull-bindings.json`:

```json
{"schema_version": 1, "bindings": [
  {"provider": "bullbitcoin", "source_account_id": "synthetic-bull", "target_kind": "new"},
  {"provider": "bullbitcoin", "source_account_id": "synthetic-bull:cad", "target_kind": "new"}
]}
```

Freeze a new preview and inspect the exact mappings/record count/approval hash:

```bash
python scripts/source_ingestion.py preview examples/data/bull-orders.csv --workspace work/canonical-demo --context work/bull-context.json --config work/parsers.json --bindings work/bull-bindings.json --plan-directory work/bull-frozen
python scripts/source_ingestion.py inspect --workspace work/canonical-demo --plan-directory work/bull-frozen --approval-sha256 APPROVAL_SHA256_FROM_PREVIEW
```

`inspect` only displays the frozen scope (`freshness: not_revalidated`); it does not
assert the state is still current. A frozen directory must be new, outside protected
financial/configuration directories. Keep it in ignored private storage. POSIX
bundles are mode 0700 with mode 0400 files. The exact manifest, original CSVs,
canonical JSON and host configuration are retained. Public source/package locations
are rejected; checkout `work`/`private` are allowed. There is no encryption claim.

Confirm only after reviewing the scope and accepting the report phase gate:

```bash
python scripts/source_ingestion.py confirm --workspace work/canonical-demo --plan-directory work/bull-frozen --config work/parsers.json --approval-sha256 APPROVAL_SHA256_FROM_PREVIEW --acknowledge-no-reports
```

The two hashes differ: `approval_sha256` approves frozen bytes, mappings, workspace,
state, configuration, environment and fixed operation ID; `plan_sha256` identifies
the core plan in its durable receipt. Save both and `operation_id`. Confirmation
checks the current workspace/configuration/environment under the existing safety
boundary; changed evidence/state rejects. Missing source paths after freezing do
not trigger reparsing. Unknown operation states never automatically retry effects.

After a lost response or missing preview directory, recover only a matching proven
completion, without a CSV, configuration file, parser or original environment:

```bash
python scripts/source_ingestion.py recover --workspace work/canonical-demo --operation-id OPERATION_ID_FROM_PREVIEW --plan-sha256 PLAN_SHA256_FROM_PREVIEW
```

Recovery verifies the stored operation type/plan/completion marker and archived
canonical evidence. A nonexistent or incomplete operation is not success. A failed
uncommitted operation requires a fresh review/new operation; never delete an audit
row or invent a compensating trade to force recovery. Reconfirmation of a complete
operation returns its receipt; no second financial effect is created.

For Wealthsimple or both CSVs, supply one context per input and explicit choices
for every new account shown in review. Existing mappings can be reused. The same
five-input, raw-byte, canonical-byte and context bounds apply. No monthly observation,
missing activity, opening balance, wallet fee or contribution is inferred.

### Owner-only API and isolated jobs

Use authenticated, CSRF-protected portfolio routes with `Idempotency-Key` for jobs:

| Endpoint | Contract |
|---|---|
| `POST /source-ingestion-previews` | `upload_ids` (`source_csv`), `contexts`, optional `bindings`/`selections`; queues `source_preview` |
| `POST /source-ingestions` | `preview_id`, exact `approval_sha256`, `acknowledge_no_reports: true`; queues fixed-ID `source_commit` |
| `POST /source-ingestions/{job_id}/recover` | Receipt-only completion recovery for an inactive job |
| `POST /source-ingestions/{job_id}/discard` | Explicitly discard a never-started or matching proven-failed job; retain all audit rows/evidence |

Paths are prefixed by `/api/v1/portfolios/{portfolio_id}`. Requests cannot supply
host paths, package enablement, code or operation IDs. Mapping-required results
cannot confirm. Nonbooking `source_plan` jobs cannot convert to financial jobs.
Ready ingestion previews expire after 24 hours; queued commits also recheck expiry.
Existing update/declaration/source-commit work is mutually exclusive. A preview has
one fixed financial operation ID; idempotent retries cannot create another effect.

API/worker use `admin/source-submissions/{portfolio_id}/{preview_id}` for frozen
private evidence. Confirmation checks uploads/configuration/state/engine and the
frozen summary, then commits decoded bytes. Committed recovery ignores stale parser
configuration and verifies the durable receipt. Active jobs are protected by their
kernel guard. `recorded` is data-only and never creates a report registry entry.
There is no new browser form yet.

### Backup, restore and daily-workflow boundary

Full backups preserve frozen bundles, original uploads and canonical facts/receipts.
CLI preview writes for Web-managed portfolios share the instance maintenance barrier,
so backups cannot capture a partially saved bundle.
Restoration expires ready/queued/running source previews and marks pending source
confirmations `needs_review`; it never silently reuses an old workspace-bound approval.
Completed receipts remain recoverable at the new root without loading a parser.
An unstarted or matching `data_failed` job can be explicitly discarded in metadata,
without deleting its financial audit row. Started/ambiguous or committed operations
cannot be discarded as unstarted; inspect them and recover a proven receipt.

Once canonical data is committed, legacy CSV mutation paths and new financial
reports fail with the phase gate. Existing frozen reports, downloads and backups
remain readable. Normal workspaces with no canonical batches retain their existing
workflow. B2 does not switch a personal workspace, migrate historical reports or
complete provider-neutral valuation/history/contribution/report projections. Those
remain SRC-004C acceptance requirements before any daily-use cutover.
