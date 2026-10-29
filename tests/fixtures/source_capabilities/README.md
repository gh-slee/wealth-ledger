# Source capability fixtures and native test recipe

All values are invented or copied from the repository's existing invented parser
archives. No maintainer ledger, credentials, approvals or user configuration are
included. `catalog.json` is inert example metadata, not an installable provider.
`oracle.json` contains literal context/hash/reference examples; these alone are
not complete, valid financial candidates. Transport tests also construct complete
covered candidates and test parent/economic-reference substitution after decoding.

`worker.py`, `fake_api.py` and this directory's Dockerfile are **test-only**. They
are never included in the production image, source catalog or HTTP dispatcher.
The offline fake API has no endpoint, credentials, network request or scheduler.
It supports only the invented CAD700.00 / BTC0.01000000 acquisition. FILE_IMPORT
and PULL_API preserve those same economic facts while recording their actual,
different transport kinds. Both remain nonbooking after shape validation.

## Frozen worker framing

Input is one compact sorted-key UTF-8 JSON object without trailing bytes, duplicate
keys, floats or unknown fields. The closed operations are:

- `normalize`: `provider` is `wealthsimple` or `bullbitcoin`, explicit
  `format_version`, `raw_base64` and `context_base64`.
- `fake_file` / `fake_api`: `raw_base64` and `context_base64` only.
- `inspect`: no additional fields.
- `probe`: a closed probe name (`network`, `files`, `readonly`, `pids`, `memory`,
  `cpu`, `stdout`, `stderr`, `sleep`, `descendant`). `files` additionally requires
  two invented test-host canary paths; it returns only denied-access flags.
- `malformed_output`: intentionally emits an invalid output frame.

Decoded raw/context/payload caps are10/4/4MiB. Total stdin is16MiB; it does not
increase those inner caps. Context is `adapter_input()`'s minimal typed projection,
not database/realm/session/credential authority. Output is exactly `ok` plus either
`value` or `payload_base64`; invalid input returns the fixed `test_frame_invalid`
code. No caller-supplied callable, module, executable or source code is evaluated.

## Measured containment and outcomes

`test_source_harness.py` requires explicit opt-in, an immutable candidate image ID
and its source-context manifest. It checks source hashes, actual image contents,
a temporary FROM tag before/after build and the child image's base-layer prefix.
Only the three static fixture files enter the child build context. Receipts retain
base/child image IDs, source/fixture hashes, HEAD and actual architecture. Developer
images are explicitly distinguished from final reviewed/accepted candidates.
Retained base aliases prevent temporary-tag cleanup from deleting candidate IDs.

Each child is UID/GID10001, root-read-only, network/ipc none, cap-drop ALL,
no-new-privileges, with no host/database/socket mounts. Its only writable filesystem
is a32MiB noexec/nosuid/nodev /tmp. Environment is cleared to the eight exact
reviewed values asserted by the test. Memory is256MiB with no extra swap, CPU1,
PIDs16, RLIMIT_CPU2/2seconds, nofile64/64 and core0/0.

Image/container setup is bounded separately (build120s, create/control30s).
Execution time is anchored to Docker's actual StartedAt. Concurrent bounded readers
retain at most8MiB stdout and64KiB stderr; overflow always takes precedence over
JSON interpretation, including a race with child exit. A complete within-limit
frame alone may be decoded. Wall limit is10seconds; explicit host cancellation is
measured separately. CPU/OOM/kernel resource termination is `resource_exit`, without
assuming a universal OOM exit code. Other outcomes are `ok`, `frame_rejected`,
`child_error`, `malformed_output`, `output_limit`, `wall_limit`, `cancelled`.

Timeout/cancellation/overflow kills only the exact owned child. The host waits for
reaping (5s), joins stream threads (2s), force-removes that exact container, checks
its disappearance and observes a50ms cleanup margin. Descendants share the cgroup;
there is no host-wide process kill or Docker prune. Receipts contain timestamps,
exit/outcome and retained byte counts, without financial payloads or host secrets.
Exceptional setup/control failures also remove only the owned container and fail
the test; missing Docker is not containment evidence.

Native probes inspect effective settings and attempt invented host file/socket,
environment, network and read-only access. Network-none may expose dormant kernel
tunnel interfaces on some Linux hosts; tests require no IPv4 route and denied
connections, rather than incorrectly requiring loopback to be the only interface.
PID/memory/CPU/output/timeout/cancellation and descendant cleanup are actually run.

Evidence describes only the Linux container architecture actually executed (local
Docker Desktop or CI), not native Windows/macOS containment. Reviewed-code test
limits do not certify arbitrary hostile plugins, a malicious host or kernel escape.
Production upload/runner/final-commit acceptance belongs to the next feature.
