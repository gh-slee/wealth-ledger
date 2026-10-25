"""Closed immutable domain-v1 vocabulary, independent of parser API versions.

These records describe source facts, never accepted balances or booking authority.
IDs, mappings, clocks and provenance are supplied explicitly by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CONTRACT_VERSION = 1
DECIMAL_PROFILE = "decimal-38s-24f-38i-v1"
MAX_CANONICAL_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 32
MAX_COLLECTION = 50_000
MAX_TEXT = 4096
MAX_DECIMAL_TOKEN = 256

EntityKindV1 = Literal["account", "connection", "instrument", "issuer", "fact", "snapshot"]
FactKindV1 = Literal["holdings", "cash_flows", "crypto_transactions", "activity"]
SourceKindV1 = Literal["holdings", "cash_flows", "crypto_transactions", "activity", "snapshot", "coverage", "membership"]
ActivityKindV1 = Literal["BUY", "SELL", "TRANSFER", "FEE", "INCOME", "FUNDING", "CORPORATE_ACTION", "UNSUPPORTED"]
ActivityLegRoleV1 = Literal["ACQUISITION", "PAYMENT", "TRANSFER", "FEE", "OTHER"]


@dataclass(frozen=True, slots=True)
class ScopedIdV1:
    tenant_id: str
    portfolio_id: str
    kind: EntityKindV1
    value: str


@dataclass(frozen=True, slots=True)
class LegacyRecordRefV1:
    canonical_sha256: str
    collection: Literal["batch", "evidence", "membership", "accounts", "snapshots", "coverage", "records"]
    ordinal: int | None
    field: str


@dataclass(frozen=True, slots=True)
class InstantV1:
    token: str
    zone: str | None
    fractional_digits: int
    tag: Literal["instant"] = "instant"


@dataclass(frozen=True, slots=True)
class DateOnlyV1:
    token: str
    zone: str | None
    tag: Literal["date_only"] = "date_only"


@dataclass(frozen=True, slots=True)
class LegacyDateTimeV1:
    token: str
    archive: LegacyRecordRefV1
    precision: Literal["legacy_unspecified"] = "legacy_unspecified"
    tag: Literal["legacy_datetime"] = "legacy_datetime"


SourceTimeV1 = InstantV1 | DateOnlyV1 | LegacyDateTimeV1


@dataclass(frozen=True, slots=True)
class PointV1:
    at: SourceTimeV1
    tag: Literal["point"] = "point"


@dataclass(frozen=True, slots=True)
class IntervalV1:
    start: SourceTimeV1
    end: SourceTimeV1
    start_inclusive: bool
    end_inclusive: bool
    tag: Literal["interval"] = "interval"


TimeSelectorV1 = PointV1 | IntervalV1


@dataclass(frozen=True, slots=True)
class DecimalTokenV1:
    token: str


@dataclass(frozen=True, slots=True)
class MoneyV1:
    amount: DecimalTokenV1
    currency: str


@dataclass(frozen=True, slots=True)
class SourceSelectorV1:
    connection: ScopedIdV1
    provider: str
    source_account_key: str | None
    kind: SourceKindV1
    source_id: str
    observation_id: str
    revision: str | None
    record_kind: FactKindV1 | None = None


@dataclass(frozen=True, slots=True)
class ExternalSourceRefV1:
    tenant_id: str
    portfolio_id: str
    selector: SourceSelectorV1


@dataclass(frozen=True, slots=True)
class FactIdentityV1:
    id: ScopedIdV1
    source: SourceSelectorV1
    change: Literal["original", "correction", "void"]
    parent: ExternalSourceRefV1 | None
    reason: str | None
    evidence_reference: str
    legacy: LegacyRecordRefV1 | None = None


@dataclass(frozen=True, slots=True)
class FinancialAccountV1:
    id: ScopedIdV1
    category: str
    role: Literal["investment", "crypto", "funding"]
    label: str


@dataclass(frozen=True, slots=True)
class SourceConnectionV1:
    id: ScopedIdV1
    provider: str
    kind: Literal["FILE_IMPORT", "PULL_API"]


@dataclass(frozen=True, slots=True)
class AccountAliasV1:
    connection: ScopedIdV1
    provider: str
    source_account_key: str
    account: ScopedIdV1
    mapping_revision: str
    evidence_reference: str


@dataclass(frozen=True, slots=True)
class IssuerV1:
    id: ScopedIdV1
    label: str


@dataclass(frozen=True, slots=True)
class IdentifierHintV1:
    scheme: str
    value: str


@dataclass(frozen=True, slots=True)
class InstrumentV1:
    id: ScopedIdV1
    kind: Literal["SECURITY", "CASH", "CRYPTO", "UNSUPPORTED"]
    currency: str | None
    ticker: str | None
    mic: str | None
    symbol: str | None
    network: str | None
    settlement_identity: str | None
    issuer: ScopedIdV1 | None
    identifiers: tuple[IdentifierHintV1, ...]
    source_descriptor: str
    evidence_reference: str


@dataclass(frozen=True, slots=True)
class InstrumentScopeV1:
    tag: Literal["all", "instruments", "category"]
    instruments: tuple[ScopedIdV1, ...] = ()
    category: Literal["SECURITY", "CASH", "CRYPTO", "UNSUPPORTED"] | None = None


@dataclass(frozen=True, slots=True)
class CoverageV1:
    connection: ScopedIdV1
    source_account_key: str
    account: ScopedIdV1
    kind: FactKindV1
    scope_id: str
    revision: str
    parent: ExternalSourceRefV1 | None
    time: TimeSelectorV1
    instrument_scope: InstrumentScopeV1
    status: Literal["complete", "partial", "unknown"]
    basis: str
    observation_id: str
    legacy: LegacyRecordRefV1 | None = None


@dataclass(frozen=True, slots=True)
class SupportV1:
    classification: Literal["supported_shape", "unsupported"]
    reasons: tuple[Literal["unsupported_instrument", "signed_position", "unsupported_activity", "unsupported_status"], ...] = ()


@dataclass(frozen=True, slots=True)
class PositionItemV1:
    identity: FactIdentityV1
    account: ScopedIdV1
    instrument: ScopedIdV1
    as_of: SourceTimeV1
    quantity: DecimalTokenV1
    market_value: MoneyV1 | None
    unit_price: MoneyV1 | None
    cost_native: MoneyV1 | None
    cost_cad: MoneyV1 | None
    unrealized: MoneyV1 | None
    source_name: str
    source_type: str
    source_exchange: str
    support: SupportV1


@dataclass(frozen=True, slots=True)
class PositionSnapshotV1:
    id: ScopedIdV1
    connection: ScopedIdV1
    source_id: str
    revision: str
    parent: ExternalSourceRefV1 | None
    as_of: SourceTimeV1
    accounts: tuple[ScopedIdV1, ...]
    coverage: tuple[ExternalSourceRefV1, ...]
    items: tuple[PositionItemV1, ...]
    legacy: LegacyRecordRefV1 | None = None


@dataclass(frozen=True, slots=True)
class ActivityLegV1:
    account: ScopedIdV1
    instrument: ScopedIdV1
    quantity: DecimalTokenV1
    role: ActivityLegRoleV1


@dataclass(frozen=True, slots=True)
class FeeV1:
    account: ScopedIdV1
    instrument: ScopedIdV1
    quantity: DecimalTokenV1
    included_in_leg: bool
    included_in_cost: bool


@dataclass(frozen=True, slots=True)
class SourceCashFlowV1:
    cash_amount: MoneyV1
    direction: Literal["in", "out"]
    boundary: Literal["external", "internal", "unclassified"]
    transfer_reference: str | None
    counterpart: ExternalSourceRefV1 | None
    cash_leg_of: ExternalSourceRefV1 | None


@dataclass(frozen=True, slots=True)
class ActivityEventV1:
    identity: FactIdentityV1
    event_time: SourceTimeV1
    kind: ActivityKindV1
    source_kind: str
    source_status: str
    status: Literal["completed", "pending", "cancelled", "unsupported"]
    legs: tuple[ActivityLegV1, ...]
    acquisition_cost: MoneyV1 | None
    acquisition_cost_cad: MoneyV1 | None
    fees: tuple[FeeV1, ...] | None
    economic_references: tuple[ExternalSourceRefV1, ...]
    transfer_reference: str | None
    lifecycle: LegacyRecordRefV1 | None
    cash_flow: SourceCashFlowV1 | None
    support: SupportV1


@dataclass(frozen=True, slots=True)
class ProvenanceV1:
    raw_sha256: str
    canonical_sha256: str | None
    provider: str
    adapter: str
    adapter_version: str
    export_version: str
    evidence_reference: str
    source_effective_at: SourceTimeV1 | None
    evidence_at: SourceTimeV1 | None
    imported_at: SourceTimeV1 | None
    accepted_at: SourceTimeV1 | None
    legacy: LegacyRecordRefV1 | None


@dataclass(frozen=True, slots=True)
class DomainBatchV1:
    contract_version: int
    profile: str
    tenant_id: str
    portfolio_id: str
    mapping_revision: str
    evidence_reference: str
    provenance: ProvenanceV1
    accounts: tuple[FinancialAccountV1, ...]
    connections: tuple[SourceConnectionV1, ...]
    aliases: tuple[AccountAliasV1, ...]
    instruments: tuple[InstrumentV1, ...]
    issuers: tuple[IssuerV1, ...]
    coverage: tuple[CoverageV1, ...]
    snapshots: tuple[PositionSnapshotV1, ...]
    activities: tuple[ActivityEventV1, ...]
