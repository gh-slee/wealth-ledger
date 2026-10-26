# Canonical domain contract v1

`wealth_ledger.domain` provides an opt-in developer vocabulary, strict codec and
one-way parser-v2 archive bridge. Domain version **1** is separate from parser API
versions 1/2 and from the product V2 roadmap. Importing the domain package registers
nothing. No CLI, Web route, parser registry, ingestion, SQLite binding or report
path selects this contract. A valid shape is never permission to book or value it.

The four modules use only Python's standard library:

| Module | Development interface |
|---|---|
| `canonical_v1` | Frozen, slotted dataclasses, tuple collections and closed Literal alternatives |
| `validation_v1` | `validate_domain_v1(batch)`, `encode_domain_v1(batch) -> bytes`, `decode_domain_v1(bytes) -> DomainBatchV1`, safe `DomainValidationError` |
| `legacy_bridge_v1` | `bridge_parser_v2(raw, canonical, BridgeContextV1) -> BridgeResultV1`, exact-evidence `recover_legacy_v1(result, reference)` |

## Explicit identity and source facts

Callers supply non-nil, lowercase hyphenated UUIDs and explicit tenant/portfolio
scope. `ScopedIdV1` distinguishes account, connection, instrument, issuer, fact and
snapshot kinds even when their UUID text happens to match. These pure object checks
do not establish authenticated ownership, persisted tenancy or row-level security.

An alias is unique by scope, connection, provider, source account key and mapping
revision. Several aliases can resolve to one financial account; one connection can
supply several accounts. The same provider/key text under another connection is a
different namespace. Every fact source selector retains its connection explicitly.
Identical duplicate declarations fail; conflicting alias targets fail. References
must resolve to the correct typed declaration within the same graph. Existing
SQLite mapping collision restrictions are unchanged.

A security instrument has its own listing UUID, four-character uppercase
alphanumeric MIC, ticker and currency. MIC syntax is checked without consulting a
registry. Issuer and identifier hints do not merge listings. Cash CAD, BTC on
bitcoin, LBTC on liquid, and a security with ticker BTC stay distinct. A crypto
instrument explicitly supplies symbol, network and settlement identity. Missing or
ambiguous mappings block conversion; no provider lookup or provisional ID occurs.

Snapshots retain separate position items, source observation, revision and declared
accounts. Coverage has explicit connection/source-account-alias/account/kind/scope/revision/observation,
time selector, instrument scope, status and basis. Snapshot coverage references
retain that full composite selector; two source aliases may legitimately use the
same source scope text even when explicitly mapped to one financial account.
Coverage validates each source alias against its exact connection/provider/account
mapping. Snapshot items use only the snapshot's explicitly selected coverage,
including source alias; an unselected global scope cannot certify them. Duplicate
snapshot source identities (connection, source ID, revision) fail independently of
caller UUIDs. Complete-empty, partial-empty and unknown-empty remain distinct.
A position outside declared snapshot or coverage scope fails. Activity coverage
selects the source record account; signed legs may name other explicitly mapped
accounts, without inventing additional source coverage.

Activities have separate normalized kind, source kind/status, semantic status,
explicit signed legs, nullable native/CAD acquisition costs and nullable fees.
Known source kinds map to the closed BUY/SELL/TRANSFER/FEE/INCOME/FUNDING vocabulary;
unknown kinds remain UNSUPPORTED. Corporate actions remain explicitly unsupported.
Unknown source statuses require unsupported status/reason; pending and cancelled
sources cannot become completed. Supported shape means only representable shape.

Every activity leg has an explicit ACQUISITION/PAYMENT/TRANSFER/FEE/OTHER role. BUY
requires at least one positive crypto/security ACQUISITION leg; zero, signed zero
and negative acquisitions fail. PAYMENT and FEE movements can be negative. A BTC
payment for a security acquisition is allowed. A recognized purchase cannot evade
these rules by being labeled UNSUPPORTED. `FeeV1.quantity` is a nonnegative
magnitude, distinct from a signed FEE leg; inclusion flags remain explicit. An
unsupported instrument referenced only by a fee still requires the activity's
unsupported_instrument classification. Unknown
fees (`None`) differ from no fees (`()`). Unknown costs differ from `0.00`.

