# Optional V2 identity service

This separate backend is under local implementation/acceptance review. It is not
an upgrade path for the existing SQLite Web App. Do not change a running ledger's
entry point or database to try it. The setup wizard, registration UI and invitation
pages belong to a later frontend slice; no V2 financial import/export service is
claimed here. See [capabilities](capability-status.md) and [the PG foundation](postgres-foundation.md).

## Model and trust boundary

A trusted host arms first setup with a 30-minute, one-use random code. Protected
`POST /api/v2/auth/setup` creates exactly one administrator and one empty portfolio,
then permanently closes setup. Restart, disabling the administrator, missing files
and restore never reopen it. There is no default account or first-visitor claim.

Later users redeem 24-hour, single-use invitations, choose credentials and then
log in separately. One user has one V2 portfolio; this does not change existing
SQLite multiple-portfolio behavior. Usernames are case-insensitive ASCII
`[A-Za-z0-9_.-]`, 1–64 characters, preserving display spelling. New passwords are
15–256 Unicode code points; spaces are accepted, with no normalization or silent
truncation. Login/current-password input accepts 1–256. NUL/surrogates are rejected.

The sole administrator can issue/list/revoke invitations, and read only their own
financial scope. Password recovery and account enable/disable remain host-only.
There is no promotion, impersonation, other-user finance access or public signup.

The trusted API uses two distinct PostgreSQL login roles:

- Identity gateway: exactly 15 reviewed definer functions; no raw identity or
  financial tables, operator functions, protected-schema DDL or role membership.
- Financial runtime: scoped candidate/job repositories and the existing FORCE RLS
  foundation; no identity access or tenant-anchor insertion.

The operator owns migrations/functions and is never configured in the API/worker.
RLS guards against missing/mistaken scope; it is not protection from a compromised
trusted server role capable of choosing tenant GUCs. Do not expose PostgreSQL.
Both DSNs must explicitly describe the same direct host/port/database/TLS target;
service/passfile/environment discovery, multi-host routing and PG proxies are not
supported. Actual database/peer/incarnation/epoch and effective grants are checked.
A request principal is immutable and revalidated each request; the actual financial
transaction checks its realm before scope or facts. No request-supplied UUID/header
selects another user. Current source APIs remain separate.

## Operator setup

