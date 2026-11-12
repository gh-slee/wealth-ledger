"""Bounded source envelope admission; every successful shape remains nonbooking."""
from dataclasses import dataclass, field
import base64
import binascii
import hashlib

from .contract_v1 import (ContractError, HASH, MAX_CONTEXT, MAX_ENVELOPE, MAX_PAYLOAD,
    MAX_RAW, SourceContextV1, canonical, context_bytes, decode_context, fingerprint,
    load_json, primitive, project_references, counter, identifier)
from .. import source_v2 as parser
from ..domain import legacy_bridge_v1 as bridge
from ..domain.validation_v1 import DomainValidationError, decode_domain_v1

SOURCE_CODES = frozenset("""source_transport_limit source_transport_invalid
source_context_invalid source_version_unsupported source_format_unsupported
source_context_mismatch source_payload_invalid source_payload_digest_mismatch
source_reference_mismatch""".split())
FINGERPRINT_FIELDS = ("incarnation", "restore_epoch", "tenant_id", "portfolio_id",
    "connection_id", "connection_version", "connection_generation", "enablement_generation",
    "availability_generation", "installation_id", "artifact_sha256", "execution_image_digest",
    "mapping_revision", "context_sha256")
ENVELOPE_FIELDS = ("envelope_version", "domain_contract_version", "parser_api_version",
    "transport", "format_version", "payload_kind", "fingerprint", "payload_sha256", "payload_base64")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    namespace: str
    code: str
    field: str
    ordinal: int | None = None


@dataclass(frozen=True, slots=True)
class TransportOutcomeV1:
    status: str
    candidate_domain_base64: str | None
    diagnostics: tuple[Diagnostic, ...]
    ingestible: bool = field(default=False, init=False)


def _blocked(code, path):
    assert code in SOURCE_CODES
    return TransportOutcomeV1("BLOCKED", None, (Diagnostic("source_v1", code, path),))


def _domain_blocked(diagnostics):
    return TransportOutcomeV1("BLOCKED", None, tuple(
        Diagnostic("domain_v1", x.code, x.field, x.ordinal) for x in diagnostics))


def make_envelope(payload, context):
    """Trusted host framing, not a proof of financial acceptance or live authority."""
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_PAYLOAD:
        raise ContractError("source_transport_limit")
    envelope = {"envelope_version": 1, "domain_contract_version": 1,
        "parser_api_version": context.installation_descriptor.parser_api_version,
        "transport": context.transport, "format_version": context.format_version,
        "payload_kind": context.installation_descriptor.payload_kind,
        "fingerprint": fingerprint(context), "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_base64": base64.b64encode(payload).decode("ascii")}
    return canonical(envelope)


def _envelope(data):
    try:
        result = load_json(data, limit=MAX_ENVELOPE)
    except ContractError as error:
        return _blocked("source_transport_limit" if error.code == "source_transport_limit" else "source_transport_invalid", "$.envelope")
    if type(result) is not dict or set(result) != set(ENVELOPE_FIELDS) or canonical(result) != data:
        return _blocked("source_transport_invalid", "$.envelope")
    for name in ENVELOPE_FIELDS:
        value = result[name]
        valid = True
        if name in ("envelope_version", "domain_contract_version"):
            valid = type(value) is int
        elif name == "parser_api_version":
            valid = value is None or type(value) is int
        elif name == "transport":
            valid = value in ("FILE_IMPORT", "PULL_API")
        elif name == "payload_kind":
            valid = value in ("parser_v2", "domain_v1")
        elif name == "format_version":
            valid = type(value) is str and 1 <= len(value) <= 128 and value.isascii()
        elif name == "fingerprint":
            valid = (type(value) is dict and set(value) == set(FINGERPRINT_FIELDS)
                     and all(type(value[x]) is str for x in FINGERPRINT_FIELDS))
            if valid:
                try:
                    for key in ("incarnation", "tenant_id", "portfolio_id", "connection_id"):
                        identifier(value[key])
                    for key in ("restore_epoch", "connection_generation", "enablement_generation", "availability_generation"):
                        counter(value[key], minimum=1 if key == "availability_generation" else 0)
                    for key in ("connection_version", "installation_id", "artifact_sha256", "execution_image_digest", "context_sha256"):
                        if not HASH.fullmatch(value[key]):
                            raise ContractError()
                    if not value["mapping_revision"] or len(value["mapping_revision"]) > 4096:
                        raise ContractError()
                except ContractError:
                    valid = False
        elif name == "payload_sha256":
            valid = type(value) is str and HASH.fullmatch(value) is not None
        elif name == "payload_base64":
            valid = type(value) is str
        if not valid:
            return _blocked("source_transport_invalid", "$.envelope." + name)
    return result