Legacy cash-flow activities, and native FUNDING, retain `SourceCashFlowV1`: positive
currency-qualified amount, direction, boundary and source economic references.
They carry no reconstructed signed legs. Funding, purchase payments and observed
cash remain distinct facts; no resulting balance, contribution, wealth total,
current holding, cost arithmetic or eligibility decision is emitted.

`ExternalSourceRefV1` carries scoped, connection-qualified historical/economic
selectors. A correction r2 -> r1 is valid when r1 is absent from this batch;
self-parent, wrong-kind/account/scope selectors fail. In-batch entity references
resolve locally. Historical existence, accepted heads, authority and source dedupe
need future persistence. The bridge does not fabricate user revision reasons.

## Exact decimal profile and time

The fixed profile is `decimal-38s-24f-38i-v1`. Financial values are `DecimalTokenV1`
plain ASCII strings matching `-?(0|[1-9][0-9]*)([.][0-9]+)?`; finance JSON numbers,
floats, bools, exponents, nonfinite values and surrounding whitespace fail. Money
has an uppercase three-letter currency; quantities carry an explicit instrument
reference on the enclosing position, leg or fee. No unqualified numeric amount is
accepted. Accepted sign and display scale are retained exactly.

Admission uses lexical coefficient analysis, with at most 38 numeric significant
digits, 24 effective fractional digits and 38 integer digits. Insignificant trailing
zeros do not consume significant precision; fractional trailing zeros do not
consume effective fractional precision. Zero has one significant digit, zero
effective fraction/integer digits, and retains its lexical sign/scale. No Decimal
rounding, quantization or ambient context is used.

- `12345678901234.123456789012345678901234` is accepted; another nonzero integer
  digit exceeds significant precision.
- `0.000000000000000000000001` is accepted; a nonzero 25th fractional place fails.
- `10000000000000000000000000000000000000` is accepted; a further integer zero
  exceeds magnitude.
- BTC/LBTC quantities and fee magnitudes must be integral satoshis. `0.0000000100`
  is accepted unchanged; either sign of `0.000000001` fails. A BTC ETF ticker does
  not make its security quantity crypto.

Native `InstantV1` retains exact Gregorian ISO seconds, zero to six fractional
digits, explicit `Z`/offset and optional zone provenance. Naive times, leap seconds,
unknown `-00:00` offsets and greater precision reject. `fractional_digits` must
match the token. Equal instants with different offsets retain different tokens.
`DateOnlyV1` has a real date and explicit known/unknown zone, with no invented
midnight, offset or UTC normalization. Date-only coverage requires a matching point;
it is not ordered against overlapping instants. Intervals have explicit inclusion
flags and comparable aware endpoints; no general temporal engine is supplied.

Zone labels are syntactically bounded to 255 ASCII characters (`UTC` or nonempty
slash-separated identifier segments, excluding `.`/`..`). They are explicitly
registry-unverified; no IANA lookup or DST arithmetic occurs in new domain time
validation. `LegacyDateTimeV1` retains exact old aware `datetime.isoformat()` spelling,
`legacy_unspecified` source precision and a typed immutable archive/field reference.
Exact fromisoformat/isoformat equality prevents silent fractional truncation.
Structural archive references alone do not authenticate source evidence.

## Closed codec, limits and diagnostics

Encoding is UTF-8 with sorted object keys, no insignificant whitespace,
`ensure_ascii=False`, and tuple/array order preserved. Decoding rejects unknown or
missing fields (including source_account_key in coverage), duplicate keys, unexpected constructors/tags/types, and byte forms
that do not re-encode identically. Only a fixed core-owned dataclass whitelist is
constructed. No plugin object, module loader or arbitrary extension dictionary is
part of the financial schema.

Limits are 4 MiB canonical bytes, nesting depth 32, 50,000 entries per collection,
4096 characters per text field and 256 characters per decimal token. Admission
budgets precede structural/reference checks, then numeric/time and semantic checks
run in fixed schema/record order. Encoding checks cumulative exact wire size before
building a serialization tree, and checks emitted chunks too. It cannot expand an
unvalidated exponent. Resource limits are acceptance bounds, not a guarantee every
maximum-size legacy archive fits the larger new representation.

