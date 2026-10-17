# Source adapters and user-defined parsers

**SRC-001 is implemented as a Python version-1 normalization contract in
`wealth_ledger.source_protocol`.** General registration, external plugin loading,
an author SDK and migration of the current importers are still planned (SRC-002-004).
The normal CLI still accepts only the existing Wealthsimple/Bull formats and explicit
flow/BTC commands. The official ETF registry is separate. See [TODO](../TODO.md).

## Goal

Let developers/users implement trusted parsers for additional bank, broker and
crypto-exchange CSVs without changing SQLite history or report code for each source.
Detection/normalization are extensible; core validation, atomic submission,
deduplication/revisions, tracking scope and reporting remain central.

All production work must be reproducible Python, independent of LLMs, agents,
browser login or local office software. The protocol below is available for contract development; it is not an enabled
import interface. Future loading/submission commands do not exist yet.

## Version-1 canonical record kinds

| kind | Purpose | Required boundaries |
|---|---|---|
| `holdings` | Accounts, positions, cash and source cost at a source time | Full/partial account scope, valuation time, instrument identity, currency, revisions |
| `cash_flows` | External deposits/withdrawals, tracked-account transfers, income/fees | Portfolio boundary, paired legs, dates, FX evidence, coverage declarations |
| `crypto_transactions` | Purchases, sales, delivery, fees and internal/external transfers | Network/asset, precision, cash counterpart, cost coverage, status and cross-source duplicates |

Record count cannot establish completeness; source scope or an explicit declaration
is required. Unknown fees/costs/missing cash counterparts stay unknown. Unsupported
kinds/types must be rejected or identified as incomplete rather than silently skipped.

## Versioned protocol and registration

Each adapter declares stable provider/adapter IDs, adapter version, supported export
versions, protocol API version and kinds. Provider/account namespaces must not depend
on filenames or repeated display names; platform IDs must not collide.

Core registration and external package entry points use versioned contracts. Reject
unsupported API versions, duplicate adapter IDs and invalid capability declarations
before execution rather than guessing compatibility. Enabled adapters/versions may
be saved in ignored local configuration and operation evidence. A public clone
must not automatically load a maintainer-specific parser.

Built-in/external adapters share contract tests. External dependencies are explicitly
installed/enabled by the user; encountering a CSV never downloads Python code.

## Separate detection, normalization and submission

1. **Detect:** inspect necessary fields/format features and return an auditable
   match/version without real writes, private credentials or code downloads.
2. **Resolve ambiguity:** reject no matches. Multiple trusted matches require an
   explicit source choice, not LLM/filename guessing.
3. **Normalize:** produce defined canonical records and source/coverage metadata,
   mappings and warnings, without writing SQLite or generating reports.
4. **Validate centrally:** check Decimal, dates/timezones, asset/account identity,
   source IDs, status, transfers, scope and cost coverage, then submit atomically.
5. **Retain evidence:** raw SHA-256, format/adapter/protocol versions, source effective
   time, normalized results and operation ID support replay and revisions.

Offline `--dry-run` must reuse detection/normalization/validation without modifying
the real project, performing new network queries or retaining temporary IDs. An
external parser unable to meet these limits cannot claim this preview contract.

## Required canonical semantics

- Account identity combines provider namespace/source account ID, not display names
  or masked suffixes alone.
- Positions retain market/asset/currency identity and original cost. Matching ticker
  text alone cannot merge instruments from different sources.
- Economic events use stable source IDs with completed/pending/cancelled state and
  effective times. Missing IDs need an explicit auditable policy, not amount/date-only deduplication.
- Distinguish reimports, content conflicts and legitimate equal-time/amount events.
  Economic revisions/cancellations and input corrections must not silently overwrite.
- Trace original values, currency direction, network, fees and evidence. A transfer
  reference alone does not verify every counterpart.
- Keep observed balances distinct from transaction history. Do not add pre-observation
  transactions again or automatically label discrepancies as fees.
- Account additions/removals require explicit scope revisions; format changes are
  not evidence of investment growth.

The concrete version-1 dataclasses and validators are described below. Database
migration, stateful deduplication/revisions, portfolio boundary matching and
submission are still SRC-004 work. A structurally valid batch alone cannot establish
financial completeness or authorize a contribution.

## Implemented protocol surface (SRC-001)

`source_protocol.py` provides frozen dataclasses and a `SourceAdapter` Protocol:

- `AdapterInfo`: API version **1**, provider/adapter namespace, adapter version,
  supported export versions and record kinds. `validate_info` rejects unsupported
  versions, invalid/duplicate capabilities and unstable namespace syntax.