def _check_references(batch, context):
    binding = context.binding_context.value
    if (batch.tenant_id != context.tenant_id or batch.portfolio_id != context.portfolio_id
            or batch.mapping_revision != context.mapping_revision
            or batch.evidence_reference != context.evidence_reference
            or batch.provenance != context.expected_provenance):
        return False
    if context.parse_context is not None:
        return True  # The exact saved bridge produced these declarations and references.
    actual_facts = tuple(bridge.FactMappingV1(x.identity.source, x.identity.id)
        for snapshot in batch.snapshots for x in snapshot.items) + tuple(
        bridge.FactMappingV1(x.identity.source, x.identity.id) for x in batch.activities)
    actual_snapshots = tuple(bridge.SnapshotMappingV1(x.source_id, x.revision, x.id) for x in batch.snapshots)
    actual_roles = tuple(bridge.LegRoleAssignmentV1(x.identity.source, i, leg.role)
        for x in batch.activities for i, leg in enumerate(x.legs))
    return (batch.connections == (binding.connection,) and batch.accounts == binding.accounts
            and batch.aliases == binding.aliases and batch.instruments == binding.instruments
            and batch.issuers == binding.issuers and set(actual_facts) == set(binding.facts)
            and set(actual_snapshots) == set(binding.snapshots) and set(actual_roles) == set(binding.leg_roles)
            and canonical(primitive(project_references(batch))) == canonical(primitive(binding.reference_graph)))


def validate_transport(raw, context, envelope):
    """Validate inert bytes against saved trusted context, never load an adapter."""
    # Size/depth priority is raw, context, envelope before envelope schema admission.
    for data, maximum, path in ((raw, MAX_RAW, "$.raw"), (context, MAX_CONTEXT, "$.context"),
                                (envelope, MAX_ENVELOPE, "$.envelope")):
        if type(data) is not bytes:
            return _blocked("source_transport_invalid" if path == "$.envelope" else "source_context_invalid", path)
        if len(data) > maximum:
            return _blocked("source_transport_limit", path)
        if path != "$.raw" and data:
            try:
                load_json(data, limit=maximum)
            except ContractError as error:
                if error.code == "source_transport_limit":
                    return _blocked("source_transport_limit", path)
    admitted = _envelope(envelope)
    if type(admitted) is TransportOutcomeV1:
        return admitted
    try:
        saved = decode_context(context)
    except ContractError:
        return _blocked("source_context_invalid", "$.context")
    for name, wanted in (("envelope_version", 1), ("domain_contract_version", 1),
                         ("parser_api_version", saved.installation_descriptor.parser_api_version)):
        if admitted[name] != wanted:
            return _blocked("source_version_unsupported", "$.envelope." + name)
    for name, wanted in (("transport", saved.transport),
                         ("payload_kind", saved.installation_descriptor.payload_kind),
                         ("format_version", saved.format_version)):
        if admitted[name] != wanted:
            return _blocked("source_format_unsupported", "$.envelope." + name)
    expected = fingerprint(saved)
    for name in FINGERPRINT_FIELDS:
        if admitted["fingerprint"][name] != expected[name]:
            return _blocked("source_context_mismatch", "$.envelope.fingerprint." + name)
    # Stage7 never inspects payload UTF-8/JSON/schema. Hash precedence is deliberate.
    encoded = admitted["payload_base64"]
    if len(encoded) > 5592408:
        return _blocked("source_transport_limit", "$.envelope.payload_base64")
    try:
        payload = base64.b64decode(encoded, validate=True)
        if not payload or base64.b64encode(payload).decode("ascii") != encoded:
            raise ValueError()
    except (ValueError, binascii.Error, UnicodeError):
        return _blocked("source_payload_invalid", "$.envelope.payload_base64")
    if len(payload) > MAX_PAYLOAD:
        return _blocked("source_transport_limit", "$.envelope.payload_base64")
    if hashlib.sha256(payload).hexdigest() != admitted["payload_sha256"]:
        return _blocked("source_payload_digest_mismatch", "$.envelope.payload_sha256")
    try:
        if admitted["payload_kind"] == "parser_v2":
            try:
                parsed = parser.decode_batch(payload, raw)
            except (ValueError, TypeError, AttributeError):
                return _blocked("source_payload_invalid", "$.envelope.payload_base64")
            if canonical(primitive(parsed.evidence.context)) != canonical(primitive(saved.parse_context.value)):
                return _blocked("source_reference_mismatch", "$.envelope.payload_base64")
            from .compatibility_v1 import parser_provenance
            expected=saved.expected_provenance
            if (parsed.adapter.provider_id!=expected.provider or parsed.adapter.adapter_id!=expected.adapter
                    or parsed.adapter.adapter_version!=expected.adapter_version or parsed.export_version!=expected.export_version
                    or hashlib.sha256(raw).hexdigest()!=expected.raw_sha256
                    or hashlib.sha256(payload).hexdigest()!=expected.canonical_sha256):
                return _blocked("source_reference_mismatch", "$.envelope.payload_base64")
            projected=parser_provenance(raw,payload,parsed,saved)
            if projected is not None and projected!=expected:
                return _blocked("source_reference_mismatch", "$.envelope.payload_base64")
            result = bridge.bridge_parser_v2(raw, payload, saved.binding_context.value)
            if result.blockers:
                return _domain_blocked(result.blockers)
            batch, domain_bytes = result.candidate, result.candidate_bytes
        else:
            batch = decode_domain_v1(payload)
            domain_bytes = payload
        if not _check_references(batch, saved):
            return _blocked("source_reference_mismatch", "$.envelope.payload_base64")
        if hashlib.sha256(raw).hexdigest() != saved.expected_provenance.raw_sha256:
            return _blocked("source_reference_mismatch", "$.envelope.payload_base64")
        return TransportOutcomeV1("VALID_SHAPE", base64.b64encode(domain_bytes).decode("ascii"), ())
    except DomainValidationError as error:
        return _domain_blocked((error.diagnostic,))
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError, KeyError):
        return _blocked("source_payload_invalid", "$.envelope.payload_base64")