Use Python 3.12+ and locked Web/PG dependencies. Foreground migration additionally
needs Alembic from `requirements-pg-test.lock`; runtime does not need Alembic.
Use the [foundation role preparation](postgres-foundation.md#explicit-host-operations)
with a third distinct nonowner `ledger_identity` login role. Configure its password
interactively through the host's PostgreSQL tooling. No role may be superuser,
BYPASSRLS, CREATEDB, CREATEROLE or a member of a privileged role. The operator must
own the intended database; migration does not create roles or grant CREATEROLE.

Keep connection files and the 32-byte instance key outside the checkout, regular
files with mode 0600 (not symlinks). DSNs require explicit host, port, dbname, user,
password and sslmode, with matching target/TLS options. Never pass a password as a
CLI argument/environment variable or include it in an issue. Protect parent folders.

```bash
PYTHONPATH=src python -m wealth_ledger.web_v2 --help
PYTHONPATH=src python -m wealth_ledger.web_v2 instance-key create \
  --output /path/to/private/identity.key
PYTHONPATH=src python -m wealth_ledger.web_v2 operator migrate-identity \
  --secret-file /path/to/private/operator.conninfo \
  --runtime-role ledger_runtime --identity-role ledger_identity \
  --key-file /path/to/private/identity.key
PYTHONPATH=src python -m wealth_ledger.web_v2 setup arm \
  --secret-file /path/to/private/operator.conninfo \
  --output /path/to/private/setup-code
PYTHONPATH=src python -m wealth_ledger.web_v2 serve \
  --identity-file /path/to/private/identity.conninfo \
  --financial-file /path/to/private/runtime.conninfo \
  --key-file /path/to/private/identity.key \
  --origin http://127.0.0.1:8080 --host 127.0.0.1 --port 8080
```

These are new, explicit commands; the default Compose/CLI Web entry stays unchanged.
An HTTP listener must bind a literal loopback address (`localhost` is pinned to
127.0.0.1). Any non-loopback bind requires an HTTPS origin **and actual TLS** through
`--tls-cert-file /path/to/private/certificate.pem --tls-key-file /path/to/private/transport.key`.
Both files must be regular0600files; the certificate/key pair is validated before
application/database activation. An HTTPS origin alone never permits a public
plaintext listener. An explicitly configured external HTTPS terminator can forward
to a loopback-only listener; forwarded headers remain untrusted.
Forwarded headers never select the caller's quota peer or financial scope. The API
has no operator connection/configuration. Do not use example ports on a real instance
without choosing its isolated storage, network and recovery plan.

A client first obtains the anonymous cookie and CSRF token from
`GET /api/v2/auth/csrf`, then sends the exact configured `Origin`,
`X-CSRF-Token` and JSON `{setup_token, username, password}` to setup. Success is
201 `{initialized:true}`, clears the anonymous cookie and does not log in. Obtain
new CSRF, then POST `{username,password}` to `/api/v2/auth/login`.
Tokens/passwords belong in request bodies, never URLs or persistent browser storage.

Host commands use the same module prefix:

```bash
# Opaque IDs come from command output or the retained private receipt.
python -m wealth_ledger.web_v2 setup revoke --secret-file /path/to/private/operator.conninfo --record-id SETUP_UUID
python -m wealth_ledger.web_v2 invite issue --secret-file /path/to/private/operator.conninfo --output /path/to/private/new-invite
python -m wealth_ledger.web_v2 invite revoke --secret-file /path/to/private/operator.conninfo --record-id INVITE_UUID
python -m wealth_ledger.web_v2 account reset-password --secret-file /path/to/private/operator.conninfo --user-id USER_UUID
python -m wealth_ledger.web_v2 account disable --secret-file /path/to/private/operator.conninfo --user-id USER_UUID
python -m wealth_ledger.web_v2 account enable --secret-file /path/to/private/operator.conninfo --user-id USER_UUID
python -m wealth_ledger.web_v2 identity status --secret-file /path/to/private/operator.conninfo
```

Password reset uses hidden TTY input and confirmation. For a protected pipe, add
`--password-stdin`; close the pipe with EOF. Only the final input newline is removed; interior newlines are preserved. Do not put a password
in shell history, process arguments, chat or example scripts. Reset does not enable
a disabled account. Username changes/additional administrators are not implemented.

## Invitation recovery and secret files

Admin APIs require the current live administrator session and CSRF on mutations:

| API | Body/query and result |
|---|---|
| `POST /api/v2/admin/invitations` | Only `{issue_request_id: UUID}`; 201 returns id/request ID/expiry and the newly created raw token once. |
| `GET /api/v2/admin/invitations` | Exact `issue_request_id`, or optional `after`/`limit` (1–100, default 50); metadata only, with `next_after`. |
| `POST /api/v2/admin/invitations/{id}/revoke` | Exactly `{}`; 204 with no body. |

Generate a fresh, nonsecret request UUID before issue. If the response is lost,
look up that request ID. Repeating issue returns `invite_already_issued` and never
replays a token. If the token was not safely received, revoke its record ID and
issue with a **new** request ID. Lists never expose bearer/digest or consumed user IDs.

Host setup/invite exports create a new 0600 secret file and a companion
`<output>.receipt.json` containing only kind/opaque record ID and pending recovery
state. The ID is fsynced **before** commit so native termination after commit still
leaves a reconciliation handle. Existing files/links are never overwritten. Export
write/fsync/close failure revokes the exact record when possible; otherwise the error
reports its ID as unresolved. A hard-killed command can leave an empty/partial secret
file and pending receipt: keep both, revoke that exact ID, confirm the outcome, then
use a new output filename. Do not infer rollback from missing output or reuse a token.
Receipts and secret files are private operational data, never source fixtures.

## HTTP/security contract

The optional service exposes health/readiness, auth, own `me`, read-only candidate
batches/jobs, checked invitations and session-protected `/api/v2/openapi.json`.
No v1 fallback, static report route, default OpenAPI/docs page or portfolio selector
is mounted. Candidate responses are raw canonical domain-v1 JSON bytes. Job DTOs
contain only id/kind/status/attempt/error_code; unknown stored error codes are sanitized.

Cookies are HttpOnly, SameSite=Lax, Path=/, no Domain; HTTPS uses Secure and the
`__Host-` prefix. Anonymous lifetime is 600 seconds; authenticated idle/absolute
limits are 1,800/43,200 seconds. Safe GET/CSRF polling does not extend idle; explicit
CSRF-protected activity does. Logout/reset/disable/password change invalidate the
appropriate sessions. All private/error responses are no-store with content,
referrer and framing protections. Generic errors contain code/message/request ID,
never validation input, passwords, hashes, SQL or database identifiers.

Duplicate sensitive headers/cookies, bad Host/Origin/CSRF, unknown fields/query
selectors and malformed UUIDs are rejected. JSON is capped at 16 KiB with a 10-second
body deadline starting at ASGI entry, including waiting for the first body event.
There are eight admitted requests and two password-work slots per API process;
database-backed peer/instance/subject budgets survive process restart. Database
connections/pools/locks/statements have explicit limits. Health bypasses database
and hashing; readiness has a separate 15-second probe deadline. Database time is
sampled after ordered locks, with a durable nondecreasing high-water mark; time
rollback fails closed rather than extending sessions/quotas.

## Backups, restore and rollback

A dump alone is incomplete: retain the matching source/image version, protected
instance key, role/configuration evidence and data manifest. Never restore over a
running/later-written instance. Stop the isolated target and restore a matching
0002 dump into a **new empty** database; withhold runtime grants/activation until
trusted finalization, role/key/realm and data verification succeed.

```bash
python -m wealth_ledger.web_v2 identity finalize-restore \
  --secret-file /path/to/private/restored-operator.conninfo \
  --runtime-role ledger_runtime --identity-role ledger_identity \
  --key-file /path/to/private/matching-identity.key
```

Finalization rotates incarnation/epoch, fences foundation jobs, revokes all raw
outstanding invitations (including time-expired ones) with reason `restore`, and
appends one restore lifecycle audit. Consumed/manual-revoked history, opaque IDs,
request mappings and enabled/disabled flags remain intact. Repeated finalization
rotates again with one further audit, preserving terminal invitation states.
Old sessions/codes/invitations fail. Restored credentials are quarantined: the host
must explicitly reset each account's password before login; reset does not enable
a disabled user. A new invite must be issued. An uninitialized/unknown-lifecycle
V2 backup cannot activate setup; create a genuinely fresh installation instead.
An older dump cannot preserve unseen later password changes, disables or financial
writes; recovery uses the chosen backup point. Normal restore requires the matching key. If that key is permanently unavailable,
keep the original service/data unchanged and work only on a verified new isolated
restore target. Create a **new** private key file at a new path, then explicitly
finalize that isolated target with replacement:

```bash
python -m wealth_ledger.web_v2 instance-key create --output /path/to/private/recovered-instance.key
python -m wealth_ledger.web_v2 identity finalize-restore \
  --secret-file /path/to/private/restored-operator.conninfo \
  --runtime-role ledger_runtime --identity-role ledger_identity \
  --key-file /path/to/private/recovered-instance.key --replace-missing-key
```

This operator-only mode atomically rebinds the new key while rotating epoch and
quarantining every credential, preserving administrator/disabled flags and applying
the same invitation/job/audit rules. It rejects reuse of the saved key as replacement.
Normal mode still rejects a mismatched key. Configure the target API with the new
key; an old-key API cannot authorize new requests. The original backup/key/data are
never overwritten. Retain new key/dump hashes and verification receipts privately.
This is isolated recovery, not live key rotation or an automatic lost-key fallback.

For a backward database clock, stop activation of the affected service and preserve
its dump/key/version. On an isolated target the trusted operator diagnoses
`clock_timestamp()` and `wl_identity.instance_auth_state.last_observed_at`. Correct
the host/system clock through host administration, or wait until actual database
time meets the saved high-water and all existing timestamp guards. Then perform
normal isolated finalization and explicit credential resets. The application never
lowers a saved watermark, rewrites historical user dates, overrides runtime time or
revives expired sessions. Forcing recovery while time remains below the saved mark
requires a separately reviewed design; it is not an existing command.
Full application artifact recovery/cutover remains separate from this identity slice.

Identity migration takes the operator advisory/instance/auth locks in order and
recognizes a closed PG18 object inventory, including routines, types, table columns,
constraints, triggers, policies and indexes. Fixed catalog identity fingerprints
come from the unchanged0001 and explicit0002 DDL; they contain no row data or OIDs.
Unknown objects are refused before changes, not dropped or repaired. A new DDL
contract needs an ordered reviewed revision.

Do not downgrade 0002 to 0001, drop schemas, stamp an unknown target or fall back to
SQLite after V2 writes. Keep the optional service stopped and preserve evidence;
forward repair or separately reviewed recovery is required. Existing SQLite backups
and services are unaffected. See [current Web backups](web-backups.md).

## Isolated development acceptance

```bash
python scripts/postgres.py test-identity-environment --output work/identity-tests
WEALTH_LEDGER_IDENTITY_TEST=1 \
WEALTH_LEDGER_IDENTITY_TEST_CONFIG=work/identity-tests/test-config.json \
PYTHONPATH=src python -m unittest discover -s tests -p 'test_identity_*.py' -v
WEALTH_LEDGER_IDENTITY_TEST=1 \
WEALTH_LEDGER_IDENTITY_TEST_CONFIG=work/identity-tests/test-config.json \
PYTHONPATH=src python -m unittest discover -s tests -p 'test_web_v2_api.py' -v
```

Build the optional runtime profile using a source-only context, then set
`WEALTH_LEDGER_IDENTITY_RUNTIME_IMAGE` to that **immutable image ID** and run
`test_web_v2_native.py`. It executes real Linux HTTP with 16 independent API
processes/transport peers, staged real password hashing, and barriers before SQL
acquisition; it also checks a nonroot two-user image. Clock overrides and process
barriers are test-only code on explicitly marked synthetic targets, never production
flags, environment bypasses or headers. Native SIGKILL, real lock waits and two
empty-target dumps have separate tests. Default opt-in skips are not acceptance.
Keep failed logs/oracles and independent review evidence. Cleanup may remove only
the exact recorded synthetic resource IDs using `cleanup-test-environment`.