Failures expose a stable `domain_*` code and schema-owned field path/optional bounded
ordinal, never a source token, arbitrary key, source account, raw row, path or plugin
exception. Version/profile errors have separate codes. An unsupported fact is
explicit data, never an implicit financial success warning. Existing parser errors
and all legacy validation behavior remain unchanged.

## One-way saved parser-v2 bridge

`BridgeContextV1` explicitly supplies scope, source connection, declarations,
account aliases, asset/listing mappings, caller-allocated fact/snapshot UUIDs,
leg-role assignments by exact record selector and ordinal, mapping revision and
evidence. Optional imported/accepted times are populated only when supplied;
legacy evidence/observation times are not reinterpreted as these times. Security
source ticker/MIC/currency and crypto source symbol/network cannot silently map to
a different listing. Funding roles cannot become investment roles.

The bridge calls unchanged `source_v2.decode_batch(canonical, raw)` on exact saved
bytes. It does not call a parser, discover plugins or accept parser-v1 archives.
`BridgeResultV1` retains original canonical bytes, available raw/canonical digests,
and the exact immutable decoded original batch. A successful result contains a
complete candidate and its canonical bytes. Otherwise candidate/bytes are both
null with safe blockers; invalid old bytes also have `original_batch=None`.
Oversize input is rejected before hashing it; its unavailable digest is null.
Every result has constructor-fixed `ingestible=False`, even when conversion succeeds.
Partial source coverage is preserved, rather than confused with partial conversion.
When explicit aliases map to one financial account, snapshot header account UUIDs
are unique in source order, while all source-qualified coverage and individual
position facts remain separate. Their quantities are never combined.

The separate result envelope retains the entire exact archive, including membership,
masked source metadata, diagnostics, source fields, lifecycle pay-in/out methods,
exchange/index rates, context choices and economic links. Typed legacy references
retrieve complete immutable records or fields with `recover_legacy_v1`; a digest
alone is insufficient retention. The financial wire contains typed references,
not source dictionaries. Retention storage, deletion and authenticity policies are
not implemented here. Original raw bytes remain owned by the caller.

Legacy Decimal conversion inspects finite coefficient/exponent and old token size
before bounded plain expansion. Unrepresentable precision blocks the whole new
candidate. Zero exponents outside [-24, 38] block. The unchanged legacy route still
accepts its existing 70-integer/18-fraction value. Old spelling/exponent is retained
in the exact archive; a successful plain new token need not have the old spelling.

Operations introduce no application filesystem, database, network, subprocess,
clock, random UUID, booking or provider calls. Two inherited boundaries remain:
importing the existing parent `wealth_ledger` package initializes existing core
Decimal precision, and old strict decoding of an optional `source_timezone` may
load read-only interpreter timezone reference data through `ZoneInfo`. These old
behaviors are unchanged. After package initialization, new operations preserve
caller Decimal context; the new domain validator performs no timezone lookup.

## Executable evidence and deferred integration

[Domain tests](../tests/test_domain_v1.py) use literal financial/time/wire oracles,
scoped alias graphs, unsupported states, actual 4 MiB/50,000/depth boundaries,
context precision 6/100 and denied application I/O.
[Bridge tests](../tests/test_domain_bridge_v1.py) embed fabricated Wealthsimple/Bull
raw and exact canonical archives with pinned SHA-256, fixed source IDs, an
independently enumerated old dataclass inventory, exact field recovery and protected
legacy accepted/rejected cases. Fixtures need no external files or account data.
These are development tests; their existence is not deployment or independent-QA
acceptance evidence.

No storage migration, parser API 3, current routing, PostgreSQL toolkit, tenant auth,
quote/FX/valuation, accepted acquisition sums, historical reconciliation, split
arithmetic, new provider, UI, dependency or runtime AI is added. Rollback means
removing or declining to adopt these opt-in modules; no stored fact or legacy byte
requires a financial restore. Independent implementation review, publication,
merge and any later deployment remain separate gates.

## Optional persistence consumer

The [PostgreSQL foundation](postgres-foundation.md) explicitly validates and stores
complete domain-v1 candidates with typed SQL precision/scoped references plus exact
canonical bytes. It does not make them ingestible, choose financial authority or
change existing parser/Web routes. Source revisions can retain one fact UUID, and
declaration versions preserve each candidate's original meaning. The domain
contract, closed codec and pure bridge remain storage-independent and unchanged.
