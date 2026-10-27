# Optional PostgreSQL foundation

This is an opt-in developer foundation for future application services. The current
CLI and Web app still use SQLite and Huey. Adding this extra, running its tests or
starting its separate Compose file does **not** switch the Web backend, create
registered users, book financial imports or migrate existing ledgers.

## What is provided

- SQLAlchemy Core repositories over PostgreSQL 18, with psycopg and explicit
  operator-only Alembic migrations. No ORM business model or async rewrite.
- Complete, validated domain-v1 **candidates**, exact canonical bytes, immutable
  source revisions and per-batch references to immutable declaration versions.
  Candidate repository heads require explicit compare-and-swap updates; they are
  not accepted financial heads or calculated holdings.
- Scoped composite foreign keys, ENABLE/FORCE RLS, bounded tenant transactions and
  pool cleanup. One opaque tenant anchor has one portfolio; no login/auth service
  adopts these anchors yet.
- Atomic operation receipts, generation changes, audit and outbox, with a maximum
  of three whole-transaction retries for serialization/deadlock SQLSTATEs.
- Explicit tenant queues with database-clock leases, persistent fencing tokens,
  safe cancellation and one internal database effect receipt. No real import,
  provider, broker, export or dynamically loaded handler is connected.
- An explicit schema migration/status CLI, synthetic Docker test provisioning and
  matching-version empty-database restore acceptance.

Source parsers, financial authority/deduplication, positions/valuation, authenticated
registration and legacy migration remain separate work. Parser API v2, domain
contract v1 and the planned full product V2 are different version boundaries.

## Installation and tests

Use a new virtual environment. Keep build tools in a separate environment, as
specified in [development](development.md); build/runtime packaging pins differ.

```bash
python3.12 -m venv .venv-pg
.venv-pg/bin/python -m pip install -r requirements-pg-test.lock
.venv-pg/bin/python scripts/postgres.py test-environment --output work/pg-tests
```

The last command requires Docker and creates only uniquely named synthetic
resources. It pulls the pinned PostgreSQL 18 image, allocates a random loopback
port persisted across container restarts, generates separate bootstrap/operator/runtime
credentials in private files,
initializes an empty database and writes `work/pg-tests/test-config.json` containing
secret-file references. It refuses an existing output directory. No original CSV,
report, ledger volume, app session or personal instance is read or mounted.

Run the actual integration suite:

```bash
WEALTH_LEDGER_PG_TEST=1 \
WEALTH_LEDGER_PG_TEST_CONFIG="$PWD/work/pg-tests/test-config.json" \
PYTHONPATH=src .venv-pg/bin/python -m unittest discover -s tests -p 'test_postgres_*.py' -v
```

Without the explicit environment opt-in, real-PG tests skip; this must never be
reported as PostgreSQL acceptance. Core/config/package tests that have their
prerequisites may still run. The suite covers real constraints, RLS, races,
rollback and two restores of one synthetic dump into new databases. Local ARM64
and Linux AMD64 CI are different evidence; no Windows/physical-host acceptance is
inferred from Docker availability.

Remove only that recorded test environment after review:

```bash
.venv-pg/bin/python scripts/postgres.py cleanup-test-environment \
  --config work/pg-tests/test-config.json
```

Cleanup verifies exact generated names and test labels before removing its own
container, volume and network. It preserves the evidence/secret directory. It does
not prune images, unrelated resources or any production volume. Protect or remove
private generated files according to your host policy; never commit them.

## Optional service and image profile

`compose.pg-foundation.yaml` is separate from the existing Web Compose file. It
requires an explicitly provided private bootstrap secret file and exposes no DB
port by default. The database lives in its own named volume, with PostgreSQL 18's
parent data directory mounted. This file alone does not install application
schema/roles, start a new Web edition or migrate SQLite. Use a unique Compose
project and never reuse a live database/financial volume for development.

The normal audited application image retains the old entrypoint and SQLite
behavior. To verify the optional PG runtime dependencies explicitly:

```bash
python scripts/docker_context.py --output work/pg-image-context
docker build --build-arg WEALTH_LEDGER_POSTGRES=1 \
  --tag wealth-ledger:pg-foundation work/pg-image-context
```

