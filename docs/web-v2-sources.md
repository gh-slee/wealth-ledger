# Optional V2 source capabilities and connections

The optional `sources` backend profile implements inert catalog discovery,
per-user FILE_IMPORT enablement and explicitly selected, reusable connections.
It uses PostgreSQL revision `0003_source_lifecycle`. This is a development backend,
not a replacement for the supported SQLite Web/CLI workflow. Production V2 upload,
financial acceptance and UI are separate delivery stages. Enabling a capability or
creating a connection never imports data or produces a financial observation.

The current adapters are Wealthsimple holdings and Bull Bitcoin orders. Both use
the existing parser protocol2, not a new institution-specific ingestion engine.
A test-only offline API adapter verifies the domain1 contract; it does not enable
live API synchronization. There is no universal CSV parser or automatic provider
installation. All behavior is deterministic code, without runtime LLM calls.

## Identity, installation and reconfirmation

A plugin definition identifies a provider and displays reviewed metadata. An
installation descriptor additionally pins the package/version, entry point,
artifact SHA-256, immutable execution-image digest, source/domain/parser contract
versions, payload kind, format versions, categories, alias policy and execution
profile. The installation ID is the SHA-256 of its exact canonical descriptor.
Catalog enumeration reads metadata only: it never imports factories, detects a
file, opens a connection or calls a provider.

Operator catalog snapshots are immutable inputs to activation. Catalog revisions
advance with changes; per-installation availability generations advance on status
changes, including retirement followed by reactivation. Prior descriptors and
installation history remain. A different active installation does not silently
replace a user's approved version. The user must explicitly reconfirm that exact
installation, then rebind affected connections. Old previews remain invalid even
if availability later returns to the same status.

Each user owns one portfolio, with multiple financial accounts and source
connections. Enablement is per user/plugin/capability; it is not a global switch.
Connections are created explicitly and reused for later exports. A single
Wealthsimple export can contain TFSA/RRSP/non-registered accounts through one
connection. Separate Bull accounts/export streams can have separate connections.
Bull requires an explicit stable parser-source alias; Wealthsimple forbids one.
The alias and canonical connection identity are immutable. A display-label edit
changes the lifecycle revision without changing canonical identity/generation.
Authorization changes advance the connection generation. Disabling a plugin does
not rewrite every connection or delete historical facts. Re-enabling it does not
re-enable a separately disabled connection.

There is no implicit adoption of legacy canonical connections. Capacity counts
all distinct canonical IDs, including those without a lifecycle sidecar, against
the256-connection limit. Unknown/foreign IDs return the same scoped not-found
response. Deletion and automatic merging of financial streams are unsupported.

## Explicit operator setup

Install the existing locked optional PostgreSQL/Web dependencies and follow
[the PG guide](postgres-foundation.md) and [identity setup](web-v2-identity.md).
Use a new, intentionally selected development database. Never run a migration
against a personal portfolio merely to try this profile. Normal startup does not
migrate, install, fetch metadata or activate the sources profile.

Create a private canonical catalog file from
[the empty example](../config/source-catalog.example.json). It contains no default
provider installation or seeded user. Protect catalog, connection-info, proof and
key files as regular private files (0600); do not commit them. The key is32bytes.

```bash
python -m wealth_ledger.web_v2 operator migrate-sources \
  --secret-file /private/example/operator.conninfo \
  --runtime-role example_finance --identity-role example_identity \
  --key-file /private/example/instance.key \
  --source-catalog-file /private/example/source-catalog.json

python -m wealth_ledger.web_v2 sources status \
  --secret-file /private/example/operator.conninfo \
  --runtime-role example_finance --identity-role example_identity \
  --key-file /private/example/instance.key \
  --source-catalog-file /private/example/source-catalog.json
```

Migration accepts only an empty target, an exact recognized0002 predecessor, or an
already matching0003 target. It verifies declared tables/columns/constraints,
functions/bodies/owners, RLS, indexes, triggers and effective role privileges.
Unknown objects, tampered functions or expanded grants fail closed. The original
0001/0002 providers stay byte-identical;0003 installs its explicit replacements.
A failed migration rolls back its complete transaction. Never downgrade in place
or run0002 code against a0003 database.

