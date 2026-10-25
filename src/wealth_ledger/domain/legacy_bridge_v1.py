"""Explicit one-way parser-v2 archive bridge; no parser dispatch or booking.

Old decoding is deliberately unchanged. Its optional declared timezone validation
may load the interpreter's read-only timezone reference data; this bridge performs
no application/workspace I/O and introduces no timezone lookup of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from decimal import Decimal
import hashlib
import re

from .. import source_v2 as old
from ..source_protocol import AccountKey, AssetKey
from . import canonical_v1 as c
from .validation_v1 import DomainDiagnosticV1, DomainValidationError, _admit, decimal_parts_v1, encode_domain_v1


@dataclass(frozen=True, slots=True)
class InstrumentMappingV1:
    source: AssetKey
    instrument: c.InstrumentV1


@dataclass(frozen=True, slots=True)
class FactMappingV1:
    source: c.SourceSelectorV1
    id: c.ScopedIdV1


@dataclass(frozen=True, slots=True)
class SnapshotMappingV1:
    source_id: str
    revision: str
    id: c.ScopedIdV1


@dataclass(frozen=True, slots=True)
class LegRoleAssignmentV1:
    source: c.SourceSelectorV1
    ordinal: int
    role: c.ActivityLegRoleV1


@dataclass(frozen=True, slots=True)
class BridgeContextV1:
    tenant_id: str
    portfolio_id: str
    source_connection: c.ScopedIdV1
    connections: tuple[c.SourceConnectionV1, ...]
    accounts: tuple[c.FinancialAccountV1, ...]
    aliases: tuple[c.AccountAliasV1, ...]
    instruments: tuple[InstrumentMappingV1, ...]
    issuers: tuple[c.IssuerV1, ...]
    facts: tuple[FactMappingV1, ...]
    snapshots: tuple[SnapshotMappingV1, ...]
    leg_roles: tuple[LegRoleAssignmentV1, ...]
    mapping_revision: str
    evidence_reference: str
    imported_at: c.SourceTimeV1 | None = None
    accepted_at: c.SourceTimeV1 | None = None


@dataclass(frozen=True, slots=True)
class BridgeResultV1:
    original_canonical: bytes
    canonical_sha256: str | None
    raw_sha256: str | None
    original_batch: old.NormalizedBatch | None
    mapping_reference: str | None
    candidate: c.DomainBatchV1 | None
    candidate_bytes: bytes | None
    blockers: tuple[DomainDiagnosticV1, ...]
    ingestible: bool = field(default=False, init=False)


def _block(code):
    raise DomainValidationError(code)


def _decimal(value):
    """Prove a bounded fixed spelling from the old coefficient/exponent first."""
    if type(value) is not Decimal or not value.is_finite():
        _block("bridge_precision_unrepresentable")
    parts = value.as_tuple()
    exponent, digits = parts.exponent, parts.digits
    # Bound the retained old spelling too, without asking Decimal to expand it.
    if len(digits) > c.MAX_DECIMAL_TOKEN or len(str(value)) > c.MAX_DECIMAL_TOKEN:
        _block("bridge_precision_unrepresentable")
    nonzero = any(digits)
    if not nonzero:
        if not -24 <= exponent <= 38:
            _block("bridge_precision_unrepresentable")
        token = ("-" if parts.sign else "") + "0" + ("." + "0" * -exponent if exponent < 0 else "")
    else:
        coefficient = "".join(str(digit) for digit in digits)
        trailing = len(coefficient) - len(coefficient.rstrip("0"))
        significant = len(coefficient.rstrip("0"))
        fractional = max(0, -exponent - trailing)
        integer = max(0, len(coefficient) + exponent)
        size = (1 if parts.sign else 0) + (integer if exponent >= 0 else max(1, integer) + 1 + -exponent)
        if significant > 38 or fractional > 24 or integer > 38 or size > c.MAX_DECIMAL_TOKEN:
            _block("bridge_precision_unrepresentable")
        point = len(coefficient) + exponent
        if exponent >= 0:
            token = coefficient + "0" * exponent
        elif point > 0:
            token = coefficient[:point] + "." + coefficient[point:]
        else:
            token = "0." + "0" * -point + coefficient
        token = ("-" if parts.sign else "") + token
    result = c.DecimalTokenV1(token)
    try:
        decimal_parts_v1(result)
    except DomainValidationError:
        _block("bridge_precision_unrepresentable")
    return result


def bridge_parser_v2(raw: bytes, canonical: bytes, context: BridgeContextV1) -> BridgeResultV1:
    """Validate exact old bytes and return one complete, always nonbooking result."""
    if type(raw) is not bytes or type(canonical) is not bytes:
        raise DomainValidationError("domain_invalid_type")
    canonical_hash = hashlib.sha256(canonical).hexdigest() if len(canonical) <= old.MAX_CANONICAL_BYTES else None
    raw_hash = hashlib.sha256(raw).hexdigest() if len(raw) <= old.MAX_RAW_BYTES else None
    reference = context.evidence_reference if type(context) is BridgeContextV1 and type(context.evidence_reference) is str and len(context.evidence_reference) <= c.MAX_TEXT else None
    if not raw or not canonical or canonical_hash is None or raw_hash is None:
        return BridgeResultV1(canonical, canonical_hash, raw_hash, None, reference, None, None, (DomainDiagnosticV1("bridge_legacy_invalid", "$"),))
    try:
        original = old.decode_batch(canonical, raw)
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        return BridgeResultV1(canonical, canonical_hash, raw_hash, None, reference, None, None, (DomainDiagnosticV1("bridge_legacy_invalid", "$"),))
    try:
        candidate = _convert(original, context, canonical_hash, raw_hash)
        encoded = encode_domain_v1(candidate)
        return BridgeResultV1(canonical, canonical_hash, raw_hash, original, reference, candidate, encoded, ())
    except DomainValidationError as error:
        code = error.diagnostic.code
        if code.startswith("domain_decimal") or code == "domain_subsatoshi":
            code = "bridge_precision_unrepresentable"
        elif code.startswith("domain_time"):
            code = "bridge_time_unrepresentable"
        elif code in {"domain_mapping_required", "domain_reference_out_of_scope", "domain_alias_conflict", "domain_duplicate_key", "domain_instrument_identity_ambiguous", "domain_invalid_type"}:
            code = "bridge_mapping_required"
        elif not code.startswith("bridge_") and code != "domain_resource_limit":
            code = "bridge_semantics_unrepresentable"
        return BridgeResultV1(canonical, canonical_hash, raw_hash, original, reference, None, None, (DomainDiagnosticV1(code, error.diagnostic.field, error.diagnostic.ordinal),))
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, OverflowError):
        return BridgeResultV1(canonical, canonical_hash, raw_hash, original, reference, None, None, (DomainDiagnosticV1("bridge_mapping_required", "$"),))


def _convert(batch, context, digest, raw_hash):
    if type(context) is not BridgeContextV1:
        _block("bridge_mapping_required")
    collections = ((context.connections, c.SourceConnectionV1), (context.accounts, c.FinancialAccountV1), (context.aliases, c.AccountAliasV1), (context.instruments, InstrumentMappingV1), (context.issuers, c.IssuerV1), (context.facts, FactMappingV1), (context.snapshots, SnapshotMappingV1), (context.leg_roles, LegRoleAssignmentV1))
    for values, expected in collections:
        if type(values) is not tuple or len(values) > c.MAX_COLLECTION:
            _block("bridge_mapping_required")
        if any(type(value) is not expected for value in values):
            _block("bridge_mapping_required")
    # Validate all caller-owned nested types before hashing/equality/conversion;
    # no unexpected object's __hash__, __eq__ or formatter is executed.
    def shape(expected, value):
        _admit(expected,value,"$",[0])
    for value in (context.tenant_id,context.portfolio_id,context.mapping_revision,context.evidence_reference):
        shape(str,value)
    shape(c.ScopedIdV1,context.source_connection)
    for values,expected in collections[:3] + (collections[4],):
        for value in values:
            shape(expected,value)
    for mapping in context.instruments:
        if type(mapping.source) is not AssetKey:
            _block("bridge_mapping_required")
        for name in ("kind","symbol","currency"):
            shape(str,getattr(mapping.source,name))
        for name in ("market","network","identifier"):
            shape(str | None,getattr(mapping.source,name))
        shape(c.InstrumentV1,mapping.instrument)
    for mapping in context.facts:
        shape(c.SourceSelectorV1,mapping.source)
        shape(c.ScopedIdV1,mapping.id)
    for mapping in context.snapshots:
        shape(str,mapping.source_id); shape(str,mapping.revision)
        shape(c.ScopedIdV1,mapping.id)
    for assignment in context.leg_roles:
        shape(c.SourceSelectorV1,assignment.source)
        shape(int,assignment.ordinal)
        shape(c.ActivityLegRoleV1,assignment.role)
    for value in (context.imported_at,context.accepted_at):
        shape(c.SourceTimeV1 | None,value)
    if type(context.source_connection) is not c.ScopedIdV1 or not any(conn.id == context.source_connection and conn.provider == batch.adapter.provider_id for conn in context.connections):
        _block("bridge_mapping_required")
    def archive(collection, ordinal=None, field_name=""):
        return c.LegacyRecordRefV1(digest, collection, ordinal, field_name)
    def time(value, collection, ordinal=None, field_name=""):
        return c.LegacyDateTimeV1(value.isoformat(), archive(collection, ordinal, field_name))
    def money(value):
        return None if value is None else c.MoneyV1(_decimal(value.amount), value.currency)
    def selector(account, kind, source_id, observation, revision, record_kind=None):
        return c.SourceSelectorV1(context.source_connection, batch.adapter.provider_id, None if account is None else account.account_id, kind, source_id, observation, revision, record_kind)
    def external(select):
        return c.ExternalSourceRefV1(context.tenant_id, context.portfolio_id, select)
    account_keys = {account.key for account in batch.accounts}
    aliases = {}
    for alias in context.aliases:
        key = AccountKey(alias.provider, alias.source_account_key)
        if key not in account_keys or alias.connection != context.source_connection or key in aliases:
            _block("bridge_mapping_required")
        aliases[key] = alias.account
    if set(aliases) != account_keys:
        _block("bridge_mapping_required")
    for metadata in batch.accounts:
        targets = tuple(item for item in context.accounts if item.id == aliases[metadata.key])
        if len(targets) != 1 or targets[0].role != metadata.role:
            _block("bridge_semantics_unrepresentable")
    def account(key):
        if key not in aliases:
            _block("bridge_mapping_required")
        return aliases[key]
    instruments = {}
    for mapping in context.instruments:
        if type(mapping.source) is not AssetKey or type(mapping.instrument) is not c.InstrumentV1 or mapping.source in instruments:
            _block("bridge_mapping_required")
        target, source = mapping.instrument, mapping.source
        if source.kind.upper() != target.kind and target.kind != "UNSUPPORTED":
            _block("bridge_semantics_unrepresentable")
        if source.currency != target.currency:
            _block("bridge_semantics_unrepresentable")
        if source.kind == "security" and (source.symbol != target.ticker or source.market != target.mic or target.mic is None or not re.fullmatch(r"[A-Z0-9]{4}", target.mic)):
            _block("bridge_mapping_required")
        if source.kind == "cash" and source.symbol != target.currency:
            _block("bridge_semantics_unrepresentable")
        if source.kind == "crypto" and (source.symbol != target.symbol or source.network != target.network):
            _block("bridge_semantics_unrepresentable")
        instruments[source] = target
    used_assets = set()
    def instrument(asset):
        if asset not in instruments:
            _block("bridge_mapping_required")
        used_assets.add(asset)
        return instruments[asset]
    record_selectors = tuple(selector(r.key.account, r.kind, r.key.source_id, r.observation_id if type(r) is old.Position else "", r.key.revision) for r in batch.records)
    fact_ids = {}
    for mapping in context.facts:
        if mapping.source not in record_selectors or mapping.source in fact_ids:
            _block("bridge_mapping_required")
        fact_ids[mapping.source] = mapping.id
    if set(fact_ids) != set(record_selectors):
        _block("bridge_mapping_required")
    snapshot_ids = {}
    for mapping in context.snapshots:
        key = (mapping.source_id, mapping.revision)
        if key not in {(s.source_id, s.revision) for s in batch.snapshots} or key in snapshot_ids:
            _block("bridge_mapping_required")
        snapshot_ids[key] = mapping.id
    if len(snapshot_ids) != len(batch.snapshots):
        _block("bridge_mapping_required")
    roles = {}
    expected_roles = {(record_selectors[i], j) for i, r in enumerate(batch.records) if type(r) is old.CryptoTransaction for j in range(len(r.legs))}
    for assignment in context.leg_roles:
        key = (assignment.source, assignment.ordinal)
        if type(assignment.ordinal) is not int or key not in expected_roles or key in roles or assignment.role not in {"ACQUISITION", "PAYMENT", "TRANSFER", "FEE", "OTHER"}:
            _block("bridge_mapping_required")
        roles[key] = assignment.role
    if set(roles) != expected_roles:
        _block("bridge_mapping_required")
    def identity(record, index):
        source = record_selectors[index]
        parent = None if record.key.supersedes_revision is None else external(selector(record.key.account, record.kind, record.key.source_id, source.observation_id, record.key.supersedes_revision))
        return c.FactIdentityV1(fact_ids[source], source, record.key.change, parent, record.revision_reason, context.evidence_reference, archive("records", index))
    def reference(value):
        if value is None:
            return None
        account(value.account)
        return external(selector(value.account, value.kind, value.source_id, "", None))
    coverage = []
    for index, old_scope in enumerate(batch.coverage):
        parent = None if old_scope.supersedes_revision is None else external(selector(old_scope.account, "coverage", old_scope.scope_id, old_scope.observation_id, old_scope.supersedes_revision, old_scope.kind))
        coverage.append(c.CoverageV1(context.source_connection, old_scope.account.account_id, account(old_scope.account), old_scope.kind, old_scope.scope_id, old_scope.revision, parent,
            c.IntervalV1(time(old_scope.start, "coverage", index, "start"), time(old_scope.end, "coverage", index, "end"), True, True), c.InstrumentScopeV1("all"), old_scope.status, old_scope.basis, old_scope.observation_id, archive("coverage", index)))
    positions, activities = {}, []
    for index, record in enumerate(batch.records):
        ident = identity(record, index)
        if type(record) is old.Position:
            target = instrument(record.asset)
            reasons = tuple(reason for condition, reason in ((record.quantity.is_signed() and not record.quantity.is_zero(), "signed_position"), (target.kind == "UNSUPPORTED", "unsupported_instrument")) if condition)
            item = c.PositionItemV1(ident, account(record.key.account), target.id, time(record.as_of, "records", index, "as_of"), _decimal(record.quantity), money(record.market_value), money(record.unit_price), money(record.cost_native), money(record.cost_cad), money(record.unrealized), record.name, record.instrument_type, record.exchange, c.SupportV1("unsupported" if reasons else "supported_shape", reasons))
            positions.setdefault(record.observation_id, []).append(item)
            continue
        economic = tuple(ref for ref in (reference(record.counterpart), reference(record.cash_leg_of) if type(record) is old.CashFlow else None) if ref is not None)
        life = None if record.lifecycle is None else archive("records", index, "lifecycle")
        # All lifecycle amounts/rates are also admitted to the new profile before
        # retaining their exact immutable archive reference; no hidden rounding.
        if record.lifecycle is not None:
            for amount in (record.lifecycle.payin, record.lifecycle.payout):
                instrument(amount.asset); _decimal(amount.quantity)
            for rate in (record.lifecycle.exchange_rate, record.lifecycle.index_rate):
                if rate is not None:
                    _decimal(rate.amount)
        cash, legs, fees, cost, cost_cad = None, (), None, None, None
        kind = {"purchase": "BUY", "sale": "SELL", "transfer": "TRANSFER", "fee": "FEE", "income": "INCOME", "deposit": "FUNDING", "withdrawal": "FUNDING"}.get(record.type, "UNSUPPORTED")
        reasons = ["unsupported_activity"] if kind == "UNSUPPORTED" else []
        if type(record) is old.CashFlow:
            cash = c.SourceCashFlowV1(money(record.amount), record.direction, record.boundary, record.transfer_reference, reference(record.counterpart), reference(record.cash_leg_of))
        else:
            legs = tuple(c.ActivityLegV1(account(leg.account), instrument(leg.asset).id, _decimal(leg.quantity), roles[(record_selectors[index], ordinal)]) for ordinal, leg in enumerate(record.legs))
            fees = None if record.fees is None else tuple(c.FeeV1(account(fee.account), instrument(fee.asset).id, _decimal(fee.quantity), fee.included_in_leg, fee.included_in_cost) for fee in record.fees)
            cost, cost_cad = money(record.acquisition_cost), money(record.acquisition_cost_cad)
            if (any(instrument(leg.asset).kind == "UNSUPPORTED" for leg in record.legs)
                    or any(instrument(fee.asset).kind == "UNSUPPORTED" for fee in record.fees or ())):
                reasons.append("unsupported_instrument")
        activities.append(c.ActivityEventV1(ident, time(record.occurred_at, "records", index, "occurred_at"), kind, record.type, record.status, record.status, legs, cost, cost_cad, fees, economic, record.transfer_reference, life, cash, c.SupportV1("unsupported" if reasons else "supported_shape", tuple(reasons))))
    snapshots = []
    for index, snapshot in enumerate(batch.snapshots):
        parent = None if snapshot.supersedes_revision is None else external(selector(None, "snapshot", snapshot.source_id, "", snapshot.supersedes_revision))
        references = tuple(external(selector(cv.account, "coverage", cv.scope_id, cv.observation_id, cv.revision, cv.kind)) for cv in batch.coverage if cv.kind == "holdings" and cv.observation_id == snapshot.source_id)
        snapshots.append(c.PositionSnapshotV1(snapshot_ids[(snapshot.source_id, snapshot.revision)], context.source_connection, snapshot.source_id, snapshot.revision, parent, time(snapshot.as_of, "snapshots", index, "as_of"), tuple(dict.fromkeys(account(key) for key in snapshot.accounts)), references, tuple(positions.get(snapshot.source_id, ())), archive("snapshots", index)))
    if used_assets != set(instruments):
        _block("bridge_mapping_required")
    # One explicit mapping may normalize several old descriptors into one listing.
    declarations = []
    seen = {}
    for mapping in context.instruments:
        previous = seen.get(mapping.instrument.id)
        if previous is not None and previous != mapping.instrument:
            _block("bridge_mapping_required")
        if previous is None:
            declarations.append(mapping.instrument)
            seen[mapping.instrument.id] = mapping.instrument
    provenance = c.ProvenanceV1(raw_hash, digest, batch.adapter.provider_id, batch.adapter.adapter_id, batch.adapter.adapter_version, batch.export_version, context.evidence_reference,
        time(batch.evidence.effective_at, "evidence", field_name="effective_at"), time(batch.evidence.context.evidence_at, "evidence", field_name="context.evidence_at"), context.imported_at, context.accepted_at, archive("batch"))
    return c.DomainBatchV1(c.CONTRACT_VERSION, c.DECIMAL_PROFILE, context.tenant_id, context.portfolio_id, context.mapping_revision, context.evidence_reference, provenance, context.accounts, context.connections, context.aliases, tuple(declarations), context.issuers, tuple(coverage), tuple(snapshots), tuple(activities))


def recover_legacy_v1(result: BridgeResultV1, reference: c.LegacyRecordRefV1):
    """Retrieve exact immutable legacy evidence, including every old dataclass field.

    This accesses the already strict-decoded archive, never a file or plugin. A
    reference does not by itself prove authenticity outside this result envelope.
    """
    _admit(c.LegacyRecordRefV1,reference,"$",[0])
    if type(result) is not BridgeResultV1 or type(result.original_batch) is not old.NormalizedBatch or type(result.canonical_sha256) is not str or reference.canonical_sha256 != result.canonical_sha256:
        raise DomainValidationError("domain_reference_out_of_scope")
    if reference.collection not in {"batch", "evidence", "membership", "accounts", "snapshots", "coverage", "records"}:
        raise DomainValidationError("domain_reference_out_of_scope")
    value = result.original_batch if reference.collection == "batch" else getattr(result.original_batch, reference.collection)
    if reference.collection in {"accounts", "snapshots", "coverage", "records"}:
        if type(value) is not tuple or type(reference.ordinal) is not int or not 0 <= reference.ordinal < len(value):
            raise DomainValidationError("domain_reference_out_of_scope")
        value = value[reference.ordinal]
    elif reference.ordinal is not None:
        raise DomainValidationError("domain_reference_out_of_scope")
    if reference.field:
        for name in reference.field.split("."):
            allowed=(old.NormalizedBatch,old.Evidence,old.ParseContext,old.RevisionContext,old.ScopeRevisionContext,old.Diagnostic,old.Account,old.Membership,old.Snapshot,old.Coverage,old.Position,old.CashFlow,old.CryptoTransaction,old.Lifecycle,old.AssetAmount,old.Rate,old.Fee,old.Reference,AccountKey,AssetKey,old.Money,old.RecordKey,old.CryptoLeg,old.AdapterInfo)
            if type(value) not in allowed or name not in {item.name for item in fields(value)}:
                raise DomainValidationError("domain_reference_out_of_scope")
            value = getattr(value, name)
    return value