The default build argument is zero. The PG runtime lock contains SQLAlchemy and
psycopg; Alembic and operator credentials are absent from the runtime install.
Migration source is packaged for the explicit operator environment. Neither image
starts PG or connects/migrates on import. Public image distribution/release and
switching a live backend require their separate acceptance.

## Explicit host operations

Use a dedicated database owned by a separate migration role. Provisioning roles is
an operator action, not a browser feature. Write libpq connection information to an
explicit private regular file accessible only to its owner (mode 0600). Do not put
credentials in shell arguments, Git, examples, logs, image layers or screenshots.
Symlink secret files, missing db/user fields and oversized files are rejected.

The CLI accepts only an explicit secret file:

```bash
.venv-pg/bin/python scripts/postgres.py status --secret-file /private/path/runtime.conninfo
.venv-pg/bin/python scripts/postgres.py migrate \
  --secret-file /private/path/operator.conninfo --runtime-role ledger_runtime
```

Use your actual selected private paths and separately provisioned role. These are
new PG targets, not paths to old SQLite files. `migrate` takes a database advisory
lock, checks target/version and applies one linear Alembic history. It refuses
unknown/newer/divergent schema state and unrecognized nonempty targets. It never
stamps, drops, downgrades or repairs a target automatically. Import, application
startup and worker execution do not call it.

The `postgres` package extra is optional and installs only exact runtime
requirements. Operator/test tools use `requirements-pg-test.lock`. License metadata,
binary bundled notices and artifact hashes are distinct from legal/security
approval; see [third-party notices](../THIRD_PARTY_NOTICES.md).

## Persistence contracts

### Precision and time

The accepted profile stays `decimal-38s-24f-38i-v1`: at most 38 numeric significant
and 38 integer digits, 24 effective fractional digits and 256 lexical characters.
Unconstrained NUMERIC and the exact original token are stored together. Independent
SQL checks reject invalid/nonfinite/mismatched values before token casts; no scale
coercion or floating-point conversion is used. NULL optional value/token pairs
mean unknown. A real zero, negative zero and trailing zeros retain their meaning.

BTC/LBTC quantities use the eight-decimal rule only for the corresponding crypto
or unsupported instrument classification, bound to an immutable instrument version
through a composite FK. A security ticker BTC remains a security. Integral
satoshis cannot be narrowed to signed BIGINT. This is not a supply/valuation rule.

Original source tag/token/offset/zone/precision are retained. Date-only never gains
an invented midnight; legacy unspecified precision stays unspecified. A valid token
whose UTC conversion would overflow is retained with an `unindexable` derived
index state and NULL UTC. Source clocks are separate from real DB job clocks.

### Identity and revisions

An explicit batch UUID is a repository handle, not a source transaction identity.
Source revision keys include connection, provider, nullable source-account key,
kind, source ID, observation ID, record kind and revision. Bounded canonical
selector hashes index the full retained tuple; digest hits compare full content and
fail closed on conflict. Null is distinct from empty text. A legitimate correction
can reuse its fact UUID with a new source revision and explicit parent.

Declarations are content-versioned within tenant/portfolio and bound to each batch's
typed rows. Changing an instrument descriptor does not change old candidate joins.
Financial source authority, cross-connection deduplication and acceptance are not
inferred from these stored revisions or their append order.

### Transactions and jobs

Operation keys are scoped by tenant, portfolio and operation kind. Same key/digest
replays the saved receipt **before** checking the old generation; a changed request
conflicts. New work locks the portfolio root before any affected source/job rows,
checks generation and commits candidate changes, receipt, audit, generation and
outbox atomically. Consistent reads use read-only REPEATABLE READ. No provider HTTP
or report/file publication occurs inside a financial transaction.

Queue claims use `FOR UPDATE SKIP LOCKED`; no strict FIFO/fairness is promised.
Default lease is 60 seconds; heartbeat at most every 20 seconds is the caller's
responsibility. Allowed lease bounds are 15..3600 seconds, attempts 1..3. Tokens and
generations never wrap. Current DB time is checked after locking the row, so a long
lock wait cannot revive an expired lease. Current token, worker, instance
incarnation/epoch and applicable connection/repository generation gate the effect.
Same-owner terminal receipt reads recover a lost successful response; stale workers
cannot overwrite success/error or commit another effect. Delivery is at least once;
this is not exactly-once HTTP/file/email execution.

