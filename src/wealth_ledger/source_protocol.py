"""Version 1 parser contracts; no registration, external loading or ledger writes.

A normalized batch is evidence, not permission to book financial effects. Existing
Wealthsimple/Bull importers retain their current behavior until SRC-004 migration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Literal, Protocol, runtime_checkable

API_VERSION = 1
KINDS = frozenset({"holdings", "cash_flows", "crypto_transactions"})
STATUSES = frozenset({"completed", "pending", "cancelled"})


@dataclass(frozen=True)
class AccountKey:
    provider: str
    account_id: str


@dataclass(frozen=True)
class AssetKey:
    """Market distinguishes securities; network distinguishes BTC and Liquid BTC."""
    kind: Literal["security", "cash", "crypto"]
    symbol: str
    currency: str
    market: str | None = None
    network: str | None = None
    identifier: str | None = None


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class RecordKey:
    """Provider/account/source ID, independent of file path and display names."""
    account: AccountKey
    source_id: str
    revision: str
    supersedes_revision: str | None = None
    change: Literal["original", "correction", "void"] = "original"


@dataclass(frozen=True)
class Holding:
    key: RecordKey
    as_of: datetime
    asset: AssetKey
    quantity: Decimal
    market_value: Money
    cost: Money | None
    kind: Literal["holdings"] = "holdings"


@dataclass(frozen=True)
class CashFlow:
    key: RecordKey
    occurred_at: datetime
    type: Literal["deposit", "withdrawal", "transfer", "income", "fee"]
    amount: Money
    status: Literal["completed", "pending", "cancelled"]
    boundary: Literal["external", "internal", "unclassified"]
    transfer_reference: str | None = None
    counterpart_account: AccountKey | None = None
    counterpart_source_id: str | None = None
    kind: Literal["cash_flows"] = "cash_flows"


@dataclass(frozen=True)
class CryptoLeg:
    """Signed source-reported change, not a calculated contribution."""
    account: AccountKey
    asset: AssetKey
    quantity: Decimal


@dataclass(frozen=True)
class CryptoTransaction:
    key: RecordKey
    occurred_at: datetime
    type: Literal["purchase", "sale", "transfer", "fee", "swap"]
    status: Literal["completed", "pending", "cancelled"]
    legs: tuple[CryptoLeg, ...]
    # None means unknown, not free. Fees must not be silently added to cost twice.
    fees: tuple[Money, ...] | None = None
    acquisition_cost: Money | None = None
    transfer_reference: str | None = None
    counterpart_source_id: str | None = None
    counterpart_account: AccountKey | None = None
    kind: Literal["crypto_transactions"] = "crypto_transactions"


CanonicalRecord = Holding | CashFlow | CryptoTransaction


@dataclass(frozen=True)
class Coverage:
    kind: str
    account: AccountKey
    start: datetime
    end: datetime
    status: Literal["complete", "partial", "unknown"]
    basis: str
    # Stable source scope; adding accounts requires a new declaration/revision.
    scope_id: str
    scope_revision: str


@dataclass(frozen=True)
class SourceEvidence:
    raw_sha256: str
    effective_at: datetime
    fetched_at: datetime
    source_reference: str
    mappings: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...]
    id_policy: str


@dataclass(frozen=True)
class AdapterInfo:
    provider_id: str
    adapter_id: str
    adapter_version: str
    export_versions: tuple[str, ...]
    kinds: tuple[str, ...]
    api_version: int = API_VERSION


@dataclass(frozen=True)
class Detection:
    matched: bool
    export_version: str | None
    reason: str


@dataclass(frozen=True)
class NormalizedBatch:
    adapter: AdapterInfo
    export_version: str
    evidence: SourceEvidence
    coverage: tuple[Coverage, ...]
    records: tuple[CanonicalRecord, ...]


@runtime_checkable
class SourceAdapter(Protocol):
    """Trusted pure parsers receive bytes, never workspace/database handles.

    Implementations must not use network, credentials, subprocesses or file writes.
    Python typing/validation does not sandbox untrusted code.
    """
    info: AdapterInfo

    def detect(self, raw: bytes) -> Detection: ...

    def normalize(self, raw: bytes, *, export_version: str) -> NormalizedBatch: ...


def _tuple(value, label):
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be an immutable tuple")


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a nonempty string without control characters")


def _time(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Source times must include an explicit timezone")


def _decimal(value):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Financial values require finite Decimal, never float")


def _currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("Money/valuation currency must be an uppercase three-letter code")


def _account(value, provider):
    if not isinstance(value, AccountKey) or value.provider != provider:
        raise ValueError("Record account must belong to the declared provider namespace")
    _text(value.account_id, "Account ID")


def _money(value, *, optional=False):
    if value is None and optional:
        return
    if not isinstance(value, Money):
        raise ValueError("Expected currency-qualified Money")
    _decimal(value.amount)
    _currency(value.currency)


def _asset(value, quantity):
    if not isinstance(value, AssetKey) or value.kind not in {"security", "cash", "crypto"}:
        raise ValueError("Invalid canonical asset kind")
    _text(value.symbol, "Asset symbol")
    for label in ("market", "network", "identifier"):
        if getattr(value, label) is not None:
            _text(getattr(value, label), "Asset " + label)
    _currency(value.currency)
    _decimal(quantity)
    if value.kind == "security" and (not value.market or value.network is not None):
        raise ValueError("Securities require market identity and no network")
    if value.kind == "crypto" and (not value.network or value.market is not None):
        raise ValueError("Crypto requires network identity and no securities market")
    if value.kind == "cash" and (value.symbol != value.currency or value.market or value.network):
        raise ValueError("Cash identity must match currency without market/network")
    digits = quantity.as_tuple()
    if value.symbol in {"BTC", "LBTC"} and digits.exponent < -8 and any(digits.digits[digits.exponent + 8:]):
        raise ValueError("BTC/LBTC quantities must be whole satoshis")


def validate_info(info):
    if not isinstance(info, AdapterInfo) or type(info.api_version) is not int or info.api_version != API_VERSION:
        raise ValueError("Unsupported source parser API version")
    for value in (info.provider_id, info.adapter_id):
        if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]*", value):
            raise ValueError("Provider/adapter IDs require stable lowercase namespaces")
    _text(info.adapter_version, "Adapter version")
    _tuple(info.kinds, "Adapter kinds"); _tuple(info.export_versions, "Export versions")
    if not info.kinds or len(set(info.kinds)) != len(info.kinds) or not set(info.kinds) <= KINDS:
        raise ValueError("Invalid or duplicate adapter capabilities")
    if not info.export_versions or len(set(info.export_versions)) != len(info.export_versions):
        raise ValueError("Adapter must declare unique supported export versions")
    for version in info.export_versions:
        _text(version, "Export version")


def resolve_detection(candidates: tuple[tuple[AdapterInfo, Detection], ...]):
    """Resolve already evaluated trusted results; this does not discover/load code."""
    seen, matches = set(), []
    for info, result in candidates:
        validate_info(info)
        if info.adapter_id in seen:
            raise ValueError("Duplicate adapter ID")
        seen.add(info.adapter_id)
        if not isinstance(result, Detection) or type(result.matched) is not bool:
            raise ValueError("Invalid detector result")
        _text(result.reason, "Detection reason")
        if result.matched:
            if result.export_version not in info.export_versions:
                raise ValueError("Detector selected an unsupported export version")
            matches.append((info, result))
        elif result.export_version is not None:
            raise ValueError("Nonmatches cannot select an export version")
    if len(matches) != 1:
        raise ValueError("Ambiguous source detection" if matches else "No supported source detected")
    return matches[0]


def validate_batch(batch: NormalizedBatch, raw: bytes) -> None:
    """Reject unsafe normalization before future ledger-specific submission checks.

    This validates structural semantics, not portfolio membership, existing revision
    lineage, balanced transfers, cost allocation or cross-source economic duplicates.
    Those require transactional state during SRC-004 integration.
    """
    if not isinstance(batch, NormalizedBatch):
        raise ValueError("Expected NormalizedBatch")
    validate_info(batch.adapter)
    info, evidence = batch.adapter, batch.evidence
    if batch.export_version not in info.export_versions:
        raise ValueError("Unsupported export format version")
    if not isinstance(evidence, SourceEvidence) or evidence.raw_sha256 != hashlib.sha256(raw).hexdigest():
        raise ValueError("Raw source evidence hash mismatch")
    _time(evidence.effective_at); _time(evidence.fetched_at)
    _text(evidence.source_reference, "Source reference"); _text(evidence.id_policy, "Source ID policy")
    _tuple(evidence.mappings, "Field mappings"); _tuple(evidence.warnings, "Warnings")
    _tuple(batch.coverage, "Coverage declarations"); _tuple(batch.records, "Canonical records")
    for mapping in evidence.mappings:
        if not isinstance(mapping, tuple) or len(mapping) != 2:
            raise ValueError("Field mappings require original/canonical pairs")
        original, canonical = mapping
        _text(original, "Original field"); _text(canonical, "Canonical field")
    for warning in evidence.warnings:
        _text(warning, "Warning")
    coverage_keys = set()
    for scope in batch.coverage:
        if not isinstance(scope, Coverage):
            raise ValueError("Expected Coverage declaration")
        if scope.kind not in info.kinds or scope.status not in {"complete", "partial", "unknown"}:
            raise ValueError("Invalid coverage kind/status")
        _account(scope.account, info.provider_id)
        _time(scope.start); _time(scope.end)
        if scope.end < scope.start:
            raise ValueError("Coverage end precedes start")
        for value in (scope.basis, scope.scope_id, scope.scope_revision):
            _text(value, "Coverage declaration")
        token = (scope.kind, scope.account, scope.scope_id, scope.scope_revision)
        if token in coverage_keys:
            raise ValueError("Duplicate scope declaration")
        coverage_keys.add(token)
    seen = set()
    for record in batch.records:
        if not isinstance(record, (Holding, CashFlow, CryptoTransaction)) or record.kind not in info.kinds:
            raise ValueError("Unsupported canonical record kind")
        expected_kind = {Holding: "holdings", CashFlow: "cash_flows", CryptoTransaction: "crypto_transactions"}[type(record)]
        if record.kind != expected_kind:
            raise ValueError("Record kind does not match its schema")
        key = record.key
        if not isinstance(key, RecordKey):
            raise ValueError("Expected RecordKey")
        _account(key.account, info.provider_id)
        _text(key.source_id, "Stable source ID"); _text(key.revision, "Source revision")
        if key.change not in {"original", "correction", "void"}:
            raise ValueError("Unknown source change")
        if (key.change == "original") != (key.supersedes_revision is None):
            raise ValueError("Corrections/voids require the superseded revision")
        if key.supersedes_revision is not None:
            _text(key.supersedes_revision, "Superseded revision")
            if key.supersedes_revision == key.revision:
                raise ValueError("A revision cannot supersede itself")
        token = (key.account, record.kind, key.source_id)
        if token in seen:
            raise ValueError("Duplicate source record in one batch; resolve revisions explicitly")
        seen.add(token)
        at = record.as_of if isinstance(record, Holding) else record.occurred_at
        _time(at)
        if not any(s.account == key.account and s.kind == record.kind and s.start <= at <= s.end for s in batch.coverage):
            raise ValueError("Every record needs an explicit covering scope declaration")
        if isinstance(record, Holding):
            _asset(record.asset, record.quantity)
            _money(record.market_value); _money(record.cost, optional=True)
            if record.market_value.currency != record.asset.currency:
                raise ValueError("Holding valuation must use its declared currency")
        else:
            if record.status not in STATUSES or key.change == "void" and record.status != "cancelled":
                raise ValueError("Invalid status; void events must be cancelled")
            if isinstance(record, CashFlow):
                if record.type not in {"deposit", "withdrawal", "transfer", "income", "fee"} or record.boundary not in {"external", "internal", "unclassified"}:
                    raise ValueError("Unsupported cash-flow type/boundary")
                _money(record.amount)
                if record.amount.amount <= 0:
                    raise ValueError("Cash-flow amount must be positive; type defines direction")
                if record.type == "transfer" and not record.transfer_reference:
                    raise ValueError("Transfer requires a source reference; matching remains unverified")
            else:
                if record.type not in {"purchase", "sale", "transfer", "fee", "swap"} or not record.legs:
                    raise ValueError("Unsupported crypto type or missing quantity legs")
                _tuple(record.legs, "Crypto legs")
                for leg in record.legs:
                    if not isinstance(leg, CryptoLeg):
                        raise ValueError("Expected CryptoLeg")
                    _account(leg.account, info.provider_id); _asset(leg.asset, leg.quantity)
                    if leg.quantity == 0:
                        raise ValueError("Crypto legs must have nonzero quantities")
                if not any(leg.asset.kind == "crypto" for leg in record.legs):
                    raise ValueError("Crypto transactions require a crypto leg")
                if record.type in {"transfer", "swap"} and not record.transfer_reference:
                    raise ValueError("Transfers/swaps require a source reference")
                _money(record.acquisition_cost, optional=True)
                if record.fees is not None:
                    _tuple(record.fees, "Crypto fees")
                for fee in record.fees or ():
                    _money(fee)
                    if fee.amount < 0:
                        raise ValueError("Fee amounts cannot be negative")
            if record.counterpart_source_id is not None and record.counterpart_account is None:
                raise ValueError("Counterpart source IDs require a provider/account namespace")
            if record.counterpart_account is not None:
                if not isinstance(record.counterpart_account, AccountKey):
                    raise ValueError("Expected counterpart AccountKey")
                _text(record.counterpart_account.provider, "Counterpart provider")
                _text(record.counterpart_account.account_id, "Counterpart account")
            for reference in (record.transfer_reference, record.counterpart_source_id):
                if reference is not None:
                    _text(reference, "Counterpart/transfer reference")


def canonical_json(batch: NormalizedBatch) -> str:
    """Lossless Decimal/time evidence; caller validates before retaining/submitting."""
    def encode(value):
        if isinstance(value, Decimal):
            _decimal(value)
            return str(value)
        if isinstance(value, datetime):
            _time(value)
            return value.isoformat()
        raise TypeError("Unsupported canonical evidence value")
    return json.dumps(asdict(batch), default=encode, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
