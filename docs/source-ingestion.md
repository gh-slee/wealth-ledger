# Canonical ingestion foundation (SRC-004A)

SRC-004A implements an explicit-context parser-v2 contract and a stateful canonical
store in the existing financial SQLite database. It is a **trusted developer API**,
not a new production CSV import command. No runtime LLM or new application dependency
is used. Wealthsimple/Bull financial imports, browser upload confirmation and the
existing reports retain their current paths.

SRC-004B must migrate those importers and their CLI/Web preview/confirmation paths;
SRC-004C must implement source-neutral portfolio/report projections. Neither is
complete. Do not advertise arbitrary bank/exchange imports. A structurally valid
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
CLI/API** still has no v2 host-context UI: it rejects a v2 match with
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
  Completed sales/swaps/other unsupported effects block the whole batch; pending
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
