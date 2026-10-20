"""Lossless parser-v2 facts and explicit host context, independent of storage.

Version-1 classes/validation remain unchanged. V2 facts are not permission to book
through a CLI/Web import; the first storage phase has no report projection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Protocol
from zoneinfo import ZoneInfo

from .source_protocol import (
    AccountKey, AdapterInfo, AssetKey, CryptoLeg, Detection, Money, RecordKey,
    _account, _asset, _money, _time, validate_info as validate_v1_info,
)

API_VERSION = 2
MAX_RAW_BYTES = 10 * 1024 * 1024
MAX_CANONICAL_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class RevisionContext:
    account: AccountKey
    kind: str
    source_id: str
    observation_id: str
    supersedes_revision: str


@dataclass(frozen=True)
class ScopeRevisionContext:
    kind: str
    scope_id: str
    supersedes_revision: str
    account: AccountKey | None = None
    record_kind: str | None = None
    observation_id: str = ""


@dataclass(frozen=True)
class ParseContext:
    evidence_at: datetime
    source_reference: str
    account_alias: str | None = None
    source_timezone: str | None = None
    format_selection: str | None = None
    revisions: tuple[RevisionContext, ...] = ()
    scope_revisions: tuple[ScopeRevisionContext, ...] = ()


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    parameters: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Evidence:
    raw_sha256: str
    context: ParseContext
    effective_at: datetime
    id_policy: str
    mappings: tuple[tuple[str, str], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    source_fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Account:
    key: AccountKey
    account_type: str
    label: str
    role: str  # investment, crypto or funding; funding is not a portfolio asset.
    masked_identifier: str | None = None


@dataclass(frozen=True)
class Membership:
    scope_id: str
    revision: str
    accounts: tuple[AccountKey, ...]
    status: str
    basis: str
    supersedes_revision: str | None = None


@dataclass(frozen=True)
class Coverage:
    kind: str
    account: AccountKey
    start: datetime
    end: datetime
    status: str
    basis: str
    scope_id: str
    revision: str
    supersedes_revision: str | None = None
    observation_id: str = ""


@dataclass(frozen=True)
class Snapshot:
    source_id: str
    revision: str
    as_of: datetime
    accounts: tuple[AccountKey, ...]
    supersedes_revision: str | None = None


@dataclass(frozen=True)
class Position:
    key: RecordKey
    observation_id: str
    as_of: datetime
    asset: AssetKey
    name: str
    instrument_type: str
    exchange: str
    quantity: Decimal
    market_value: Money
    unit_price: Money | None
    cost_native: Money | None
    cost_cad: Money | None
    unrealized: Money | None
    revision_reason: str | None = None
    source_fields: tuple[tuple[str, str], ...] = ()
    kind: str = "holdings"


@dataclass(frozen=True)
class Reference:
    account: AccountKey
    kind: str
    source_id: str


@dataclass(frozen=True)
class AssetAmount:
    asset: AssetKey
    quantity: Decimal
    method: str


@dataclass(frozen=True)
class Rate:
    amount: Decimal
    unit: str


@dataclass(frozen=True)
class Lifecycle:
    created_at: datetime
    completed_at: datetime | None
    sent_at: datetime | None
    source_type: str
    source_subtype: str
    source_status: str
    payin_status: str
    payout_status: str
    payin: AssetAmount
    payout: AssetAmount
    exchange_rate: Rate | None = None
    index_rate: Rate | None = None


@dataclass(frozen=True)
class Fee:
    account: AccountKey
    asset: AssetKey
    quantity: Decimal
    included_in_leg: bool
    included_in_cost: bool


@dataclass(frozen=True)
class CashFlow:
    key: RecordKey
    occurred_at: datetime
    type: str
    direction: str
    amount: Money
    status: str
    boundary: str
    transfer_reference: str | None = None
    counterpart: Reference | None = None
    cash_leg_of: Reference | None = None
    lifecycle: Lifecycle | None = None
    revision_reason: str | None = None
    source_fields: tuple[tuple[str, str], ...] = ()
    kind: str = "cash_flows"


@dataclass(frozen=True)
class CryptoTransaction:
    key: RecordKey
    occurred_at: datetime
    type: str
    status: str
    legs: tuple[CryptoLeg, ...]
    acquisition_cost: Money | None
    acquisition_cost_cad: Money | None
    fees: tuple[Fee, ...] | None
    lifecycle: Lifecycle | None = None
    transfer_reference: str | None = None
    counterpart: Reference | None = None
    revision_reason: str | None = None
    source_fields: tuple[tuple[str, str], ...] = ()
    kind: str = "crypto_transactions"


@dataclass(frozen=True)
class NormalizedBatch:
    adapter: AdapterInfo
    export_version: str
    evidence: Evidence
    accounts: tuple[Account, ...]
    membership: Membership
    snapshots: tuple[Snapshot, ...]
    coverage: tuple[Coverage, ...]
    records: tuple[Position | CashFlow | CryptoTransaction, ...]


class SourceAdapter(Protocol):
    info: AdapterInfo
    def detect(self, raw: bytes) -> Detection: ...
    def normalize(self, raw: bytes, *, export_version: str, context: ParseContext) -> NormalizedBatch: ...


def _text(value, *, empty=False):
    if not isinstance(value, str) or len(value) > 4096 or not empty and not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("Expected bounded source text")


def _tuple(value, maximum=50000):
    if not isinstance(value, tuple) or len(value) > maximum:
        raise ValueError("Expected bounded immutable tuple")


def _pairs(value):
    _tuple(value, 256)
    seen = set()
    for pair in value:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ValueError("Expected named source fields")
        _text(pair[0]); _text(pair[1], empty=True)
        if pair[0] in seen:
            raise ValueError("Duplicate source field")
        seen.add(pair[0])


def _revision(revision, parent):
    _text(revision)
    if parent is not None:
        _text(parent)
        if revision == parent:
            raise ValueError("Revision cannot supersede itself")


def validate_info(info):
    if not isinstance(info, AdapterInfo) or type(info.api_version) is not int or info.api_version != API_VERSION:
        raise ValueError("Unsupported parser-v2 API version")
    validate_v1_info(replace(info, api_version=1))


def validate_context(context):
    if not isinstance(context, ParseContext):
        raise ValueError("Parser-v2 requires explicit host context")
    _time(context.evidence_at); _text(context.source_reference)
    for item in (context.account_alias, context.source_timezone, context.format_selection):
        if item is not None:
            _text(item)
    if context.source_timezone is not None:
        try:
            ZoneInfo(context.source_timezone)
        except (KeyError, ValueError):
            raise ValueError("Unknown declared source timezone") from None
    _tuple(context.revisions)
    seen = set()
    for item in context.revisions:
        if not isinstance(item, RevisionContext) or item.kind not in {"holdings", "cash_flows", "crypto_transactions"}:
            raise ValueError("Invalid host revision context")
        if not isinstance(item.account, AccountKey):
            raise ValueError("Invalid context account")
        _text(item.account.provider); _text(item.account.account_id)
        _text(item.source_id); _text(item.supersedes_revision); _text(item.observation_id, empty=True)
        identity = (item.account, item.kind, item.source_id, item.observation_id)
        if identity in seen:
            raise ValueError("Duplicate host revision context")
        seen.add(identity)
    _tuple(context.scope_revisions)
    seen = set()
    for item in context.scope_revisions:
        if not isinstance(item, ScopeRevisionContext) or item.kind not in {"membership","snapshot","coverage"}:
            raise ValueError("Invalid host scope revision context")
        _text(item.scope_id); _text(item.supersedes_revision); _text(item.observation_id,empty=True)
        if item.kind == "coverage":
            if not isinstance(item.account,AccountKey) or item.record_kind not in {"holdings","cash_flows","crypto_transactions"}:
                raise ValueError("Coverage revision context needs an account and record kind")
            _text(item.account.provider); _text(item.account.account_id)
            if (item.record_kind == "holdings") != bool(item.observation_id):
                raise ValueError("Coverage revision observation differs")
        elif item.account is not None or item.record_kind is not None or item.observation_id:
            raise ValueError("Snapshot/membership context has no record selector")
        identity = (item.kind,item.scope_id,item.account,item.record_kind,item.observation_id)
        if identity in seen:
            raise ValueError("Duplicate host scope revision context")
        seen.add(identity)


def _reference(value):
    if value is None:
        return
    if not isinstance(value, Reference) or value.kind not in {"cash_flows", "crypto_transactions"} or not isinstance(value.account, AccountKey):
        raise ValueError("Invalid economic counterpart reference")
    _text(value.account.provider); _text(value.account.account_id); _text(value.source_id)


def _lifecycle(value, record):
    if value is None:
        return
    if not isinstance(value, Lifecycle):
        raise ValueError("Invalid source lifecycle")
    _time(value.created_at)
    for at in (value.completed_at, value.sent_at):
        if at is not None:
            _time(at)
            if at < value.created_at:
                raise ValueError("Source lifecycle precedes creation")
    if record.status == "completed" and (value.completed_at is None or value.completed_at != record.occurred_at):
        raise ValueError("Completed source event needs its completion time")
    for text in (value.source_type, value.source_status, value.payin_status, value.payout_status):
        _text(text)
    _text(value.source_subtype, empty=True)
    for amount in (value.payin, value.payout):
        if not isinstance(amount, AssetAmount):
            raise ValueError("Expected source asset amount")
        _asset(amount.asset, amount.quantity); _text(amount.method)
        if amount.quantity < 0:
            raise ValueError("Source pay-in/out amounts must be nonnegative")
    for rate in (value.exchange_rate, value.index_rate):
        if rate is not None:
            if not isinstance(rate, Rate) or not isinstance(rate.amount, Decimal) or not rate.amount.is_finite():
                raise ValueError("Invalid source rate")
            _text(rate.unit)


def _validate_batch(batch, raw, *, context=None):
    if not isinstance(batch, NormalizedBatch) or type(raw) is not bytes or not 0 < len(raw) <= MAX_RAW_BYTES:
        raise ValueError("Expected bounded parser-v2 batch and original bytes")
    validate_info(batch.adapter)
    if batch.export_version not in batch.adapter.export_versions:
        raise ValueError("Unsupported source export version")
    ev = batch.evidence
    if not isinstance(ev, Evidence) or ev.raw_sha256 != hashlib.sha256(raw).hexdigest():
        raise ValueError("Raw source evidence hash mismatch")
    validate_context(ev.context)
    if context is not None and ev.context != context:
        raise ValueError("Parser changed trusted host context")
    if ev.context.format_selection not in {None, batch.export_version}:
        raise ValueError("Host/source format selection differs")
    _time(ev.effective_at); _text(ev.id_policy); _pairs(ev.mappings); _pairs(ev.source_fields)
    _tuple(ev.diagnostics, 256)
    for item in ev.diagnostics:
        if not isinstance(item, Diagnostic) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,199}", item.code) or item.severity not in {"info", "warning", "error"}:
            raise ValueError("Invalid diagnostic code/severity")
        _pairs(item.parameters)
    for items in (batch.accounts, batch.snapshots, batch.coverage, batch.records):
        _tuple(items)
    accounts = {}
    for account in batch.accounts:
        if not isinstance(account, Account) or account.role not in {"investment", "crypto", "funding"}:
            raise ValueError("Invalid source account metadata")
        _account(account.key, batch.adapter.provider_id)
        _text(account.account_type); _text(account.label)
        if account.masked_identifier is not None:
            _text(account.masked_identifier)
        if account.key in accounts:
            raise ValueError("Duplicate source account")
        accounts[account.key] = account
    membership = batch.membership
    if not isinstance(membership, Membership) or membership.status not in {"complete", "partial", "unknown"}:
        raise ValueError("Invalid account membership declaration")
    _text(membership.scope_id); _text(membership.basis); _revision(membership.revision, membership.supersedes_revision)
    _tuple(membership.accounts)
    if not accounts or len(set(membership.accounts)) != len(membership.accounts) or set(membership.accounts) != set(accounts):
        raise ValueError("Membership must match declared accounts exactly")
    snapshots = {}
    for snapshot in batch.snapshots:
        if not isinstance(snapshot, Snapshot):
            raise ValueError("Invalid snapshot header")
        _text(snapshot.source_id); _revision(snapshot.revision, snapshot.supersedes_revision); _time(snapshot.as_of)
        _tuple(snapshot.accounts)
        if not snapshot.accounts or len(set(snapshot.accounts)) != len(snapshot.accounts) or not set(snapshot.accounts) <= accounts.keys() or snapshot.source_id in snapshots:
            raise ValueError("Invalid/duplicate snapshot account scope")
        snapshots[snapshot.source_id] = snapshot
    scopes = set()
    for scope in batch.coverage:
        if not isinstance(scope, Coverage) or scope.kind not in batch.adapter.kinds or scope.account not in accounts or scope.status not in {"complete", "partial", "unknown"}:
            raise ValueError("Invalid record coverage")
        _time(scope.start); _time(scope.end); _text(scope.basis); _text(scope.scope_id)
        _revision(scope.revision, scope.supersedes_revision)
        if scope.end < scope.start or (scope.kind == "holdings") != bool(scope.observation_id):
            raise ValueError("Invalid coverage time/observation")
        if scope.kind == "holdings" and (scope.observation_id not in snapshots or scope.account not in snapshots[scope.observation_id].accounts):
            raise ValueError("Coverage refers to an unknown snapshot/account")
        token = (scope.kind, scope.account, scope.scope_id, scope.observation_id)
        if token in scopes:
            raise ValueError("Duplicate coverage declaration")
        scopes.add(token)
    seen = set()
    for record in batch.records:
        expected = {Position:"holdings", CashFlow:"cash_flows", CryptoTransaction:"crypto_transactions"}.get(type(record))
        if expected is None or record.kind != expected or record.kind not in batch.adapter.kinds or not isinstance(record.key, RecordKey) or record.key.account not in accounts:
            raise ValueError("Invalid canonical record schema/account")
        key = record.key
        _text(key.source_id); _revision(key.revision, key.supersedes_revision)
        if key.change not in {"original", "correction", "void"} or (key.change == "original") != (key.supersedes_revision is None):
            raise ValueError("Invalid record revision/void")
        if key.change != "original":
            _text(record.revision_reason)
        elif record.revision_reason is not None:
            raise ValueError("Original records cannot carry a revision reason")
        observation = record.observation_id if isinstance(record, Position) else ""
        token = (record.kind, key.account, observation, key.source_id)
        if token in seen:
            raise ValueError("Duplicate source identity within batch")
        seen.add(token)
        at = record.as_of if isinstance(record, Position) else record.occurred_at
        _time(at); _pairs(record.source_fields)
        if not any(s.kind == record.kind and s.account == key.account and s.observation_id == observation and s.start <= at <= s.end for s in batch.coverage):
            raise ValueError("Every record needs matching explicit coverage")
        if isinstance(record, Position):
            snapshot = snapshots.get(observation)
            if snapshot is None or key.account not in snapshot.accounts or snapshot.as_of != at or snapshot.revision != key.revision:
                raise ValueError("Position differs from snapshot header")
            _asset(record.asset, record.quantity); _text(record.name); _text(record.instrument_type); _text(record.exchange, empty=True)
            for money in (record.market_value, record.unit_price, record.cost_native, record.unrealized):
                _money(money, optional=money is not record.market_value)
                if money is not None and money.currency != record.asset.currency:
                    raise ValueError("Position source-native currency differs")
            _money(record.cost_cad, optional=True)
            if record.cost_cad is not None and record.cost_cad.currency != "CAD":
                raise ValueError("Source CAD book cost must remain CAD")
            if key.change == "void":
                raise ValueError("Snapshot replacement, not a fabricated zero position, removes snapshot membership")
        else:
            if record.status not in {"completed", "pending", "cancelled"} or key.change == "void" and record.status != "cancelled":
                raise ValueError("Invalid event status/void")
            _lifecycle(record.lifecycle, record); _reference(record.counterpart)
            if record.transfer_reference is not None:
                _text(record.transfer_reference)
            if isinstance(record, CashFlow):
                if record.type not in {"deposit", "withdrawal", "transfer", "income", "fee"} or record.direction not in {"in", "out"} or record.boundary not in {"external", "internal", "unclassified"}:
                    raise ValueError("Invalid explicit cash direction/boundary")
                _money(record.amount)
                if record.amount.amount <= 0 or record.type in {"deposit", "income"} and record.direction != "in" or record.type in {"withdrawal", "fee"} and record.direction != "out":
                    raise ValueError("Cash amount/type/direction differs")
                if record.type == "transfer" and record.transfer_reference is None:
                    raise ValueError("Transfer requires a source reference")
                _reference(record.cash_leg_of)
                if record.cash_leg_of is not None and (record.cash_leg_of.kind != "crypto_transactions" or record.boundary != "internal"):
                    raise ValueError("Linked purchase cash is an internal transaction leg")
            else:
                if record.type not in {"purchase", "sale", "transfer", "fee", "swap"}:
                    raise ValueError("Unsupported canonical crypto event type")
                _tuple(record.legs, 256)
                if not record.legs or not any(leg.asset.kind == "crypto" for leg in record.legs if isinstance(leg, CryptoLeg)):
                    raise ValueError("Crypto event requires a crypto leg")
                for leg in record.legs:
                    if not isinstance(leg, CryptoLeg) or leg.account not in accounts:
                        raise ValueError("Unknown crypto leg account")
                    _asset(leg.asset, leg.quantity)
                    if leg.quantity == 0:
                        raise ValueError("Crypto legs must be nonzero")
                _money(record.acquisition_cost, optional=True); _money(record.acquisition_cost_cad, optional=True)
                if record.acquisition_cost_cad is not None and record.acquisition_cost_cad.currency != "CAD":
                    raise ValueError("Source CAD acquisition cost must remain CAD")
                if record.type in {"transfer", "swap"} and record.transfer_reference is None:
                    raise ValueError("Crypto transfer/swap requires a source reference")
                if record.fees is not None:
                    _tuple(record.fees, 256)
                    for fee in record.fees:
                        if not isinstance(fee, Fee) or fee.account not in accounts or type(fee.included_in_leg) is not bool or type(fee.included_in_cost) is not bool:
                            raise ValueError("Invalid explicit fee allocation")
                        _asset(fee.asset, fee.quantity)
                        if fee.quantity < 0:
                            raise ValueError("Fee quantity must be nonnegative")
    record_parents = {(r.key.account,r.kind,r.key.source_id,r.observation_id if isinstance(r,Position) else ""):r.key.supersedes_revision for r in batch.records}
    for item in ev.context.revisions:
        token = (item.account,item.kind,item.source_id,item.observation_id)
        if token not in record_parents or record_parents[token] != item.supersedes_revision:
            raise ValueError("Parser omitted or changed a host-selected record parent")
    scope_parents = {("membership",membership.scope_id,None,None,""):membership.supersedes_revision}
    scope_parents.update({("snapshot",s.source_id,None,None,""):s.supersedes_revision for s in batch.snapshots})
    scope_parents.update({("coverage",s.scope_id,s.account,s.kind,s.observation_id):s.supersedes_revision for s in batch.coverage})
    for item in ev.context.scope_revisions:
        token = (item.kind,item.scope_id,item.account,item.record_kind,item.observation_id)
        if token not in scope_parents or scope_parents[token] != item.supersedes_revision:
            raise ValueError("Parser omitted or changed a host-selected scope parent")
    if len(canonical_json(batch).encode()) > MAX_CANONICAL_BYTES:
        raise ValueError("Canonical batch exceeds evidence limit")


def validate_batch(batch, raw, *, context=None):
    try:
        _validate_batch(batch, raw, context=context)
    except (TypeError, AttributeError, KeyError, OverflowError, InvalidOperation):
        raise ValueError("Invalid parser-v2 field type or value") from None


def canonical_json(value):
    def encode(item):
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError("Nonfinite source value")
            return str(item)
        if isinstance(item, datetime):
            _time(item)
            return item.isoformat()
        raise TypeError("Unsupported canonical value")
    return json.dumps(asdict(value), default=encode, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def decode_batch(canonical: bytes, raw: bytes) -> NormalizedBatch:
    """Decode only core-owned v2 schemas; never import or execute a saved parser.

    This is for canonical archives/replay, not permissive JSON normalization.
    Unknown fields, duplicate keys, floats and noncanonical encodings fail closed.
    """
    import types
    from dataclasses import fields, is_dataclass
    from typing import Literal, get_args, get_origin, get_type_hints
    if type(canonical) is not bytes or not 0 < len(canonical) <= MAX_CANONICAL_BYTES:
        raise ValueError("Invalid canonical evidence size")
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("Duplicate canonical JSON key")
            result[name] = value
        return result
    def decode(expected, value, depth=0):
        if depth > 32:
            raise ValueError("Canonical nesting limit")
        origin, args = get_origin(expected), get_args(expected)
        if origin is types.UnionType:
            for choice in args:
                try:
                    return decode(choice, value, depth + 1)
                except (ValueError, TypeError, InvalidOperation):
                    pass
            raise ValueError("Canonical union does not match a schema")
        if expected is type(None):
            if value is not None:
                raise ValueError("Expected null")
            return None
        if origin is Literal:
            if not any(type(value) is type(choice) and value == choice for choice in args):
                raise ValueError("Unknown canonical enum")
            return value
        if origin is tuple:
            if not isinstance(value, list) or len(value) > 50000:
                raise ValueError("Expected bounded canonical array")
            if len(args) == 2 and args[1] is Ellipsis:
                return tuple(decode(args[0], item, depth + 1) for item in value)
            if len(value) != len(args):
                raise ValueError("Canonical tuple length differs")
            return tuple(decode(kind, item, depth + 1) for kind, item in zip(args, value))
        if expected in {str, int, bool}:
            if type(value) is not expected:
                raise ValueError("Canonical primitive type differs")
            return value
        if expected is Decimal:
            if type(value) is not str:
                raise ValueError("Canonical financial numbers must be strings")
            result = Decimal(value)
            if not result.is_finite():
                raise ValueError("Nonfinite canonical value")
            return result
        if expected is datetime:
            if type(value) is not str:
                raise ValueError("Canonical times must be strings")
            result = datetime.fromisoformat(value); _time(result)
            return result
        if is_dataclass(expected) and expected.__module__ in {__name__, "wealth_ledger.source_protocol"}:
            if not isinstance(value, dict) or set(value) != {field.name for field in fields(expected)}:
                raise ValueError("Canonical object schema differs")
            hints = get_type_hints(expected)
            return expected(**{name:decode(hints[name], item, depth + 1) for name,item in value.items()})
        raise ValueError("Unknown canonical schema")
    try:
        value = json.loads(canonical, object_pairs_hook=pairs,
                           parse_constant=lambda value:(_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        batch = decode(NormalizedBatch, value)
        validate_batch(batch, raw)
        if canonical_json(batch).encode() != canonical:
            raise ValueError("Evidence is not the canonical encoding")
        return batch
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, InvalidOperation):
        raise ValueError("Invalid canonical-v2 archive") from None
