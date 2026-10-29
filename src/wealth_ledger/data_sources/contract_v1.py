"""Closed source-v1 primitives and immutable contexts, independent of booking."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
import hashlib
import json
import re
import types
from typing import Literal, Union, get_args, get_origin, get_type_hints
import uuid

from ..domain import canonical_v1 as c
from ..domain import legacy_bridge_v1 as bridge
from .. import source_v2 as parser
from .. import source_protocol

MAX_COUNTER = 9223372036854775807
MAX_RAW = 10 * 1024 * 1024
MAX_PAYLOAD = MAX_CONTEXT = 4 * 1024 * 1024
MAX_ENVELOPE = 8 * 1024 * 1024
NAMESPACE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
HASH = re.compile(r"[0-9a-f]{64}")


class ContractError(ValueError):
    """No source values or arbitrary exception strings in boundary failures."""
    def __init__(self, code="source_context_invalid", field="$.context"):
        self.code, self.field = code, field
        super().__init__(code)


def counter(value, *, minimum=0):
    if (type(value) is not str or not re.fullmatch(r"0|[1-9][0-9]{0,18}", value)
            or not minimum <= int(value) <= MAX_COUNTER):
        raise ContractError()
    return value


def identifier(value):
    try:
        parsed = uuid.UUID(value)
        if type(value) is not str or not parsed.int or str(parsed) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError() from None
    return value


def primitive(value):
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: primitive(getattr(value, f.name)) for f in fields(value)}
    if type(value) is tuple:
        return [primitive(item) for item in value]
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ContractError()
        return value.isoformat()
    if type(value) in (str, int, bool, type(None)):
        return value
    raise ContractError()


def canonical(value):
    """Encode admitted JSON primitives, never arbitrary repr/default coercion."""
    _admit_primitive(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _admit_primitive(value, depth=0):
    if depth > 32:
        raise ContractError("source_transport_limit")
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ContractError() from None
    elif type(value) in (int, bool, type(None)):
        pass
    elif type(value) is list:
        if len(value) > c.MAX_COLLECTION:
            raise ContractError("source_transport_limit")
        for item in value:
            _admit_primitive(item, depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ContractError()
            _admit_primitive(key, depth + 1)
            _admit_primitive(item, depth + 1)
    else:
        raise ContractError()


def load_json(data, *, limit=MAX_CONTEXT):
    if type(data) is not bytes or not data or len(data) > limit:
        raise ContractError("source_transport_limit")
    # Bound nesting before JSON allocates an arbitrarily deep object graph.
    level, quoted, escaped = 0, False, False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            level += 1
            if level > 32:
                raise ContractError("source_transport_limit")
        elif byte in (93, 125):
            level -= 1
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError()
            result[key] = value
        return result
    def forbidden(_):
        raise ContractError()
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                            parse_float=forbidden, parse_constant=forbidden)
        _admit_primitive(result)
        return result
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise ContractError() from None


def decode(expected, value, depth=0):
    """Only code-owned dataclasses; no type/import names come from input."""
    if depth > 32:
        raise ContractError("source_transport_limit")
    origin, args = get_origin(expected), get_args(expected)
    if origin in (types.UnionType, Union):
        for choice in args:
            try:
                return decode(choice, value, depth + 1)
            except ContractError:
                pass
        raise ContractError()
    if origin is Literal:
        if not any(type(value) is type(v) and value == v for v in args):
            raise ContractError()
        return value
    if origin is tuple:
        if type(value) is not list or len(value) > c.MAX_COLLECTION:
            raise ContractError()
        return tuple(decode(args[0], v, depth + 1) for v in value)
    if expected is datetime:
        try:
            if type(value) is not str:
                raise ValueError()
            result = datetime.fromisoformat(value)
            if result.tzinfo is None or result.utcoffset() is None or result.isoformat() != value:
                raise ValueError()
            return result
        except (ValueError, TypeError):
            raise ContractError() from None
    if is_dataclass(expected) and expected.__module__ in {
            __name__, c.__name__, bridge.__name__, parser.__name__, source_protocol.__name__}:
        names = {f.name for f in fields(expected)}
        if type(value) is not dict or set(value) != names:
            raise ContractError()
        hints = get_type_hints(expected)
        return expected(**{k: decode(hints[k], v, depth + 1) for k, v in value.items()})
    if expected not in (str, int, bool, type(None)) or type(value) is not expected:
        raise ContractError()
    if expected is str and len(value) > c.MAX_TEXT:
        raise ContractError()
    return value


@dataclass(frozen=True, slots=True)
class Descriptor:
    descriptor_version: Literal[1]
    plugin_id: str
    provider_id: str
    adapter_id: str
    package_distribution: str
    package_version: str
    entry_point_name: str
    entry_point_target: str
    artifact_sha256: str
    execution_image_digest: str
    source_contract_version: Literal[1]
    domain_contract_version: Literal[1]
    parser_api_version: Literal[2] | None
    payload_kind: Literal["parser_v2", "domain_v1"]
    capabilities: tuple[Literal["FILE_IMPORT", "PULL_API"], ...]
    format_versions: tuple[str, ...]
    asset_categories: tuple[Literal["SECURITY", "CASH", "CRYPTO", "UNSUPPORTED"], ...]
    alias_policy: Literal["forbidden", "required"]
    execution_profile: Literal["reviewed-file-v1", "contract-api-v1"]


def validate_descriptor(value):
    if type(value) is not Descriptor or decode(Descriptor, primitive(value)) != value:
        raise ContractError()
    for name in ("plugin_id", "provider_id", "adapter_id"):
        if not NAMESPACE.fullmatch(getattr(value, name)):
            raise ContractError()
    for name in ("package_distribution", "package_version", "entry_point_name"):
        text = getattr(value, name)
        if not text or text != text.strip() or len(text) > 200 or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
            raise ContractError()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", value.package_distribution):
        raise ContractError()
    if not NAMESPACE.fullmatch(value.entry_point_name):
        raise ContractError()
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", value.entry_point_target, re.ASCII):
        raise ContractError()
    if not HASH.fullmatch(value.artifact_sha256) or not HASH.fullmatch(value.execution_image_digest):
        raise ContractError()
    for collection in (value.capabilities, value.format_versions, value.asset_categories):
        if not collection or tuple(sorted(set(collection))) != collection:
            raise ContractError()
    if len(value.format_versions) > 32 or any(not re.fullmatch(r"[\x21-\x7e]{1,128}", x) for x in value.format_versions):
        raise ContractError()
    if ((value.payload_kind == "parser_v2") != (value.parser_api_version == 2)
            or len(canonical(primitive(value))) > 16384):
        raise ContractError()
    return value


def installation_id(descriptor):
    return digest(primitive(validate_descriptor(descriptor)))


@dataclass(frozen=True, slots=True)
class InternalRealm:
    database: str
    database_oid: str
    server_address: str | None
    server_port: int | None
    incarnation: str
    restore_epoch: str

    @classmethod
    def from_principal(cls, principal):
        from ..persistence.identity import Principal, REALM_KEYS
        if type(principal) is not Principal:
            raise ContractError()
        row = dict(zip(REALM_KEYS, principal.realm))
        return cls(row["database"], str(row["database_oid"]), row["server_address"],
                   row["server_port"], row["incarnation"], str(row["epoch"]))


@dataclass(frozen=True, slots=True)
class IdentityReference:
    id: c.ScopedIdV1
    source: c.SourceSelectorV1
    change: Literal["original", "correction", "void"]
    parent: c.ExternalSourceRefV1 | None


@dataclass(frozen=True, slots=True)
class PositionReference:
    identity: IdentityReference
    account: c.ScopedIdV1
    instrument: c.ScopedIdV1


@dataclass(frozen=True, slots=True)
class CoverageReference:
    connection: c.ScopedIdV1
    source_account_key: str
    account: c.ScopedIdV1
    kind: c.FactKindV1
    scope_id: str
    revision: str
    parent: c.ExternalSourceRefV1 | None
    instrument_scope: c.InstrumentScopeV1
    observation_id: str


@dataclass(frozen=True, slots=True)
class SnapshotReference:
    id: c.ScopedIdV1
    connection: c.ScopedIdV1
    source_id: str
    revision: str
    parent: c.ExternalSourceRefV1 | None
    accounts: tuple[c.ScopedIdV1, ...]
    coverage: tuple[c.ExternalSourceRefV1, ...]
    items: tuple[PositionReference, ...]


@dataclass(frozen=True, slots=True)
class LegReference:
    account: c.ScopedIdV1
    instrument: c.ScopedIdV1
    role: c.ActivityLegRoleV1


@dataclass(frozen=True, slots=True)
class FeeReference:
    account: c.ScopedIdV1
    instrument: c.ScopedIdV1


@dataclass(frozen=True, slots=True)
class CashFlowReference:
    direction: Literal["in", "out"]
    boundary: Literal["external", "internal", "unclassified"]
    transfer_reference: str | None
    counterpart: c.ExternalSourceRefV1 | None
    cash_leg_of: c.ExternalSourceRefV1 | None


@dataclass(frozen=True, slots=True)
class ActivityReference:
    identity: IdentityReference
    legs: tuple[LegReference, ...]
    fees: tuple[FeeReference, ...] | None
    economic_references: tuple[c.ExternalSourceRefV1, ...]
    transfer_reference: str | None
    cash_flow: CashFlowReference | None


@dataclass(frozen=True, slots=True)
class ReferenceGraphV1:
    coverage: tuple[CoverageReference, ...]
    snapshots: tuple[SnapshotReference, ...]
    activities: tuple[ActivityReference, ...]


def project_references(batch):
    """Projection for comparison only; never manufacture a permission from output."""
    def take(cls, item, **replacements):
        return cls(**{f.name: replacements.get(f.name, getattr(item, f.name)) for f in fields(cls)})
    def identity(item):
        return take(IdentityReference, item)
    return ReferenceGraphV1(
        tuple(take(CoverageReference, x) for x in batch.coverage),
        tuple(take(SnapshotReference, x, items=tuple(take(PositionReference, i, identity=identity(i.identity)) for i in x.items)) for x in batch.snapshots),
        tuple(take(ActivityReference, x, identity=identity(x.identity),
                   legs=tuple(take(LegReference, leg) for leg in x.legs),
                   fees=None if x.fees is None else tuple(take(FeeReference, fee) for fee in x.fees),
                   cash_flow=None if x.cash_flow is None else take(CashFlowReference, x.cash_flow)) for x in batch.activities))


@dataclass(frozen=True, slots=True)
class DomainAllowed:
    tenant_id: str
    portfolio_id: str
    connection: c.SourceConnectionV1
    accounts: tuple[c.FinancialAccountV1, ...]
    aliases: tuple[c.AccountAliasV1, ...]
    instruments: tuple[c.InstrumentV1, ...]
    issuers: tuple[c.IssuerV1, ...]
    facts: tuple[bridge.FactMappingV1, ...]
    snapshots: tuple[bridge.SnapshotMappingV1, ...]
    leg_roles: tuple[bridge.LegRoleAssignmentV1, ...]
    mapping_revision: str
    evidence_reference: str
    imported_at: c.SourceTimeV1 | None
    accepted_at: c.SourceTimeV1 | None
    reference_graph: ReferenceGraphV1


@dataclass(frozen=True, slots=True)
class ParserBinding:
    codec: Literal["parser2_context_v1"]
    value: parser.ParseContext


@dataclass(frozen=True, slots=True)
class BridgeBinding:
    codec: Literal["bridge_context_v1"]
    value: bridge.BridgeContextV1


@dataclass(frozen=True, slots=True)
class DomainBinding:
    codec: Literal["domain_allowed_v1"]
    value: DomainAllowed


@dataclass(frozen=True, slots=True)
class SourceContextV1:
    context_version: Literal[1]
    realm: InternalRealm
    tenant_id: str
    portfolio_id: str
    connection: c.SourceConnectionV1
    connection_version: str
    connection_generation: str
    enablement_generation: str
    availability_generation: str
    installation_descriptor: Descriptor
    installation_id: str
    transport: Literal["FILE_IMPORT", "PULL_API"]
    format_version: str
    mapping_revision: str
    evidence_reference: str
    parse_context: ParserBinding | None
    binding_context: BridgeBinding | DomainBinding
    expected_provenance: c.ProvenanceV1


def _walk(value):
    yield value
    if is_dataclass(value):
        for f in fields(value):
            yield from _walk(getattr(value, f.name))
    elif type(value) is tuple:
        for item in value:
            yield from _walk(item)


def _unique(items):
    if len(set(items)) != len(items):
        raise ContractError()


def validate_context(value):
    if type(value) is not SourceContextV1 or decode(SourceContextV1, primitive(value)) != value:
        raise ContractError()
    descriptor = validate_descriptor(value.installation_descriptor)
    identifier(value.tenant_id); identifier(value.portfolio_id); identifier(value.realm.incarnation)
    counter(value.realm.database_oid, minimum=1); counter(value.realm.restore_epoch)
    if not value.realm.database or (value.realm.server_port is not None and not 1 <= value.realm.server_port <= 65535):
        raise ContractError()
    for name in ("connection_generation", "enablement_generation", "availability_generation"):
        counter(getattr(value, name), minimum=1 if name == "availability_generation" else 0)
    if (value.installation_id != installation_id(descriptor)
            or value.connection_version != digest(primitive(value.connection))
            or value.connection.id.kind != "connection"
            or value.connection.provider != descriptor.provider_id
            or value.connection.kind != value.transport or value.transport not in descriptor.capabilities
            or value.format_version not in descriptor.format_versions
            or not value.mapping_revision or not value.evidence_reference):
        raise ContractError()
    binding = value.binding_context.value
    if descriptor.payload_kind == "parser_v2":
        if type(value.binding_context) is not BridgeBinding or type(value.parse_context) is not ParserBinding:
            raise ContractError()
        parser.validate_context(value.parse_context.value)
        if binding.connections != (value.connection,) or binding.source_connection != value.connection.id:
            raise ContractError()
    elif type(value.binding_context) is not DomainBinding or value.parse_context is not None or binding.connection != value.connection:
        raise ContractError()
    if (binding.tenant_id != value.tenant_id or binding.portfolio_id != value.portfolio_id
            or binding.mapping_revision != value.mapping_revision or binding.evidence_reference != value.evidence_reference
            or value.expected_provenance.evidence_reference != value.evidence_reference
            or value.expected_provenance.provider != descriptor.provider_id
            or value.expected_provenance.adapter != descriptor.adapter_id
            or value.expected_provenance.export_version != value.format_version
            or value.expected_provenance.imported_at != binding.imported_at
            or value.expected_provenance.accepted_at != binding.accepted_at):
        raise ContractError()
    for name in ("raw_sha256", "canonical_sha256"):
        token = getattr(value.expected_provenance, name)
        if token is not None and not HASH.fullmatch(token):
            raise ContractError()
    for item in _walk(value):
        if type(item) is c.ScopedIdV1:
            identifier(item.value)
            if item.tenant_id != value.tenant_id or item.portfolio_id != value.portfolio_id:
                raise ContractError()
        if type(item) is c.ExternalSourceRefV1 and (item.tenant_id != value.tenant_id or item.portfolio_id != value.portfolio_id):
            raise ContractError()
        if type(item) is c.SourceSelectorV1 and (item.connection != value.connection.id or item.provider != descriptor.provider_id):
            raise ContractError()
    for sequence, kind in ((binding.accounts, "account"), (binding.issuers, "issuer")):
        _unique(tuple(x.id for x in sequence))
        if any(x.id.kind != kind for x in sequence):
            raise ContractError()
    _unique(tuple(x.id for x in binding.facts))
    _unique(tuple(x.source for x in binding.facts))
    _unique(tuple(x.id for x in binding.snapshots))
    _unique(tuple((x.source, x.ordinal) for x in binding.leg_roles))
    from ..domain.validation_v1 import DomainValidationError
    try:
        _context_semantics(value)
        if type(binding) is DomainAllowed:
            validate_reference_graph(binding)
    except DomainValidationError:
        # Context admission is a source diagnostic at stage3, not a leaked domain
        # exception or a later fingerprint/payload mismatch.
        raise ContractError() from None
    if len(canonical(primitive(value))) > MAX_CONTEXT:
        raise ContractError("source_transport_limit")
    return value



def _context_semantics(value):
    """Admit accepted primitive semantics without inventing a financial batch.

    Missing mappings may still reach the unchanged bridge/domain mapper. A present
    direct external reference, however, must name an explicitly declared alias;
    this checks its scope, not existence or authority of a historical fact.
    """
    from ..domain.validation_v1 import _time, _text, _LEGACY_FIELDS
    binding=value.binding_context.value
    for text in (value.mapping_revision,value.evidence_reference,value.expected_provenance.adapter_version):
        _text(text,'$')
    accounts={item.id for item in binding.accounts}
    aliases={}
    for alias in binding.aliases:
        _text(alias.source_account_key,'$');_text(alias.mapping_revision,'$');_text(alias.evidence_reference,'$')
        if (alias.connection!=value.connection.id or alias.provider!=value.connection.provider
                or alias.account not in accounts or alias.mapping_revision!=value.mapping_revision):
            raise ContractError()
        key=(alias.connection,alias.provider,alias.source_account_key,alias.mapping_revision)
        if key in aliases:raise ContractError()
        aliases[key]=alias.account
    for item in _walk(value):
        if type(item) in (c.InstantV1,c.DateOnlyV1,c.LegacyDateTimeV1):
            _time(item,'$')
        elif type(item) is c.LegacyRecordRefV1:
            if (not HASH.fullmatch(item.canonical_sha256) or item.canonical_sha256!=value.expected_provenance.canonical_sha256
                    or item.field not in _LEGACY_FIELDS):
                raise ContractError()
            if item.collection in {'accounts','snapshots','coverage','records'}:
                if item.ordinal is None or not 0<=item.ordinal<c.MAX_COLLECTION:raise ContractError()
            elif item.ordinal is not None:raise ContractError()
        elif type(item) is c.SourceSelectorV1:
            _text(item.provider,'$');_text(item.source_id,'$')
            if item.source_account_key is not None:_text(item.source_account_key,'$')
            if item.revision is not None:_text(item.revision,'$')
            if item.kind in {'holdings','cash_flows','crypto_transactions','activity'} and (item.source_account_key is None or item.record_kind is not None):
                raise ContractError()
            if item.kind=='coverage' and (item.source_account_key is None or item.record_kind is None):raise ContractError()
            if item.kind in {'snapshot','membership'} and (item.source_account_key is not None or item.record_kind is not None or item.observation_id):
                raise ContractError()
        elif type(item) is c.ExternalSourceRefV1 and type(binding) is DomainAllowed:
            selector=item.selector
            if selector.source_account_key is not None and (selector.connection,selector.provider,selector.source_account_key,value.mapping_revision) not in aliases:
                raise ContractError()
    # If a current coverage alias is explicitly supplied, its target must agree.
    # An absent mapping remains representable for the downstream mapping blocker.
    if type(binding) is DomainAllowed:
        for coverage in binding.reference_graph.coverage:
            key=(coverage.connection,value.connection.provider,coverage.source_account_key,value.mapping_revision)
            if key in aliases and aliases[key]!=coverage.account:raise ContractError()


def validate_reference_graph(binding):
    graph = binding.reference_graph
    accounts = {x.id for x in binding.accounts}
    instruments = {x.id for x in binding.instruments}
    if len(instruments) != len(binding.instruments) or any(x.id.kind != "instrument" for x in binding.instruments):
        raise ContractError()
    fact_maps, snapshot_maps, roles = [], [], []
    def account(value):
        if value not in accounts:
            raise ContractError()
    def instrument(value):
        if value not in instruments:
            raise ContractError()
    def fact(identity):
        if identity.id.kind != "fact":
            raise ContractError()
        if (identity.change == "original") != (identity.parent is None):
            raise ContractError()
        from ..domain.validation_v1 import _parent
        _parent(identity.source, identity.parent, "$")
        fact_maps.append(bridge.FactMappingV1(identity.source, identity.id))
    for coverage in graph.coverage:
        if coverage.connection != binding.connection.id:
            raise ContractError()
        if coverage.parent is not None:
            selector = coverage.parent.selector
            if (selector.connection != coverage.connection or selector.source_account_key != coverage.source_account_key
                    or selector.kind != "coverage" or selector.source_id != coverage.scope_id
                    or selector.record_kind != coverage.kind or selector.observation_id != coverage.observation_id
                    or selector.revision in (None, coverage.revision)):
                raise ContractError()
        account(coverage.account)
        for i in coverage.instrument_scope.instruments:
            instrument(i)
    _unique(tuple((x.connection, x.source_account_key, x.kind, x.scope_id, x.revision, x.observation_id) for x in graph.coverage))
    for snapshot in graph.snapshots:
        if snapshot.id.kind != "snapshot" or snapshot.connection != binding.connection.id:
            raise ContractError()
        if snapshot.parent is not None:
            selector = snapshot.parent.selector
            if (selector.connection != snapshot.connection or selector.kind != "snapshot"
                    or selector.source_id != snapshot.source_id or selector.revision in (None, snapshot.revision)):
                raise ContractError()
        snapshot_maps.append(bridge.SnapshotMappingV1(snapshot.source_id, snapshot.revision, snapshot.id))
        for a in snapshot.accounts:
            account(a)
        for item in snapshot.items:
            fact(item.identity); account(item.account); instrument(item.instrument)
    for activity in graph.activities:
        fact(activity.identity)
        for ordinal, leg in enumerate(activity.legs):
            account(leg.account); instrument(leg.instrument)
            roles.append(bridge.LegRoleAssignmentV1(activity.identity.source, ordinal, leg.role))
        for fee in activity.fees or ():
            account(fee.account); instrument(fee.instrument)
    _unique(tuple(x.id for x in fact_maps)); _unique(tuple(x.source for x in fact_maps))
    _unique(tuple(x.id for x in snapshot_maps)); _unique(tuple((x.source_id, x.revision) for x in snapshot_maps))
    if set(fact_maps) != set(binding.facts) or set(snapshot_maps) != set(binding.snapshots) or set(roles) != set(binding.leg_roles):
        raise ContractError()


def context_bytes(value):
    return canonical(primitive(validate_context(value)))


def decode_context(data):
    try:
        return validate_context(decode(SourceContextV1, load_json(data)))
    except (ContractError, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise ContractError() from None


def fingerprint(context):
    validate_context(context)
    return {"incarnation": context.realm.incarnation, "restore_epoch": context.realm.restore_epoch,
            "tenant_id": context.tenant_id, "portfolio_id": context.portfolio_id,
            "connection_id": context.connection.id.value, "connection_version": context.connection_version,
            "connection_generation": context.connection_generation, "enablement_generation": context.enablement_generation,
            "availability_generation": context.availability_generation, "installation_id": context.installation_id,
            "artifact_sha256": context.installation_descriptor.artifact_sha256,
            "execution_image_digest": context.installation_descriptor.execution_image_digest,
            "mapping_revision": context.mapping_revision, "context_sha256": hashlib.sha256(context_bytes(context)).hexdigest()}


def adapter_input(context):
    validate_context(context)
    result = {"context_version": 1, "payload_kind": context.installation_descriptor.payload_kind,
              "context": primitive(context.parse_context if context.parse_context is not None else context.binding_context)}
    if context.parse_context is None:
        result["expected_provenance"] = primitive(context.expected_provenance)
    if len(canonical(result)) > MAX_CONTEXT:
        raise ContractError("source_transport_limit")
    return result


@dataclass(frozen=True, slots=True)
class Definition:
    plugin_id: str
    provider_id: str
    display_name: str
    publisher_label: str
    docs_url: str | None


@dataclass(frozen=True, slots=True)
class Availability:
    installation_id: str
    status: Literal["ACTIVE", "RETIRED", "REVOKED"]
    availability_generation: str


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    schema_version: Literal[1]
    catalog_revision: str
    definitions: tuple[Definition, ...]
    installations: tuple[Descriptor, ...]
    availability: tuple[Availability, ...]
