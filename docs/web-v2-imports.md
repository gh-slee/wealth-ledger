# V2 CSV ingestion

V2 financial ingestion is under implementation. There is no operational `0004`
profile, authenticated CSV import route or new browser import workflow yet. Use
the existing [daily source workflow](source-projections.md#default-daily-workflow)
for tracking and reports. Existing Web/CLI workspaces remain on SQLite.

## Current building blocks

- [Evidence admission](../src/kurafolio/ingestion/codec.py) checks bounded
  canonical JSON, closed fields, exact decimal tokens, source times, whole
  satoshis, local references, cash-flow shape and required unsupported-data
  reasons. Unknown fees and absent membership stay null. A selected coverage
  interval must contain its snapshot date, including a complete empty snapshot.
  Exact date-only or legacy assertions can agree within supplied evidence without
  granting authority to install a current snapshot head. Head ordering still
  requires comparable source times, including the first head.
- [Parser2 discovery](../src/kurafolio/ingestion/discovery.py) validates the
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
- [Mapping and reconciliation](../src/kurafolio/ingestion/reconciliation.py)
  distinguish exact source identity, financial meaning, corrections and historical
  snapshots. Financial digests exclude archive pointers at declared lineage
  locations while preserving time tokens and economic-reference revisions. Equal
  amounts or file hashes do not establish a duplicate trade.
- [Review validation](../src/kurafolio/ingestion/approval.py) requires exact
  admitted stage bytes, checks the disclosed evidence and target bodies, and binds
  the complete READY review to its Plan. Recomputed hashes alone cannot establish
  truthful disclosure. Current database authority must still be checked at commit.
- [Transport helpers](../src/kurafolio/ingestion/runner_client.py) check bounded
  frames and exact TLS peer identity. A peer certificate carries exactly one URI
  SAN, `urn:wealth-ledger:instance:<instance id>:peer:<api|worker|launcher>`; it
  keeps the project's former name so certificates already issued stay valid. The [raw receiver](../src/kurafolio/web_v2/imports.py)
  enforces Content-Length and receive deadlines without a body spool. It must be
  called only after authentication, CSRF and shared database capacity admission.
- [Storage fragments](../src/kurafolio/persistence/ingestion_schema.py) define
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
  only down its explicit correction chain from an active head, and cannot share
  any revision of its chain (parent, descendant or sibling) with another group's
  head or follow a parent cycle. Indexes on revision parents and head targets
  keep this check limited to the affected chain. A snapshot head
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
  appends a revision. A free-text instrument descriptor is evidence, not identity. An authority decision appends a revision to the latest link
  for the same pair. The caller still authenticates, locks, recovers an existing
  receipt, runs `_references_v1`, inserts the receipt with the returned counts
  and changes set and member state. Opt-in PostgreSQL tests accept a base Plan
  and then each branch, authority-only and snapshot-history vector through this
  function, comparing exact row counts, lineage claims, heads, generations and
  events with the literal fixtures. They do not cover the caller-owned receipt
  row, concurrent acceptance or restore.
  The declared gateway function `accept_preview_v1` takes only `operation_id`,
  `preview_id` and `preview_digest`. It authenticates through `_guard_user_v1`,
  then returns an exact earlier receipt before any mutable check. A reused
  operation ID with a different request returns `import_operation_conflict`. It
  then locks source lifecycle rows before the ingestion root, set and preview. It
  marks a set expired once the database clock reaches expiry. It requires a
  READY set at the previewed revision and the exact Plan digest. It rechecks each
  member's pinned connection, enablement, catalog availability and wrapper
  profile, then runs `_references_v1` and `_effects_v1`. Finally it stores the
  canonical receipt, commits the set and its members, and cancels any live
  leases. Failures return a fixed code and roll back every financial effect of
  the call. Only an expired set keeps its EXPIRED fencing, which accepts nothing.
  The receipt is checked again after the set lock wait, the session is rechecked
  at the database clock, and deferred references are proven before success is
  returned. Lock-timeout, deadlock and serialization errors reach the caller's
  retry loop instead of becoming an internal error.
  Opt-in PostgreSQL tests cover commit, exact replay, a reused operation, a new
  operation on a committed set, expiry, source and wrapper changes, request
  shape and a revoked session. Rate admission, grants and the HTTP route are not
  yet wired.
  The private `_quota_v1(tenant, portfolio, bucket, count, bytes)` helper is the
  shared PostgreSQL admission and release point. It locks the instance bucket row
  before the scoped user row. `read` and `control` count one attempt against 300s
  windows of 60/600 and 30/300 (user/instance). `raw` +1 counts one attempt
  (10/60) and takes one concurrent slot (1/4); −1 releases the slot only.
  `storage` ±1 reserves or releases one outstanding set (8/64) with its bytes
  (128 MiB/1 GiB, at most 16 MiB per call). Only the attempt count resets with a
  window. A release without a matching reservation fails, so nothing is released
  twice. Rate and slot exhaustion return `import_busy`; storage exhaustion returns
  `import_limit`.
  The private `_purge_v1(tenant, portfolio, set)` helper cleans one terminal set.
  It takes the storage quota rows before the set, refuses while a non-cleanup
  lease is still offered or active, and deletes only that set's stages,
  decisions and previews. It also clears member context bytes. After it proves those rows are gone, it
  releases the set's storage reservation once and marks cleanup complete; a
  repeated call changes nothing. Sets, members, leases, receipts and accepted
  evidence stay. Opt-in PostgreSQL tests cover window reset, user and shared
  instance bounds across portfolios, double release, purge ordering and fail-closed
  rollback. `cleanup_set_v1` is the only caller of `_purge_v1`.
  The declared gateway function `cancel_set_v1` takes only `operation_id`,
  `set_id` and `expected_set_revision`. It authenticates through
  `_guard_user_v1` and returns an exact earlier CANCEL receipt before any mutable
  check; a reused operation ID with a different request returns
  `import_operation_conflict`. It locks the ingestion root, set, members and
  leases in the same order as acceptance. A set that acceptance already committed
  is returned unchanged with its acceptance receipt ID. Expiry still wins and
  fences the set. Otherwise, at the expected revision, the set becomes CANCELLED
  with one revision and one control-generation step, member attempts and live
  leases are fenced, cleanup is marked pending, and one CANCEL receipt and one
  CANCELLED audit row hold the resulting set view. Accepted facts, mappings and
  quotas are untouched; storage is released later by cleanup. Opt-in PostgreSQL
  tests run it under the real transition guard, including cancel-then-confirm
  and confirm-then-cancel orders inside one transaction. They do not race two
  connections. No HTTP route calls it yet.
  The declared gateway function `decide_set_v1` takes `set_id` and one complete
  `Decisions` object. SQL checks that object against the closed codec schema,
  including its 128-entry bounds; references are proven later during
  preparation and acceptance. It follows the same receipt-first replay, lock order,
  session recheck and expiry rule as cancel. It accepts only a NEEDS_MAPPING,
  CONFLICT or READY set at the revision in the request. Retained transient bytes
  (contexts, stages, decisions and previews) plus the new document must fit the
  set's fixed reservation, otherwise it returns `import_limit` without writing.
  On success the set becomes RECONCILING with one revision and one control
  generation step, the next decision revision is appended, live prepare leases are
  cancelled, and one DECISIONS receipt and DECIDED audit row are stored. An earlier
  READY preview can then no longer be confirmed.
  `read_set_v1` and `read_receipt_v1` authenticate first and read one ID in the
  caller's scope without locks or writes. A set is reported in its stored state.
  An ACCEPT receipt is returned exactly as stored. A control receipt (CANCEL or
  DECISIONS) is rebuilt as the history DTO from its row and audit entry with zero
  fact counts. Receipts from earlier restore realms stay readable but grant
  nothing. Rate admission for these calls is left to the caller.
  [Page cursors](../src/kurafolio/ingestion/cursors.py) follow the declared
  token format: canonical cursor JSON and an HMAC-SHA256 over those exact bytes,
  each unpadded base64url and joined by a dot, at most 1,024 characters. The key
  is derived from the instance secret for the `wealth-ledger/ingestion-cursor-v1`
  purpose. The API checks the MAC in constant time before decoding, then rejects
  noncanonical JSON, open payloads and alternative base64 spellings. A cursor is
  signed, not encrypted, and holds only opaque IDs, a fixed filter, a position and
  an expiry. The database never holds the key.
  `read_sets_v1` and `read_preview_v1` take that already-verified payload and
  recheck it against live authentication before using its position. The checks
  cover user, portfolio, the SHA-256 realm digest of the guard's canonical realm,
  filter, resource, revision, review digest and expiry. A cursor expires no later
  than the session's absolute or 30-minute idle limit; for previews it also expires
  no later than the set and preview. `read_sets_v1` lists set views newest first
  in pages of 1 to 50 with an optional exact state filter. `read_preview_v1` pages
  the stored review document's rows. It stops before 50 rows or 4 MiB of canonical
  row bytes and never splits a row. A review with no rows has an empty first page
  and no next cursor; a cursor at or past the last row returns `import_stale`.
  It reports `can_confirm` only for the current
  READY revision with a complete Plan before expiry. A later set revision leaves an
  old preview readable but not confirmable. Both return the unsigned next-page
  payload for the API to sign. No route signs or verifies cursors yet.
  The private `_guard_worker_v1(worker, token, request)` helper is the first
  check of every worker function. Worker identity is the actual database login:
  the registry row named by the worker UUID must belong to `session_user` and be
  enabled. The request's credential epoch must equal the registry's, and its
  realm digest must equal the current realm digest. The installed profile version
  and both instance readiness markers are checked first. The UUID, token and
  request fields are assertions, never scope authority. The helper returns the
  SHA-256 of the token's 32 decoded bytes for the caller's lease check. It
  needs no user session, so cleanup can run after the originating session
  ends. No worker function calls it yet.
  The declared gateway function `create_set_v1` takes only an `operation_id` and
  one to four member selections. Each selection names a connection, installation,
  format version and an optional declared size of at most 10 MiB; no financial
  value is accepted. It follows the same receipt-first replay as cancel, locks the
  source lifecycle rows, reserves one set's fixed 16 MiB storage capacity through
  `_quota_v1`, then locks the ingestion root and checks the receipt again. Each
  member must use an enabled file-import connection and enabled source on the
  same installation, ACTIVE catalog availability and exactly one reviewed wrapper
  profile for that installation and format. Any failure returns a fixed code and
  rolls back the reservation and every row. On success the database builds each
  member's child context itself, following the owner's Option A decision. The
  context carries a fresh job ID, member ID, fence 1, the wrapper profile and image
  digests, and an evidence time from the database clock in whole UTC seconds. A
  parser-v2 profile gets a fresh source reference; a native discovery profile gets
  a fresh ephemeral namespace, never real tenant, portfolio or connection IDs. The
  set starts RECEIVING with a 24-hour expiry, its members start `waiting` with
  their source pins recorded, and one CREATE receipt and CREATED audit row hold
  the set view.
  `reserve_member_v1` opens and binds one raw upload attempt without ever
  receiving raw content. `reserve` needs a RECEIVING set at the expected revision,
  rechecks the member's creation-time pins (a changed generation returns
  `import_stale`), counts one raw attempt and takes the user's one concurrent raw
  slot. It needs exactly one enabled worker. The member becomes `receiving` with a
  120-second raw deadline, a re-upload advances the fence and clears old raw
  fields, and an unbound 30-second offer lease is created that no worker can
  claim. `bind` accepts the SHA-256, length and handoff-token digest once, from the
  same session, before the deadline and offer expiry. It extends the offer by up
  to 60 seconds within the raw deadline and returns handoff metadata only; the
  trusted API adds its own plaintext token. Opt-in PostgreSQL tests cover
  replay, a reused operation, quota exhaustion, each unavailable-source case, the
  native namespace, cancel-then-purge release, reservation rollback on every
  refusal, missing or ambiguous workers and re-upload fencing. No upload route,
  worker claim or raw transport calls them yet.
  The worker functions `claim_member_v1` and `renew_member_v1` handle normalize
  leases; the prepare and cleanup kinds return `import_invalid` here. Both take no bytes and call `_guard_worker_v1` first.
  Scope comes only from the stored set row, and locks follow the reserve order.
  The lease must be the member's one live normalize lease at the requested fence,
  name the calling worker and match the handoff-token digest
  (`authentication_required` otherwise). The set must still be RECEIVING and
  unexpired, and the member's creation-time pins are rechecked. As r7 requires,
  the session that reserved the attempt must still be live, with the same user
  and credential version (`session_changed` otherwise), and no lease runs past
  the member's 120-second raw deadline (`import_reupload_required` once it
  passes). `claim` also needs
  the bound raw digest, the member's context digest and the context's job ID. It
  moves the member to `normalizing` and the lease to `active`, storing the claim
  request ID and digest. Repeating that exact claim returns `already_claimed`;
  another request ID returns `import_conflict`. `renew` extends an active lease,
  never shortening it, and stores its acknowledgement so that a repeated request
  gets the same bytes back. Lease deadlines are whole seconds, 30 seconds ahead
  and never past set expiry. Every acknowledgement carries a `source_fingerprint`:
  the SHA-256 of the canonical Plan `pinned_sources` entries for the set's
  members in member-ID order. Opt-in PostgreSQL tests cover claim, lost
  acknowledgements, renew replay and every refusal leaving the offer unchanged.
  `admit_stage_v1` uses the same lease checks on an active lease and is the only
  worker function so far that takes bytes: the child's canonical minimal evidence.
  The bytes must match the request's length and stage digest, and the request's
  raw digest must be the member's. A stage with the same digest already stored for
  the member returns `already_admitted` without parsing again. A different stage
  stored since this attempt's offer returns `import_conflict`, so each raw attempt
  admits at most one stage. Otherwise `_validate_minimal_v1` checks the document.
  Its provenance must name the member's raw digest, installation, wrapper profile
  and format, the request's discovery digest, and the context's image digest,
  evidence reference, evidence time and parser API; any difference returns
  `import_invalid`. The stage must also fit the set's reservation with the other
  retained transient bytes (`import_limit` otherwise). It is then stored until set
  expiry. The member stays `normalizing` with no stage digest until a finish call
  admits it. Opt-in PostgreSQL tests cover parser and native evidence, replay, a
  second stage, each provenance mismatch and the reservation bound, with nothing
  stored on refusal. No worker process calls it yet.
  `finish_member_v1` ends an active normalize lease with one outcome and up to
  three launcher cleanup proofs for the same job and fence. A lost acknowledgement
  is answered from the finished lease's stored result; any other request on it
  returns `import_stale`. `stage_admitted` needs no error code, the uploader's
  live session, valid source pins and exactly one stage stored during this attempt. The member becomes `admitted`
  with that stage digest, and when every member is admitted the set moves to
  NORMALIZING for preparation. `reupload_required` and `rejected` need an error
  code from the public member result list, and neither depends on the source
  still being available. A re-upload request makes the member `reupload_required`;
  the next reserve starts fence 2 and clears the error code. Following the owner's
  decision, `rejected` rejects the whole set: it becomes REJECTED with cleanup
  pending, every member is rejected, the finishing member keeps the error code and
  other live leases are cancelled. No receipt is written because no user operation
  is involved. Also by owner decision, the user's raw slot is released only when
  at least one proof was sent and every proof says `absent` or `not_created`.
  Otherwise the acknowledgement says `cleanup_complete: false` and the slot stays
  held for a later cleanup call. Proofs are checked for shape and stored on the
  attempt's lease. Each normalize lease records whether its attempt still holds
  the raw slot that reserve took (`raw_slot`), so a slot is released at most once
  by finish or cleanup, never by both. Opt-in PostgreSQL tests cover each outcome,
  replay, slot release and retention, a two-member set and every refusal
  leaving the attempt unchanged. No worker process calls it yet.
  `claim_plan_v1` and `cleanup_set_v1` give terminal sets back their capacity
  after the originating session has ended. `claim_plan_v1` with
  `work_kind: cleanup` takes a fresh worker token and picks the oldest set that
  is terminal with cleanup `pending` or `failed` and has no live cleanup lease. A
  set past its expiry is first expired under its lock, exactly as a user call
  would expire it. The claim stores the token's digest on a 30-second cleanup
  lease. Following the owner's decisions, the lease carries a fixed cleanup
  session marker instead of a user session, its fence is 1 plus the set's earlier
  cleanup leases, and its acknowledgement's `source_fingerprint` is the set's
  creation request digest. Repeating the same claim request returns
  `already_claimed`; with nothing eligible the result is `no_work`. A lapsed
  cleanup lease is closed as expired before the set is handed out again. Prepare
  claims return `import_invalid` until WL-P0-007L adds them.
  `cleanup_set_v1` takes the lease's job ID and fence, the same token, and up to
  twelve proofs. Each proof must name a normalize attempt of this set that was
  bound to the launcher, at most three times. It locks the raw and storage quota
  rows before the set. Every raw slot still held by a fenced attempt is then
  handled once. An attempt that was never bound releases its slot without a
  proof. A bound attempt releases it only when its proofs all say `absent` or
  `not_created`, and the proofs are stored on that attempt. When no slot is left
  held, `_purge_v1` removes the transient rows and releases the storage
  reservation (`purged`). Otherwise, by owner decision, the proofs are kept, the
  set stays `failed` with its storage held, and the next claim retries it
  (`cleanup_pending`). The finished lease stores its acknowledgement for replay.
  The lease trigger enforces the same rules: a slot moves only from `held` to
  `released`, a recorded proof is never removed, and a closed attempt can change
  nothing else. Opt-in PostgreSQL tests cover cancel during reception, cancel
  before claim, expiry before claim, a slot already released by finish, pending
  and failed proofs, oldest-first selection, replay and every refusal leaving
  the lease and slot unchanged. No worker process calls them yet.
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
KURAFOLIO_INGESTION_TEST=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_postgres_migration.py' -v
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