To install/reactivate a reviewed catalog, supply an explicit private content-proof
input and a compare-and-swap revision:

```bash
python -m wealth_ledger.web_v2 sources catalog-apply \
  --secret-file /private/example/operator.conninfo \
  --runtime-role example_finance --identity-role example_identity \
  --key-file /private/example/instance.key \
  --source-catalog-file /private/example/reviewed-catalog.json \
  --source-proof-file /private/example/source-proofs.json \
  --expected-catalog-revision 0
```

The proof input has exactly this structure (use real reviewed IDs/files):

```json
{"format":"source-proof-input-v1","installations":[{"installation_id":"<descriptor-sha256>","artifact_file":"reviewed-content.json","image_root":"/app/src"}]}
```

Relative artifact paths resolve against that proof file's directory. The artifact
is canonical `source-content-v1` JSON: package distribution/version, declared
entry points and a sorted list of exact relative package paths/SHA-256 values.
It is not an arbitrary wheel, self-attested browser claim or permission to import
code. The foreground host operator checks its descriptor hash and every actual
package file in the pinned image, using a new stopped, volume-free container.
It rejects unexpected files, links, mismatches and image-declared volumes, then
removes that exact proof container. Docker is a host-side proof/test prerequisite;
no Docker SDK/socket is given to the application or a parser child. No plugin is
executed by catalog activation. Proofs are transient code-owned objects, not
serializable HTTP authority. Unchanged matching catalog application is a no-op.

Start only with an explicit matching profile/catalog:

```bash
python -m wealth_ledger.web_v2 serve \
  --identity-file /private/example/identity.conninfo \
  --financial-file /private/example/finance.conninfo \
  --key-file /private/example/instance.key \
  --source-catalog-file /private/example/source-catalog.json \
  --schema-profile sources --origin http://127.0.0.1:8100 \
  --host 127.0.0.1 --port 8100
```

Default `identity` behavior remains exact0002. Host setup/invite/account commands
can explicitly use `--schema-profile sources`; their existing protection and secret
export rules remain. Status output contains safe counts/revisions, not DSNs,
role names, keys or installation artifact paths.

## Closed authenticated HTTP surface

All routes require the live authenticated session and actual SQL realm. Writes
also require exact Origin/CSRF. Decimal counters are canonical strings, not JSON
numbers, booleans or values with leading zeros. Unknown fields are rejected.

| Method/path | Purpose |
|---|---|
| GET `/api/v2/sources` | Safe catalog/capability metadata and scoped enablement |
| PUT `/api/v2/sources/{plugin_id}/capabilities/{capability}` | Enable/disable or explicitly reconfirm FILE_IMPORT |
| GET `/api/v2/source-connections` | Scoped, revision-pinned paginated connections |
| POST `/api/v2/source-connections` | Explicit new FILE_IMPORT connection |
| GET `/api/v2/source-connections/{id}` | Own connection and current availability |
| PUT `/api/v2/source-connections/{id}` | Rename, disable/re-enable or reconfirm binding |

Read pages use bounded `limit` and `after`. A cursor requires the returned
`catalog_revision`, `state_revision`, `incarnation` and `restore_epoch` as separate
query parameters. The public realm contains only `incarnation` and `restore_epoch`;
the complete actual database realm stays internal and is checked independently.
These fields are not a caller-created tenant assertion. The strict DTOs in [schemas.py](../src/wealth_ledger/web_v2/schemas.py)
are authoritative for each route's fields. PUT/POST carry `operation_id`,
`expected_revision` and `expected_realm` plus their operation-specific fields.
Create additionally supplies plugin/capability/installation, display label and
nullable alias. Enablement supplies `enabled` and an installation ID when enabled;
connection updates supply the explicitly selected binding/label/enabled state.