### Role and policy matrix

| Data | Runtime role | Operator role |
|---|---|---|
| Instance/schema metadata | SELECT only; no secrets/financial values | Migration/restore/version ownership |
| Tenant roots/portfolios | Scoped SELECT; generation update only | Explicit anchor bootstrap, one portfolio per tenant |
| Candidate/declaration/receipt/audit rows | Scoped INSERT/SELECT; immutable revisions | Reviewed migration/restore |
| Connection generation, candidate head, jobs/outbox | Scoped bounded state updates | Reviewed recovery |

Every private table carries tenant+portfolio composite references and forced RLS.
The dedicated operator has an explicit operator policy for whole-instance
maintenance; runtime is neither an owner nor a member of that role and cannot
create schema, disable policies or TRUNCATE. Context is trusted internal input in
this foundation, not user authentication. RLS protects omitted scope predicates;
a compromised app credential issuing arbitrary SQL can change custom settings and
is not magically sandboxed. Future authenticated services must derive context on
the server. Plugins receive no DB handle or operator credential.

## Restore boundary

The tests use an actual matching PostgreSQL dump restored into a **new empty
database**, then reapply reviewed grants/policies. Before runtime access, explicit
`finalize-restore` increments the operator-controlled restore epoch, rotates a fresh
incarnation UUID, fences unfinished jobs and preserves committed receipts. Two
restores of the same old dump must have different incarnations, even if their epoch
counter is equal; an old restored worker handle must still fail.

This command is only the final gate of a separately reviewed restore procedure:

```bash
.venv-pg/bin/python scripts/postgres.py finalize-restore \
  --secret-file /private/path/restored-operator.conninfo --runtime-role ledger_runtime
```

Do not grant/start runtime workers on a newly restored target before this gate.
A DB-only restore is not complete app/artifact/key recovery. Full legacy adoption,
coordinated backup and actual financial cutover are separate work; existing SQLite
backup procedures remain in [Web backups](web-backups.md). Preserve originals and
version-matched backups. Never fall back to stale SQLite after PG writes or assume
an older image can read a newer PG data directory.

### Exact candidate admission and replay limits

Source selectors use the existing 4 MiB canonical budget, including multibyte and
JSON-escaped text. Their indexes contain bounded SHA-256 values; complete text is
compared to detect collisions. Each source revision has a typed, versioned,
tenant/portfolio-scoped connection foreign key and selector/reference agreement,
including the provider digest for that immutable connection version. Long provider
text is compared by a bounded hash binding rather than indexed as unbounded text.

PostgreSQL text/JSONB cannot represent U+0000. This optional repository explicitly
rejects a candidate containing that character with `invalid_candidate`, before
opening a transaction, even where the domain codec admits metadata with it. It
never removes/replaces the character, changes the core domain contract, writes a
partial candidate or reports that admission failure as a database outage.

A lease is checked against the persisted job's immutable expected generation and
source binding, plus the claimed attempt and lease duration. Copying a handle does
not rebase work or remove a source fence. Completion locks the portfolio, actual
persisted source reference, then job; it samples the database clock after locks.

An exact batch-ID/byte replay without head updates returns its original outcome.
A fresh operation key adds only an immutable key/digest-binding receipt; candidate
rows, generation, audit and outbox do not change. Reusing that key with changed
content conflicts. Saved-key replay precedes generation checks. An explicit head
update is still a new CAS operation, even when its candidate bytes already exist.

## Separate optional identity acceptance

The explicit0002 identity service has its own [operator/API and test workflow](web-v2-identity.md).
Its synthetic marker/configuration, roles and databases are separate from0001
foundation tests. Run identity SQL/HTTP plus native optional-image acceptance;
missing opt-in execution is a skip, not a pass. The default SQLite Web/CLI and
0001 migration/DDL remain unchanged. Do not activate0002 on an existing ledger
merely to test a source change.