- `AccountKey(provider, account_id)` and `RecordKey(account, source_id, revision,
  supersedes_revision=None, change="original")`: identity never depends on a path
  or display label. Corrections/voids require a distinct superseded revision.
- `AssetKey(kind, symbol, currency, market=None, network=None, identifier=None)`:
  securities require a market; crypto requires a network; cash matches its currency.
  `currency` is the valuation currency. BTC/LBTC quantities require whole satoshis.
- `Holding`: source time, signed Decimal quantity, market value and optional cost.
  `CashFlow`: positive amount, direction/type, status, explicit boundary and optional
  counterpart references. Counterpart source IDs require their provider/account
  namespace; a transfer reference does not verify the other leg.
- `CryptoTransaction`: source-reported signed `CryptoLeg` quantities, status,
  optional acquisition cost, fees and transfer/counterpart references. `fees=None`
  means unknown; `fees=()` means explicitly no separate fees. Do not apply the same
  fee to a leg and acquisition cost twice. BTC and LBTC retain different networks;
  this contract does not automatically net swaps or infer contributions.
- `Coverage`: kind/account, inclusive timezone-aware start/end, completeness,
  declared basis, scope ID and scope revision. Every record must have a covering
  declaration. An empty record list cannot change declared completeness.
- `SourceEvidence`: raw SHA-256, effective/fetch times, source reference, field
  mappings, warnings and stable-ID policy. `NormalizedBatch` retains this evidence,
  adapter/version, selected export version, coverage and records.

`detect(raw: bytes) -> Detection` and
`normalize(raw: bytes, *, export_version: str) -> NormalizedBatch` are pure trusted
Python operations. They receive no workspace, credentials or database. No network,
file writes or subprocesses are permitted. This is a contract, not a Python sandbox.
`resolve_detection` accepts already evaluated trusted results, rejects duplicate
adapter IDs and zero/multiple matches, and never discovers or installs code.

`validate_batch(batch, raw)` checks hashes, versions, kinds, Decimal/nonfinite
values, timestamps, currencies, identity, coverage, local revision shape, status
and satoshi precision. Each source record may occur only once per kind/account in
one batch; adapters must resolve export revisions explicitly. Event voids require
cancelled status. Pending/cancelled records remain evidence and must not be booked
as completed activity. Observed BTC totals remain the existing balance-observation
API, not crypto transactions.

`canonical_json` preserves Decimal as strings, aware ISO timestamps, null unknowns
and all version/evidence fields. Validate first. It is a deterministic evidence
serializer, not a database importer or generic JSON deserializer.

Future transactional checks must still verify revision lineage against the ledger,
portfolio membership, duplicate economic effects across sources, cash counterpart
completeness, transfer matching, disposal/cost allocation and scope changes. Batch
validation does not claim these stateful checks are implemented. No runtime LLM is
involved. The offline synthetic acceptance cases are in `tests/test_source_protocol.py`.

## Banks, brokers and exchanges

**Banks:** establish deposits/withdrawals across the investment boundary. Importing
a bank CSV does not add bank cash to investment assets; tracked cash-account scope
must be explicit. Bank outflow and broker inflow can be one movement requiring
auditable matching, not two contributions.

**Brokers:** snapshots and activity/trade history are different kinds. They can
complement each other, but trade turnover is not external contributions. In-kind
transfers, multiple currencies, splits and refunds require supported source/scope policies.

**Exchanges:** separate purchases/sales/deposits/withdrawals/fees and own-wallet
transfers. Exchange delivery and wallet receipt must not double count. A sale with
no cash counterpart cannot invent cash; quantities alone do not establish complete cost.

## Intended custom-parser workflow

After the SDK is implemented, users should be able to:

1. Read the public protocol/schema and synthetic example plugin.
2. Implement detection/normalization with explicit supported formats/types.
3. Run offline mapping/deduplication/timezone/revision/scope/transfer/fee contract
   tests using synthetic or properly sanitized fixtures.
4. Install a trusted package into their venv and enable registration/entry points
   without editing the core.
5. Preview offline before normal core submission; maintain parser versions/tests
   when export formats change.

No SDK installer or enable command exists yet. SRC-001 is complete; implement
SRC-002-SRC-004 after the first usable Web MVP before claiming additional support.

## Trust and publication

External Python plugins run with the user's permissions, not in a sandbox. Install
trusted code and manage versions/dependencies explicitly. Never execute Python
inside CSVs, load code from transaction URLs or run LLM-generated runtime parsers.

Shared parsers must not include real accounts, names, trades, addresses or reports.
Use synthetic fixtures. Core validation protects financial contracts, not the host
from malicious Python. Follow [publication](publishing.md) and
[development](development.md) procedures.