There are no upload, delete, install, credential, sync, scheduler or PULL_API
execution endpoints. PULL_API is recognized metadata but receives a semantic409
capability-unavailable result when requested here; unknown capability values are
invalid input. Connection identity/provider/alias cannot be changed via a label edit.

Mutations use restricted EXECUTE-only database functions, fresh session/role/realm
checks, a fixed lock order and a final database clock sample. The finance role
remains read-only. Ordinary lifecycle changes do not advance financial fact
state, enqueue financial jobs or publish reports. CAS conflicts have no effects.
An operation UUID is unique across mutation kinds within the user's current realm;
reusing it with different canonical input conflicts. Exact retries return the
immutable historical receipt, including after a lost COMMIT acknowledgement.
A historical representation is not current enablement/booking authority. A changed
realm requires a new preview/request, not a relabelled old receipt.

Source budgets are database-shared across API processes:60 reads/user and600 per
instance,30 writes/user and300 per instance in300seconds. After authentication,
Origin/CSRF checks, even invalid source DTOs consume the relevant source budget.
The20-second lifecycle deadline includes lock/retry work. Exhausted signed64-bit
counters refuse changes instead of wrapping. Safe no-store DTOs exclude internal
artifact paths, raw descriptors, SQL errors and credentials.

## Nonbooking normalization contract

`data_sources/contract_v1.py` separates domain1, parser2 and source-transport1.
The trusted full context binds the exact installation, availability/enablement/
connection generations, tenant/portfolio, internal realm, mapping/evidence and
caller-owned provenance/reference graph. Child input is only its minimal typed
adapter projection, without sessions, database identity or realm fingerprint.
Source and domain diagnostics use separate namespaces and deterministic ordering:
framing/size, context, versions/format, fingerprint, base64 limits, payload hash,
all payload decoding, reference/provenance binding, then bridge mapping blockers.
Direct-domain parent/economic references must match the independently supplied
allowed graph; output never manufactures its own permissions. Successful shape
validation always has `ingestible=false`. Live historical authority and atomic
financial acceptance are separate, unimplemented V2 import work.

## Restore and recovery limits

A matching initialized0003 dump must be restored into a new empty target using
matching code/key/catalog/installation proofs, then explicitly finalized:

```bash
python -m wealth_ledger.web_v2 sources finalize-restore \
  --secret-file /private/example/restored-operator.conninfo \
  --runtime-role example_finance --identity-role example_identity \
  --key-file /private/example/instance.key \
  --source-catalog-file /private/example/source-catalog.json \
  --source-proof-file /private/example/source-proofs.json
```

Only the explicit offline finalizer recognizes the exact no-ACL shape produced by
`pg_restore --no-acl`; it rejects mixed/unknown grants and applies/verifies the
known runtime privileges atomically. Normal startup/migration never repairs an
unrecognized privilege state. Source rows, canonical identities, counters,
disables, immutable receipts/audits and availability generations remain unchanged.
Finalization rotates incarnation, advances restore epoch, revokes issued invites
with the restore reason, quarantines old credentials and fences old jobs/forms.
Consumed/manual-revoked invitations and historical source receipts remain. Host
password reset is needed before old users can log in again. Bootstrap stays closed;
uninitialized backups cannot be activated. Recovery cannot recreate post-backup
writes or configuration disables. Never restore over a live database or erase
source metadata to satisfy an older schema. Database fixture restore verification
is not the future complete V2 application/key/artifact backup/migration feature.

## Synthetic verification

See [the test recipe](../tests/fixtures/source_capabilities/README.md) for exact
worker framing/outcomes/settings, bounded streams, native canaries/resource probes
and cleanup. Docker containment is test-only, with no running production launcher.
Use the locked PG test environment; see [development](development.md#optional-source-profile-acceptance).
Self-tests, independent review, merged CI and an actual deployment are distinct
facts. Local native receipts establish only their recorded Linux architecture;
there is no claim of native Windows/macOS containment or arbitrary hostile-plugin
security. No UI or financial report behavior changes in this scope.
