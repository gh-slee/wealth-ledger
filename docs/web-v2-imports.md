# V2 CSV ingestion

V2 financial ingestion is under implementation. There is no operational `0004`
profile, authenticated CSV import route or new browser import workflow yet. Use
the existing [daily source workflow](source-projections.md#default-daily-workflow)
for tracking and reports. Existing Web/CLI workspaces remain on SQLite.

## Current building blocks

- [Evidence admission](../src/wealth_ledger/ingestion/codec.py) checks bounded
  canonical JSON, closed fields, exact decimal tokens, source times, whole
  satoshis, local references, cash-flow shape and required unsupported-data
  reasons. Unknown fees and absent membership stay null. A selected coverage
  interval must contain its snapshot date, including a complete empty snapshot.
  Exact date-only or legacy assertions can agree within supplied evidence without
  granting authority to install a current snapshot head. Head ordering still
  requires comparable source times, including the first head.
- [Parser2 discovery](../src/wealth_ledger/ingestion/discovery.py) validates the
  frozen parser output against raw bytes, caller context, installation and reviewed
  wrapper profile. Its projection retains essential typed evidence and excludes
  arbitrary row archives. It does not execute a plugin or accept financial facts.
- Native discovery uses the frozen domain validator in a caller-owned ephemeral
  namespace, then converts identifiers to local references. It retains issuers,
  instrument identifiers, source dates and actual lifecycle sidecars. Its retained
  identity-policy token comes from the exact reviewed wrapper profile; parser2
  retains source-supplied prose. A profile-verification helper rejects a changed
  native token even when its stage hash is valid. Live admission and preparation
  still need the unfinished service integration; this helper grants no authority.
  Frozen-valid legacy timestamps retain their original token, unspecified
  precision and archive pointer; they are not promoted to precise instants.
- [Mapping and reconciliation](../src/wealth_ledger/ingestion/reconciliation.py)
  distinguish exact source identity, financial meaning, corrections and historical
  snapshots. Financial digests exclude archive pointers at declared lineage
  locations while preserving time tokens and economic-reference revisions. Equal
  amounts or file hashes do not establish a duplicate trade.
- [Review validation](../src/wealth_ledger/ingestion/approval.py) requires exact
  admitted stage bytes, checks the disclosed evidence and target bodies, and binds
  the complete READY review to its Plan. Recomputed hashes alone cannot establish
  truthful disclosure. Current database authority must still be checked at commit.
- [Transport helpers](../src/wealth_ledger/ingestion/runner_client.py) check bounded
  frames and exact TLS peer identity. The [raw receiver](../src/wealth_ledger/web_v2/imports.py)
  enforces Content-Length and receive deadlines without a body spool. It must be
  called only after authentication, CSRF and shared database capacity admission.
- [Storage fragments](../src/wealth_ledger/persistence/ingestion_schema.py) define
  the closed table inventory, scoped foreign keys, canonical-byte checks and
  forced-RLS policies. Separate append-only and outbox trigger fragments reject
  accepted-record changes and malformed or inconsistent event envelopes. The
  checked effects function must still prove actual references and changed facts.
  A private user-guard fragment reuses existing identity clock/session/credential
  rules and checks the explicit schema, initialized marker, realm and catalog
  before returning an authenticated scope. It is not wired into import routes.
  A schema-owned SQL renderer also checks closed Minimal structure, decimal and
  time envelopes, typed selectors and support flags. It is an expression builder,
  not the complete Minimal validator: local graph, whole-satoshi, financial and
  current source/profile checks still need the checked entry point. It installs
  no database function or grant and cannot make an import ready.
  Integer enum choices reject decimal scale, and ordinary text checks reject
  exactly the C0 controls while preserving permitted DEL/C1 characters. The
  byte entry point must still compare canonical input bytes: parsed
  JSONB alone loses original exponent and negative-zero spellings.
  The declared `_validate_minimal_v1(bytea)` helper now renders that byte entry
  point, including pre-parse depth/size bounds, canonical bytes, exact schema
  error classes, local references, whole-satoshi quantities, cash-flow and
  snapshot semantics. It returns the retained evidence without changing its
  values, including canonical legacy ISO timestamps with second or microsecond
  timezone offsets. No application profile installs or calls it yet. Session, lease,
  selected-profile and accepted-reference authority remain separate requirements
  for the unfinished admission and preparation functions.
  The declared `_validate_plan_v1(uuid,uuid,uuid,bytea)` renderer binds canonical
  Plan bytes to stored member pins, stages, complete decisions and scoped entity
  versions. It recomputes financial material, including snapshot children, and
  checks local parent, authority and head references. READY preparation can pin
  exactly the next revision while an existing READY Plan pins the current one;
  this read-only check does not advance state.
  The `_references_v1(uuid,uuid,uuid)` renderer reads a stored preview and checks
  scoped accepted references against permanent input and Plan bytes. It compares
  full source keys and financial content, checks duplicate/correction lineage,
  resolves economic links, rejects parent and mirror cycles, and checks current
  head targets. Same-set duplicate evidence may reference a new revision already
  declared by that Plan. Duplicate and correction effects retain the economic
  group proven by their target or parent. A host correction decision cannot
  deactivate a chain as a void; void requires explicit source evidence. A same-set
  correction path may advance one final head from its locked accepted ancestor.
  Competing activity connections with overlapping mapped coverage require an
  explicit authority choice. A historical snapshot choice covers its declared
  position and coverage children, without granting current-head authority.
  These checks remain development fragments awaiting
  independent acceptance and integration with authenticated lock ordering, source
  authority and the complete head/effects guards.
  A private `_replay_v1` fragment checks the current initialized incarnation and
  restore epoch, then looks up the exact scope/realm/operation namespace. A known
  kind and request digest recover the original canonical result; changed content
  conflicts, and a missing receipt returns no outcome. It reads no mutable source
  or preview rows and writes no facts, counters or audit records. Callers must
  authenticate and derive scope first; this helper is not a login or history route.
  The `_transition_v1` trigger guard rejects control-row states that no checked
  function may produce. Sets follow the declared state graph, advance their
  revision once for decisions, cancellation, READY preparation and acceptance,
  and can only become EXPIRED once the database clock reaches expiry. Terminal
  sets change only their cleanup progress. Members keep their pinned selection
  and source generations, follow their already locked set into terminal states,
  and need a fence step before raw bindings are replaced. Leases reject stale
  fences, disabled workers, work after the deadline and offers longer than the
  declared limits. Stages, decisions and previews are append-only and can be
  deleted only after terminal state or purge time. A preview pins the current set
  revision, decision revision and root generations, and carries a Plan only when
  READY. Quota windows reset only after 300 seconds, and held counts never reset
  with a window. Readiness cannot keep a changed catalog or profile, and worker
  credential epochs only increase.
  The `_head_v1` trigger guard keeps heads on authoritative revisions. An
  activity head targets an activity record, is inactive exactly for a void, moves
  only down its explicit correction chain from an active head, and cannot fork a
  chain another group already heads or follow a parent cycle. A snapshot head
  recomputes its key from the closed canonical instrument scope and account, and
  names only existing scoped instruments. A newer complete observation replaces
  the complete base, a partial one keeps it, and the head cannot move back onto
  an ancestor. Observation order, source authority and economic group binding
  remain `_references_v1` checks; neither guard authenticates a caller.
  The `_effects_v1(tenant, portfolio, preview, receipt)` renderer is the single
  accepted write. It revalidates the stored Plan, then copies the exact Plan and
  any new input bytes, and inserts proposed entities from the same body fragment
  that Plan validation hashed. It also writes new source revisions, lineage for
  every planned fact, mappings, authority links, head compare-and-set updates,
  generation counters, one audit row and at most one outbox event. A mapping is
  identified by its connection and closed source identity, and a changed target
  appends a revision. An authority decision appends a revision to the latest link
  for the same pair. The caller still authenticates, locks, recovers an existing
  receipt, runs `_references_v1`, inserts the receipt with the returned counts
  and changes set and member state. Opt-in PostgreSQL tests accept a base Plan
  and then each branch, authority-only and snapshot-history vector through this
  function, comparing exact row counts, lineage claims, heads, generations and
  events with the literal fixtures. They do not cover the caller-owned receipt
  row, concurrent acceptance or restore.
  These fragments are not a complete migration provider and install no application
  grants. Never use them to enable a real instance.

## Remaining acceptance

Remaining checked database functions and guards, operator upgrade/inventory verification,
live source/profile checks around native admission and Plan preparation,
authenticated routes, the dedicated worker and
trusted launcher remain unfinished. Real acceptance must exercise atomic effects,
replay, shared capacity, races, cleanup, effective Linux containment and restore
into two independently empty targets.

The new backend does not yet calculate portfolio balances, quotes or reports.
Frontend delivery, report parity and existing-workspace adoption are separate
stages. No current code automatically switches a legacy workspace or rewrites its
financial history.

## Developer checks

Run from the repository root in a supported environment with the locked Web test
dependencies:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_ingestion_*.py' -v
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_postgres_migration.py' -v
```

These focused checks include synthetic evidence and review tampering, parser2
examples, exact native activity/metadata/snapshot vectors, profile-token and
lifecycle negatives, framed bytes, raw ASGI messages and disposable local TLS certificates.
By default, the storage test above checks generated structure without installing a database.
They do not certify authenticated routes, a complete PostgreSQL migration or
Linux child containment. Real database and container checks must use disposable
synthetic resources and report their own executed evidence.

An optional storage-fragment check starts its own PostgreSQL 18 Linux container,
with no network or published port, a temporary private bootstrap secret and
bounded memory/tmpfs resources. The exact image referenced by
`IngestionAppendOnlyPostgresTests.IMAGE` in the test module must already be cached;
the test uses `--pull never`. It verifies nonce ownership before removing only
its own container.

```bash
WEALTH_LEDGER_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_postgres_migration.py' -v
```

This command tests append-only records, immutable event envelopes, closed/rehashed
event mutations, byte/depth limits and exact canonical Unicode/large-array bytes.
It also evaluates generated shape/scalar predicates against literal evidence and
hostile values. Deliberate graph and sub-satoshi controls pass that partial
predicate, demonstrating why it cannot be used as complete stage admission.
Separate checks invoke the declared byte helper itself, where those invalid
references and sub-satoshi quantities reject. They cover literal round trips,
canonical encoding, damaged/oversized inputs, error classes, cash-flow uncertainty,
unknown-date evidence and a denied public EXECUTE grant. These are helper checks,
not an authenticated or committable import.
Plan and reference tests additionally exercise all fixed Plan vectors, scoped
existing entity targets, exact preparation revisions, rehashed substitutions,
missing/duplicated facts, source pins, accepted-input/Plan retention, duplicates,
corrections, same-set references, head comparison and mirror cycles. Synthetic
previews and deferred parent rows isolate these helpers; they do not establish
review disclosure, a live source/lease, complete stream-authority checks or a
committable import. Developer self-tests do not establish independent acceptance.

Transition and head guard checks install both triggers inside a rolled-back
transaction over seeded synthetic rows, including already expired sets and
leases. They cover allowed and skipped state steps, revision counts, fences,
raw rebinding, preview pins, purge timing, quota windows, readiness, worker
epochs, activity chain forks and cycles, and snapshot key, scope, base and order
rules. They do not prove that the checked functions take the declared locks.

The fragment inserts explicitly roll back while deferred parent references are
incomplete. They do not prove a committable import, live authorization, complete
profile migration, transaction atomicity or restore. The opt-in flag enables tests
only; it cannot enable the application ingestion profile.

User-guard checks likewise construct and roll back synthetic readiness/identity
markers to isolate the helper. They exercise stale sessions, credential/realm
changes, initialization and catalog failures. Constructed markers do not establish
an initialized predecessor, a valid full-profile upgrade, effective application
role privileges or an end-to-end authenticated import.

See [source lifecycle](web-v2-sources.md), [parser SDK](parser-sdk.md) and
[development validation](development.md) for the preceding contracts and workflow.
