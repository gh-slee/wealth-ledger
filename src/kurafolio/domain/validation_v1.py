"""Pure, bounded, closed domain-v1 validation and canonical UTF-8 codec."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
import json
import re
import types
from typing import Literal, Union, get_args, get_origin, get_type_hints

from . import canonical_v1 as c

_CODES = frozenset("""domain_version_unsupported domain_profile_unsupported
 domain_schema_unknown_field domain_schema_missing_field domain_duplicate_key
 domain_invalid_type domain_reference_out_of_scope domain_mapping_required
 domain_alias_conflict domain_instrument_identity_ambiguous domain_decimal_invalid
 domain_decimal_nonfinite domain_decimal_token_limit domain_decimal_envelope
 domain_subsatoshi domain_time_invalid domain_time_precision_unsupported
 domain_revision_invalid domain_coverage_mismatch domain_unsupported_semantics
 domain_resource_limit bridge_legacy_invalid bridge_mapping_required
 bridge_precision_unrepresentable bridge_time_unrepresentable
 bridge_semantics_unrepresentable""".split())


@dataclass(frozen=True, slots=True)
class DomainDiagnosticV1:
    code: str
    field: str
    ordinal: int | None = None


class DomainValidationError(ValueError):
    """Only schema-owned paths and fixed codes are exposed to callers."""
    def __init__(self, code: str, field: str = "$", ordinal: int | None = None):
        if code not in _CODES:
            code = "domain_invalid_type"
        if not re.fullmatch(r"\$(?:\.[a-z_]+|\[[0-9]{1,5}\])*", field) or len(field) > 210:
            field = "$"
        if type(ordinal) is not int or not 0 <= ordinal < c.MAX_COLLECTION:
            ordinal = None
        self.diagnostic = DomainDiagnosticV1(code, field, ordinal)
        super().__init__(f"{code}: {field}")


def _fail(code, path="$", ordinal=None):
    raise DomainValidationError(code, path, ordinal)


_SCHEMA = (
    c.ScopedIdV1, c.LegacyRecordRefV1, c.InstantV1, c.DateOnlyV1,
    c.LegacyDateTimeV1, c.PointV1, c.IntervalV1, c.DecimalTokenV1, c.MoneyV1,
    c.SourceSelectorV1, c.ExternalSourceRefV1, c.FactIdentityV1,
    c.FinancialAccountV1, c.SourceConnectionV1, c.AccountAliasV1, c.IssuerV1,
    c.IdentifierHintV1, c.InstrumentV1, c.InstrumentScopeV1, c.CoverageV1,
    c.SupportV1, c.PositionItemV1, c.PositionSnapshotV1, c.ActivityLegV1,
    c.FeeV1, c.SourceCashFlowV1, c.ActivityEventV1, c.ProvenanceV1,
    c.DomainBatchV1,
)
_HINTS = {cls: get_type_hints(cls) for cls in _SCHEMA}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SHA = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)(?:\.([0-9]+))?", re.ASCII)
_CURRENCY = re.compile(r"[A-Z]{3}", re.ASCII)
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_ZONE = re.compile(r"(?:UTC|[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)+)", re.ASCII)
_LEGACY_FIELDS = frozenset(("", "context.evidence_at", "lifecycle.created_at", "lifecycle.completed_at", "lifecycle.sent_at",
    "adapter", "export_version", "evidence", "accounts", "membership", "snapshots", "coverage", "records", "raw_sha256", "context", "effective_at", "id_policy", "mappings", "diagnostics", "source_fields", "key", "account_type", "label", "role", "masked_identifier", "scope_id", "revision", "status", "basis", "supersedes_revision", "kind", "account", "start", "end", "observation_id", "source_id", "as_of", "asset", "name", "instrument_type", "exchange", "quantity", "market_value", "unit_price", "cost_native", "cost_cad", "unrealized", "revision_reason", "occurred_at", "type", "direction", "amount", "boundary", "transfer_reference", "counterpart", "cash_leg_of", "lifecycle", "legs", "acquisition_cost", "acquisition_cost_cad", "fees"))


def _json_string(value):
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except UnicodeError:
        _fail("domain_invalid_type")


def _charge(budget, count, path):
    budget[0] += count
    if budget[0] > c.MAX_CANONICAL_BYTES:
        _fail("domain_resource_limit", path)


def _resource_admit(value, budget, depth=0):
    """Admission budgets run before schema/type checks, in bounded traversal."""
    if depth > c.MAX_DEPTH:
        _fail("domain_resource_limit")
    if type(value) in _HINTS:
        names=fields(value)
        _charge(budget,2+max(0,len(names)-1),"$")
        for item in names:
            _charge(budget,len(_json_string(item.name))+1,"$")
            _resource_admit(getattr(value,item.name),budget,depth+1)
    elif type(value) in (tuple,list):
        if len(value)>c.MAX_COLLECTION:
            _fail("domain_resource_limit")
        _charge(budget,2+max(0,len(value)-1),"$")
        for item in value:
            _resource_admit(item,budget,depth+1)
    elif type(value) is dict:
        if len(value)>c.MAX_COLLECTION:
            _fail("domain_resource_limit")
        _charge(budget,2+max(0,len(value)-1),"$")
        for key,item in value.items():
            _resource_admit(key,budget,depth+1)
            _charge(budget,1,"$")
            _resource_admit(item,budget,depth+1)
    elif type(value) is str:
        if len(value)>c.MAX_TEXT:
            _fail("domain_resource_limit")
        _charge(budget,len(_json_string(value)),"$")
    elif type(value) is int:
        if not -c.MAX_COLLECTION<=value<=c.MAX_COLLECTION:
            _fail("domain_resource_limit")
        _charge(budget,len(_json_string(value)),"$")
    elif value is None or type(value) is bool:
        _charge(budget,len(_json_string(value)),"$")
    # Unknown Python objects and forbidden JSON numbers are rejected by the
    # closed structural pass; never call their conversion or traversal methods.


def _admit(expected, value, path, budget, depth=0):
    """Check exact Python types and cumulative wire size without copying the tree."""
    if depth > c.MAX_DEPTH:
        _fail("domain_resource_limit", path)
    origin, args = get_origin(expected), get_args(expected)
    if origin in (types.UnionType, Union):
        for choice in args:
            if type(value) is choice or get_origin(choice) is Literal and any(type(value) is type(v) and value == v for v in get_args(choice)) or get_origin(choice) is tuple and type(value) is tuple:
                return _admit(choice, value, path, budget, depth)
        _fail("domain_invalid_type", path)
    if expected in _HINTS:
        if type(value) is not expected:
            _fail("domain_invalid_type", path)
        names = fields(expected)
        _charge(budget, 2 + max(0, len(names) - 1), path)
        for field in names:
            _charge(budget, len(_json_string(field.name)) + 1, path)
            _admit(_HINTS[expected][field.name], getattr(value, field.name), path + "." + field.name, budget, depth + 1)
    elif origin is tuple:
        if type(value) is not tuple:
            _fail("domain_invalid_type", path)
        if len(value) > c.MAX_COLLECTION:
            _fail("domain_resource_limit", path)
        _charge(budget, 2 + max(0, len(value) - 1), path)
        for index, item in enumerate(value):
            _admit(args[0], item, f"{path}[{index}]", budget, depth + 1)
    elif origin is Literal:
        if not any(type(value) is type(choice) and value == choice for choice in args):
            _fail("domain_invalid_type", path)
        _charge(budget, len(_json_string(value)), path)
    elif expected is type(None):
        if value is not None:
            _fail("domain_invalid_type", path)
        _charge(budget, 4, path)
    elif expected in (str, int, bool):
        if type(value) is not expected:
            _fail("domain_invalid_type", path)
        if expected is str and len(value) > c.MAX_TEXT or expected is int and not -c.MAX_COLLECTION <= value <= c.MAX_COLLECTION:
            _fail("domain_resource_limit", path)
        _charge(budget, len(_json_string(value)), path)
    else:
        _fail("domain_invalid_type", path)


def _walk(value, path="$"):
    yield value, path
    if type(value) in _HINTS:
        for field in fields(value):
            yield from _walk(getattr(value, field.name), path + "." + field.name)
    elif type(value) is tuple:
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _uuid(value, path):
    if not _UUID.fullmatch(value) or value == "00000000-0000-0000-0000-000000000000":
        _fail("domain_invalid_type", path)


def _text(value, path, *, empty=False):
    if (not empty and not value.strip()) or any(ord(ch) < 32 for ch in value):
        _fail("domain_invalid_type", path)


def decimal_parts_v1(value: c.DecimalTokenV1, path="$"):
    """Lexical coefficient analysis, with no ambient Decimal operations."""
    if type(value) is not c.DecimalTokenV1 or type(value.token) is not str:
        _fail("domain_invalid_type", path)
    token = value.token
    if len(token) > c.MAX_DECIMAL_TOKEN:
        _fail("domain_decimal_token_limit", path)
    if token.lstrip("-") in {"NaN", "sNaN", "Infinity", "inf"}:
        _fail("domain_decimal_nonfinite", path)
    match = _DECIMAL.fullmatch(token)
    if not match:
        _fail("domain_decimal_invalid", path)
    integer, fraction = match.group(1), match.group(2) or ""
    significant = (integer + fraction).lstrip("0").rstrip("0")
    if len(significant) > 38 or len(fraction.rstrip("0")) > 24 or len(integer.lstrip("0")) > 38:
        _fail("domain_decimal_envelope", path)
    return integer, fraction, bool(significant), token.startswith("-")


def _sign(value):
    _, _, nonzero, negative = decimal_parts_v1(value)
    return (-1 if negative else 1) if nonzero else 0


def _quantity(value, instrument, path):
    _, fraction, _, _ = decimal_parts_v1(value, path)
    if instrument.kind in {"CRYPTO", "UNSUPPORTED"} and instrument.symbol is not None and instrument.symbol.upper() in {"BTC", "LBTC"} and any(ch != "0" for ch in fraction[8:]):
        _fail("domain_subsatoshi", path)


def _zone(zone, path):
    if zone is not None and (len(zone) > 255 or not _ZONE.fullmatch(zone) or any(part in {".", ".."} for part in zone.split("/"))):
        _fail("domain_time_invalid", path)


def _time(value, path):
    try:
        if type(value) is c.InstantV1:
            _zone(value.zone, path)
            match = _INSTANT.fullmatch(value.token)
            if not match:
                _fail("domain_time_invalid", path)
            fraction = match.group(1) or ""
            if len(fraction) > 6 or value.fractional_digits != len(fraction):
                _fail("domain_time_precision_unsupported", path)
            offset = match.group(2)
            if offset == "-00:00" or offset != "Z" and (int(offset[1:3]) > 23 or int(offset[4:]) > 59):
                _fail("domain_time_invalid", path)
            datetime.fromisoformat(value.token)
        elif type(value) is c.DateOnlyV1:
            _zone(value.zone, path)
            if not _DATE.fullmatch(value.token) or date.fromisoformat(value.token).isoformat() != value.token:
                _fail("domain_time_invalid", path)
        else:
            time_fields = {"evidence": {"effective_at", "context.evidence_at"}, "snapshots": {"as_of"}, "coverage": {"start", "end"}, "records": {"as_of", "occurred_at", "lifecycle.created_at", "lifecycle.completed_at", "lifecycle.sent_at"}}
            if value.archive.field not in time_fields.get(value.archive.collection, set()):
                _fail("domain_time_invalid", path)
            at = datetime.fromisoformat(value.token)
            if at.tzinfo is None or at.utcoffset() is None or at.isoformat() != value.token:
                _fail("domain_time_invalid", path)
    except DomainValidationError:
        raise
    except (ValueError, OverflowError):
        _fail("domain_time_invalid", path)


def _comparable(value):
    return ("date", value.zone, value.token) if type(value) is c.DateOnlyV1 else ("aware", datetime.fromisoformat(value.token))


def _same_time(a, b):
    return _comparable(a) == _comparable(b)


def _contains(selector, at):
    if type(selector) is c.PointV1:
        return _same_time(selector.at, at)
    if any(type(v) is c.DateOnlyV1 for v in (at, selector.start, selector.end)):
        return False
    start, end, actual = (_comparable(v)[1] for v in (selector.start, selector.end, at))
    return (start < actual or selector.start_inclusive and start == actual) and (actual < end or selector.end_inclusive and actual == end)


def _selector_identity(selector):
    return (selector.connection, selector.provider, selector.source_account_key, selector.kind, selector.source_id, selector.observation_id, selector.record_kind)


def _parent(source, parent, path):
    if parent is not None and (parent.selector.revision is None or parent.selector.revision == source.revision or _selector_identity(parent.selector) != _selector_identity(source)):
        _fail("domain_revision_invalid", path)


def _support(value, required, path):
    if len(set(value.reasons)) != len(value.reasons) or (value.classification == "supported_shape") != (not value.reasons) or not set(required) <= set(value.reasons):
        _fail("domain_unsupported_semantics", path)


def validate_domain_v1(batch: c.DomainBatchV1) -> None:
    """Admission/types, then references, numbers/times, then recognized semantics."""
    _resource_admit(batch, [0])
    _admit(c.DomainBatchV1, batch, "$", [0])
    if batch.contract_version != c.CONTRACT_VERSION:
        _fail("domain_version_unsupported", "$.contract_version")
    if batch.profile != c.DECIMAL_PROFILE:
        _fail("domain_profile_unsupported", "$.profile")
    _uuid(batch.tenant_id, "$.tenant_id"); _uuid(batch.portfolio_id, "$.portfolio_id")
    _text(batch.mapping_revision, "$.mapping_revision"); _text(batch.evidence_reference, "$.evidence_reference")
    scope = (batch.tenant_id, batch.portfolio_id)
    declarations = {}
    for name, kind in (("accounts", "account"), ("connections", "connection"), ("instruments", "instrument"), ("issuers", "issuer"), ("snapshots", "snapshot")):
        for index, item in enumerate(getattr(batch, name)):
            path = f"$.{name}[{index}].id"
            if item.id.kind != kind:
                _fail("domain_reference_out_of_scope", path)
            key = (kind, item.id.value)
            if key in declarations:
                _fail("domain_duplicate_key", path)
            declarations[key] = item
    snapshot_sources = set()
    for index, snapshot in enumerate(batch.snapshots):
        key = (snapshot.connection, snapshot.source_id, snapshot.revision)
        if key in snapshot_sources:
            _fail("domain_duplicate_key", f"$.snapshots[{index}]")
        snapshot_sources.add(key)
    fact_sources = set()
    for collection in (tuple(item for snapshot in batch.snapshots for item in snapshot.items), batch.activities):
        for fact in collection:
            if fact.identity.id.kind != "fact":
                _fail("domain_reference_out_of_scope")
            key = ("fact", fact.identity.id.value)
            source_key = _selector_identity(fact.identity.source) + (fact.identity.source.revision,)
            if key in declarations or source_key in fact_sources:
                _fail("domain_duplicate_key")
            declarations[key] = fact
            fact_sources.add(source_key)
    # Source selectors keep the connection namespace as well as the old key.
    for value, path in _walk(batch):
        if type(value) is c.ScopedIdV1:
            _uuid(value.tenant_id, path); _uuid(value.portfolio_id, path); _uuid(value.value, path)
            if (value.tenant_id, value.portfolio_id) != scope or (value.kind, value.value) not in declarations:
                _fail("domain_reference_out_of_scope", path)
        elif type(value) is c.ExternalSourceRefV1:
            if (value.tenant_id, value.portfolio_id) != scope:
                _fail("domain_reference_out_of_scope", path)
        elif type(value) is c.LegacyRecordRefV1:
            if not _SHA.fullmatch(value.canonical_sha256) or value.canonical_sha256 != batch.provenance.canonical_sha256 or value.field not in _LEGACY_FIELDS:
                _fail("domain_reference_out_of_scope", path)
            if value.collection in {"accounts", "snapshots", "coverage", "records"}:
                if value.ordinal is None or not 0 <= value.ordinal < c.MAX_COLLECTION:
                    _fail("domain_reference_out_of_scope", path)
            elif value.ordinal is not None:
                _fail("domain_reference_out_of_scope", path)
    def resolve(ref, kind, path):
        if ref.kind != kind:
            _fail("domain_reference_out_of_scope", path)
        return declarations[(kind, ref.value)]
    aliases = {}
    for index, alias in enumerate(batch.aliases):
        path = f"$.aliases[{index}]"
        connection = resolve(alias.connection, "connection", path)
        resolve(alias.account, "account", path)
        if alias.provider != connection.provider or alias.mapping_revision != batch.mapping_revision:
            _fail("domain_reference_out_of_scope", path)
        _text(alias.source_account_key, path); _text(alias.evidence_reference, path)
        key = (alias.connection, alias.provider, alias.source_account_key, alias.mapping_revision)
        if key in aliases:
            _fail("domain_alias_conflict" if aliases[key] != alias.account else "domain_duplicate_key", path)
        aliases[key] = alias.account
    def source_account(source, path):
        connection = resolve(source.connection, "connection", path)
        if source.provider != connection.provider:
            _fail("domain_reference_out_of_scope", path)
        key = (source.connection, source.provider, source.source_account_key, batch.mapping_revision)
        if key not in aliases:
            _fail("domain_mapping_required", path)
        return aliases[key]
    for value, path in _walk(batch):
        if type(value) is c.SourceSelectorV1:
            connection = resolve(value.connection, "connection", path)
            _text(value.provider, path); _text(value.source_id, path)
            if value.provider != connection.provider:
                _fail("domain_reference_out_of_scope", path)
            if value.source_account_key is not None:
                _text(value.source_account_key, path)
                source_account(value, path)
            if value.revision is not None:
                _text(value.revision, path)
            if value.kind in {"holdings", "cash_flows", "crypto_transactions", "activity"} and (value.source_account_key is None or value.record_kind is not None):
                _fail("domain_revision_invalid", path)
            if value.kind == "coverage" and (value.record_kind is None or value.source_account_key is None):
                _fail("domain_revision_invalid", path)
            if value.kind in {"snapshot", "membership"} and (value.source_account_key is not None or value.record_kind is not None or value.observation_id):
                _fail("domain_revision_invalid", path)
        elif type(value) in (c.PositionItemV1, c.ActivityLegV1, c.FeeV1):
            resolve(value.account, "account", path); resolve(value.instrument, "instrument", path)
        elif type(value) is c.CoverageV1:
            connection = resolve(value.connection, "connection", path)
            resolve(value.account, "account", path)
            _text(value.source_account_key, path + ".source_account_key")
            selector = c.SourceSelectorV1(value.connection, connection.provider, value.source_account_key, "coverage", value.scope_id, value.observation_id, value.revision, value.kind)
            if source_account(selector, path) != value.account:
                _fail("domain_reference_out_of_scope", path)
            for ref in value.instrument_scope.instruments:
                resolve(ref, "instrument", path)
        elif type(value) is c.InstrumentV1 and value.issuer is not None:
            resolve(value.issuer, "issuer", path)
    for snapshot in batch.snapshots:
        resolve(snapshot.connection, "connection", "$.snapshots")
        for account in snapshot.accounts:
            resolve(account, "account", "$.snapshots")
        for item in snapshot.items:
            if source_account(item.identity.source, "$.snapshots") != item.account:
                _fail("domain_reference_out_of_scope", "$.snapshots")
    for event in batch.activities:
        source_account(event.identity.source, "$.activities")
    # Numeric admission precedes semantic sign rules, including unsupported facts.
    for value, path in _walk(batch):
        if type(value) is c.DecimalTokenV1:
            decimal_parts_v1(value, path)
        elif type(value) is c.MoneyV1:
            if not _CURRENCY.fullmatch(value.currency):
                _fail("domain_invalid_type", path)
        elif type(value) in (c.InstantV1, c.DateOnlyV1, c.LegacyDateTimeV1):
            _time(value, path)
        elif type(value) in (c.FinancialAccountV1, c.IssuerV1):
            _text(value.label, path)
            if type(value) is c.FinancialAccountV1:
                _text(value.category, path)
        elif type(value) is c.SourceConnectionV1:
            if not re.fullmatch(r"[a-z][a-z0-9_.-]*", value.provider):
                _fail("domain_invalid_type", path)
        elif type(value) is c.ProvenanceV1:
            if not _SHA.fullmatch(value.raw_sha256) or value.canonical_sha256 is not None and not _SHA.fullmatch(value.canonical_sha256):
                _fail("domain_invalid_type", path)
        if type(value) in (c.PositionItemV1, c.ActivityLegV1, c.FeeV1):
            _quantity(value.quantity, declarations[("instrument", value.instrument.value)], path)
    for index, instrument in enumerate(batch.instruments):
        path = f"$.instruments[{index}]"
        _text(instrument.source_descriptor, path); _text(instrument.evidence_reference, path)
        for text in (instrument.ticker, instrument.symbol, instrument.network, instrument.settlement_identity):
            if text is not None:
                _text(text, path)
        if instrument.currency is not None and not _CURRENCY.fullmatch(instrument.currency):
            _fail("domain_invalid_type", path)
        if instrument.kind == "SECURITY":
            if instrument.mic is None or not re.fullmatch(r"[A-Z0-9]{4}", instrument.mic) or not instrument.ticker or instrument.currency is None or any(v is not None for v in (instrument.symbol, instrument.network, instrument.settlement_identity)):
                _fail("domain_instrument_identity_ambiguous", path)
        elif instrument.kind == "CASH":
            if instrument.currency is None or any(v is not None for v in (instrument.ticker, instrument.mic, instrument.symbol, instrument.network, instrument.settlement_identity)):
                _fail("domain_instrument_identity_ambiguous", path)
        elif instrument.kind == "CRYPTO":
            if not instrument.symbol or not instrument.network or not instrument.settlement_identity or instrument.ticker is not None or instrument.mic is not None:
                _fail("domain_instrument_identity_ambiguous", path)
    for value, path in _walk(batch):
        if type(value) is c.IntervalV1:
            if type(value.start) is c.DateOnlyV1 or type(value.end) is c.DateOnlyV1 or _comparable(value.end)[1] < _comparable(value.start)[1]:
                _fail("domain_coverage_mismatch", path)
        elif type(value) is c.FactIdentityV1:
            if value.source.revision is None or value.source.kind not in {"holdings", "cash_flows", "crypto_transactions", "activity"}:
                _fail("domain_revision_invalid", path)
            if (value.change == "original") != (value.parent is None) or value.change != "original" and value.reason is None and value.legacy is None:
                _fail("domain_revision_invalid", path)
            if value.reason is not None:
                _text(value.reason, path)
            _parent(value.source, value.parent, path)
        elif type(value) is c.FeeV1 and _sign(value.quantity) < 0:
            _fail("domain_unsupported_semantics", path)
    coverage_keys = set()
    for index, coverage in enumerate(batch.coverage):
        path = f"$.coverage[{index}]"
        key = (coverage.connection, coverage.source_account_key, coverage.account, coverage.kind, coverage.scope_id, coverage.observation_id, coverage.revision)
        if key in coverage_keys:
            _fail("domain_duplicate_key", path)
        coverage_keys.add(key)
        if coverage.kind == "holdings" and (not coverage.observation_id or not any(snapshot.connection == coverage.connection and snapshot.source_id == coverage.observation_id and coverage.account in snapshot.accounts for snapshot in batch.snapshots)):
            _fail("domain_coverage_mismatch", path)
        _text(coverage.scope_id, path); _text(coverage.revision, path); _text(coverage.basis, path)
        scope_value = coverage.instrument_scope
        if (scope_value.tag == "all" and (scope_value.instruments or scope_value.category is not None) or scope_value.tag == "instruments" and (not scope_value.instruments or scope_value.category is not None) or scope_value.tag == "category" and (scope_value.instruments or scope_value.category is None) or len(set(scope_value.instruments)) != len(scope_value.instruments)):
            _fail("domain_coverage_mismatch", path)
        if coverage.parent is not None:
            selector = coverage.parent.selector
            if selector.connection != coverage.connection or selector.source_account_key != coverage.source_account_key or selector.kind != "coverage" or selector.source_id != coverage.scope_id or selector.record_kind != coverage.kind or selector.observation_id != coverage.observation_id or selector.revision in {None, coverage.revision} or source_account(selector, path) != coverage.account:
                _fail("domain_revision_invalid", path)
    def covered(identity, account, instrument, at, scopes=None):
        for cv in batch.coverage if scopes is None else scopes:
            if cv.connection != identity.source.connection or cv.source_account_key != identity.source.source_account_key or cv.account != account or cv.kind != identity.source.kind or cv.observation_id != identity.source.observation_id or not _contains(cv.time, at):
                continue
            inscope = cv.instrument_scope
            if instrument is None or inscope.tag == "all" or inscope.tag == "instruments" and instrument in inscope.instruments or inscope.tag == "category" and declarations[("instrument", instrument.value)].kind == inscope.category:
                return True
        return False
    for index, snapshot in enumerate(batch.snapshots):
        path = f"$.snapshots[{index}]"
        _text(snapshot.source_id, path); _text(snapshot.revision, path)
        if not snapshot.accounts or len(set(snapshot.accounts)) != len(snapshot.accounts) or len(set(snapshot.coverage)) != len(snapshot.coverage):
            _fail("domain_coverage_mismatch", path)
        selected_scopes = []
        for reference in snapshot.coverage:
            selector = reference.selector
            account = source_account(selector, path)
            matches = tuple(cv for cv in batch.coverage if cv.connection == selector.connection and cv.source_account_key == selector.source_account_key and cv.account == account and cv.kind == selector.record_kind and cv.scope_id == selector.source_id and cv.revision == selector.revision and cv.observation_id == selector.observation_id)
            if selector.kind != "coverage" or selector.record_kind != "holdings" or selector.connection != snapshot.connection or selector.observation_id != snapshot.source_id or account not in snapshot.accounts or len(matches) != 1 or not _contains(matches[0].time, snapshot.as_of):
                _fail("domain_coverage_mismatch", path)
            selected_scopes.append(matches[0])
        if any(not any(source_account(reference.selector, path) == account for reference in snapshot.coverage) for account in snapshot.accounts):
            _fail("domain_coverage_mismatch", path)
        if snapshot.parent is not None and (snapshot.parent.selector.connection != snapshot.connection or snapshot.parent.selector.kind != "snapshot" or snapshot.parent.selector.source_id != snapshot.source_id or snapshot.parent.selector.revision in {None, snapshot.revision}):
            _fail("domain_revision_invalid", path)
        for item in snapshot.items:
            ins = declarations[("instrument", item.instrument.value)]
            if item.identity.source.connection != snapshot.connection or item.identity.source.kind != "holdings" or item.identity.source.observation_id != snapshot.source_id or item.identity.source.revision != snapshot.revision or item.account not in snapshot.accounts or not _same_time(item.as_of, snapshot.as_of) or not covered(item.identity, item.account, item.instrument, item.as_of, selected_scopes):
                _fail("domain_coverage_mismatch", path)
            if item.identity.change == "void":
                _fail("domain_revision_invalid", path)
            required = []
            if _sign(item.quantity) < 0:
                required.append("signed_position")
            if ins.kind == "UNSUPPORTED":
                required.append("unsupported_instrument")
            _support(item.support, required, path)
            for money in (item.market_value, item.unit_price, item.cost_native, item.unrealized):
                if money is not None and ins.currency is not None and money.currency != ins.currency:
                    _fail("domain_unsupported_semantics", path)
            if item.cost_cad is not None and item.cost_cad.currency != "CAD":
                _fail("domain_unsupported_semantics", path)
    recognized = {"purchase": "BUY", "buy": "BUY", "sale": "SELL", "sell": "SELL", "transfer": "TRANSFER", "fee": "FEE", "income": "INCOME", "deposit": "FUNDING", "withdrawal": "FUNDING", "funding": "FUNDING", "corporate_action": "CORPORATE_ACTION"}
    for index, event in enumerate(batch.activities):
        path = f"$.activities[{index}]"
        _text(event.source_kind, path); _text(event.source_status, path)
        external_links=event.economic_references
        if event.cash_flow is not None:
            external_links += tuple(ref for ref in (event.cash_flow.counterpart,event.cash_flow.cash_leg_of) if ref is not None)
        if any(ref.selector.kind not in {"cash_flows", "crypto_transactions", "activity"} or ref.selector.revision is None and event.identity.legacy is None for ref in external_links):
            _fail("domain_revision_invalid", path)
        normalized_source_kind = event.source_kind.lower()
        if normalized_source_kind not in recognized and event.kind != "UNSUPPORTED":
            _fail("domain_unsupported_semantics", path)
        if normalized_source_kind in recognized and event.kind != recognized[normalized_source_kind]:
            _fail("domain_unsupported_semantics", path)
        if event.source_status not in {"completed", "pending", "cancelled"} and event.status != "unsupported":
            _fail("domain_unsupported_semantics", path)
        if event.source_status in {"completed", "pending", "cancelled"} and event.status != event.source_status:
            _fail("domain_unsupported_semantics", path)
        if event.identity.change == "void" and event.status != "cancelled":
            _fail("domain_revision_invalid", path)
        if event.acquisition_cost_cad is not None and event.acquisition_cost_cad.currency != "CAD":
            _fail("domain_unsupported_semantics", path)
        required = []
        if event.kind in {"UNSUPPORTED", "CORPORATE_ACTION"}:
            required.append("unsupported_activity")
        if event.status == "unsupported":
            required.append("unsupported_status")
        if (any(declarations[("instrument", leg.instrument.value)].kind == "UNSUPPORTED" for leg in event.legs)
                or any(declarations[("instrument", fee.instrument.value)].kind == "UNSUPPORTED" for fee in event.fees or ())):
            required.append("unsupported_instrument")
        _support(event.support, required, path)
        if event.kind == "BUY":
            acquisitions = tuple(leg for leg in event.legs if leg.role == "ACQUISITION")
            if not acquisitions or any(_sign(leg.quantity) <= 0 or declarations[("instrument", leg.instrument.value)].kind not in {"CRYPTO", "SECURITY"} for leg in acquisitions):
                _fail("domain_unsupported_semantics", path)
        is_cash = event.identity.source.kind == "cash_flows" or event.kind == "FUNDING"
        if is_cash != (event.cash_flow is not None):
            _fail("domain_unsupported_semantics", path)
        owner_account = source_account(event.identity.source, path)
        if event.cash_flow is not None:
            cash = event.cash_flow
            if _sign(cash.cash_amount.amount) <= 0 or event.legs or normalized_source_kind in {"deposit", "income"} and cash.direction != "in" or normalized_source_kind in {"withdrawal", "fee"} and cash.direction != "out":
                _fail("domain_unsupported_semantics", path)
            if cash.cash_leg_of is not None and (cash.cash_leg_of.selector.kind != "crypto_transactions" or cash.boundary != "internal"):
                _fail("domain_unsupported_semantics", path)
            if not covered(event.identity, owner_account, None, event.event_time):
                _fail("domain_coverage_mismatch", path)
        else:
            if not event.legs:
                _fail("domain_unsupported_semantics", path)
            for leg in event.legs:
                if not covered(event.identity, owner_account, leg.instrument, event.event_time):
                    _fail("domain_coverage_mismatch", path)


def _wire(value):
    if type(value) in _HINTS:
        return {f.name: _wire(getattr(value, f.name)) for f in fields(value)}
    if type(value) is tuple:
        return [_wire(item) for item in value]
    return value


def encode_domain_v1(batch: c.DomainBatchV1) -> bytes:
    validate_domain_v1(batch)
    output = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(_wire(batch)):
        encoded = chunk.encode("utf-8")
        if len(output) + len(encoded) > c.MAX_CANONICAL_BYTES:
            _fail("domain_resource_limit")
        output.extend(encoded)
    return bytes(output)


def _json_depth(data):
    depth, quoted, escaped = 0, False, False
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
            depth += 1
            if depth > c.MAX_DEPTH:
                _fail("domain_resource_limit")
        elif byte in (93, 125):
            depth -= 1


def _decode(expected, value, path="$"):
    origin, args = get_origin(expected), get_args(expected)
    if origin in (types.UnionType, Union):
        if value is None and type(None) in args:
            return None
        choices = [choice for choice in args if choice is not type(None)]
        if len(choices) == 1:
            return _decode(choices[0], value, path)
        if type(value) is dict and "tag" in value:
            for choice in choices:
                if choice in _HINTS and value["tag"] in get_args(_HINTS[choice].get("tag")):
                    return _decode(choice, value, path)
        _fail("domain_invalid_type", path)
    if expected in _HINTS:
        if type(value) is not dict:
            _fail("domain_invalid_type", path)
        names = tuple(field.name for field in fields(expected))
        if set(value) - set(names):
            _fail("domain_schema_unknown_field", path)
        for name in names:
            if name not in value:
                _fail("domain_schema_missing_field", path + "." + name)
        return expected(**{name: _decode(_HINTS[expected][name], value[name], path + "." + name) for name in names})
    if origin is tuple:
        if type(value) is not list:
            _fail("domain_invalid_type", path)
        if len(value) > c.MAX_COLLECTION:
            _fail("domain_resource_limit", path)
        return tuple(_decode(args[0], item, f"{path}[{i}]") for i, item in enumerate(value))
    if origin is Literal:
        if not any(type(value) is type(choice) and value == choice for choice in args):
            _fail("domain_invalid_type", path)
        return value
    if expected is type(None):
        if value is not None:
            _fail("domain_invalid_type", path)
        return None
    if expected not in (str, int, bool) or type(value) is not expected:
        _fail("domain_invalid_type", path)
    if expected is str and len(value) > c.MAX_TEXT:
        _fail("domain_resource_limit", path)
    return value


def decode_domain_v1(data: bytes) -> c.DomainBatchV1:
    if type(data) is not bytes:
        _fail("domain_invalid_type")
    if not data or len(data) > c.MAX_CANONICAL_BYTES:
        _fail("domain_resource_limit")
    _json_depth(data)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("domain_duplicate_key")
            result[key] = value
        return result
    def integer(token):
        if len(token) > 6:
            _fail("domain_resource_limit")
        return int(token)
    forbidden_number = object()
    def forbidden(_):
        return forbidden_number
    try:
        decoded = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_int=integer, parse_float=forbidden, parse_constant=forbidden)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("domain_invalid_type")
    _resource_admit(decoded, [0])
    batch = _decode(c.DomainBatchV1, decoded)
    if encode_domain_v1(batch) != data:
        _fail("domain_invalid_type")
    return batch
