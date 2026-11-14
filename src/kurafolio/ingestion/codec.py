"""Bounded closed JSON and local-graph validation for ingestion evidence.

Admission here does not establish current database authority or accept facts.
Those checks belong to the scoped transaction after an exact review is confirmed.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
import uuid

from ..domain.canonical_v1 import DecimalTokenV1
from ..domain.validation_v1 import DomainValidationError, decimal_parts_v1
from .contracts import (CORE_NAMES, IngestionError, MAX_COUNTER,
                        MAX_MINIMAL, MAX_PLAN, MAX_ROWS, definition)


def encode(value):
    """Canonical UTF-8 without float coercion, duplicate keys or a trailing LF."""
    try:
        _primitive(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except IngestionError:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise IngestionError() from None


def _primitive(value, depth=0):
    if depth > 32:
        raise IngestionError('import_limit')
    if type(value) in (str, int, bool, type(None)):
        return
    if type(value) is dict:
        if len(value) > 131072 or any(type(key) is not str for key in value):
            raise IngestionError()
        for item in value.values():
            _primitive(item, depth + 1)
    elif type(value) is list:
        if len(value) > 131072:
            raise IngestionError('import_limit')
        for item in value:
            _primitive(item, depth + 1)
    else:
        raise IngestionError()


def sha256(data):
    if type(data) is not bytes:
        raise IngestionError()
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha256(encode(value))


def _reference(ref, namespace):
    prefix, name = ref.split('#/$defs/', 1)
    if prefix:
        namespace = {'codec-schema.json': 'core', 'wire-contracts.json': 'wire',
                     'frozen-shapes.json': 'frozen'}.get(prefix)
        if namespace is None:
            raise IngestionError()
    return name, namespace


def _shape(value, schema, namespace, path):
    if '$ref' in schema:
        name, ns = _reference(schema['$ref'], namespace)
        _shape(value, definition(name, ns), ns, path)
        if ns == 'core':
            _scalar(name, value, path)
        return
    if 'anyOf' in schema:
        for option in schema['anyOf']:
            try:
                _shape(value, option, namespace, path)
                return
            except IngestionError:
                pass
        raise IngestionError('import_invalid', path)
    if 'enum' in schema and not any(type(value) is type(x) and value == x
                                    for x in schema['enum']):
        raise IngestionError('import_invalid', path)
    if 'const' in schema and (type(value) is not type(schema['const'])
                              or value != schema['const']):
        raise IngestionError('import_invalid', path)
    kind = schema.get('type')
    expected = {'object': dict, 'array': list, 'string': str, 'integer': int,
                'boolean': bool, 'null': type(None)}
    if kind is not None and type(value) is not expected[kind]:
        raise IngestionError('import_invalid', path)
    if kind == 'object':
        props = schema['properties']
        if not set(schema['required']) <= value.keys() or (
                schema.get('additionalProperties') is False and value.keys() - props.keys()):
            raise IngestionError('import_invalid', path)
        for key in props:
            if key in value:
                _shape(value[key], props[key], namespace, path + '.' + key)
    elif kind == 'array':
        if len(value) > schema.get('maxItems', 50000):
            raise IngestionError('import_limit', path)
        if len(value) < schema.get('minItems', 0):
            raise IngestionError('import_invalid', path)
        for item in value:
            _shape(item, schema['items'], namespace, path + '[]')
    elif kind == 'string':
        if len(value) > schema.get('maxLength', 4096):
            raise IngestionError('import_limit', path)
        if 'pattern' in schema and re.fullmatch(schema['pattern'], value, re.ASCII) is None:
            raise IngestionError('import_invalid', path)
        if any(ord(ch) < 32 for ch in value):
            raise IngestionError('import_invalid', path)
    elif kind == 'integer':
        if not schema.get('minimum', value) <= value <= schema.get('maximum', value):
            raise IngestionError('import_invalid', path)


def _scalar(name, value, path):
    try:
        if name == 'UUID':
            parsed = uuid.UUID(value)
            if not parsed.int or str(parsed) != value:
                raise ValueError()
        elif name == 'Counter':
            if int(value) > MAX_COUNTER:
                raise ValueError()
        elif name == 'Decimal':
            decimal_parts_v1(DecimalTokenV1(value))
        elif name in {'Instant', 'Date', 'LegacyTime'}:
            _time(value, path)
        elif name in {'Claim', 'SourceKey'}:
            _claim(value, path)
        elif name in {'InstrumentScope', 'CanonicalInstrumentScope'}:
            key = 'asset_local_ids' if name == 'InstrumentScope' else 'instrument_ids'
            ids = value[key]
            if len(set(ids)) != len(ids) or ids != sorted(ids):
                raise ValueError()
            if value['tag'] == 'all' and (ids or value['category'] is not None):
                raise ValueError()
            if value['tag'] == 'category' and (ids or value['category'] is None):
                raise ValueError()
            if value['tag'] == 'instruments' and (not ids or value['category'] is not None):
                raise ValueError()
        elif name == 'Identity':
            original = value['change'] == 'original'
            if original != (value['parent'] is None and value['revision_reason'] is None):
                raise ValueError()
            if not original and (value['parent'] is None or not value['revision_reason']):
                raise ValueError()
        elif name == 'Diagnostic':
            has_counts = value['row_count'] is not None and value['duplicate_count'] is not None
            if value['code'] == 'observed_order_rows':
                if not has_counts or int(value['duplicate_count']) > int(value['row_count']):
                    raise ValueError()
            elif value['row_count'] is not None or value['duplicate_count'] is not None:
                raise ValueError()
        elif name == 'Support':
            reasons = value['reasons']
            if (len(set(reasons)) != len(reasons)
                    or (value['classification'] == 'supported_shape') != (not reasons)):
                raise ValueError()
        elif name == 'WrapperProfile':
            if value['profile_digest'] != digest({k: v for k, v in value.items()
                                                  if k != 'profile_digest'}):
                raise ValueError()
    except (ValueError, TypeError, AttributeError, DomainValidationError):
        raise IngestionError('import_invalid', path) from None


def _time(value, path):
    token = value['token']
    if value.get('zone') is not None:
        zone = value['zone']
        if (not re.fullmatch(r'[A-Za-z0-9_+./-]+', zone, re.ASCII)
                or any(x in {'.', '..'} for x in zone.split('/'))):
            raise IngestionError('import_invalid', path)
    try:
        if value['tag'] == 'date_only':
            if date.fromisoformat(token).isoformat() != token:
                raise ValueError()
        elif value['tag'] == 'instant':
            at = datetime.fromisoformat(token)
            fraction = re.search(r'\.(\d+)', token)
            if value['fractional_digits'] != (len(fraction[1]) if fraction else 0):
                raise ValueError()
            if token.endswith('-00:00') or at.utcoffset() is None:
                raise ValueError()
            offset = re.search(r'[+-](\d{2}):(\d{2})$', token)
            if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
                raise ValueError()
        elif not token.strip():
            raise ValueError()
    except (ValueError, OverflowError):
        raise IngestionError('import_invalid', path) from None


def compare_time(left, right):
    """Compare only compatible precision, retaining the original evidence tokens."""
    if left['tag'] == right['tag'] == 'instant':
        a, b = datetime.fromisoformat(left['token']), datetime.fromisoformat(right['token'])
    elif (left['tag'] == right['tag'] == 'date_only'
          and left['zone'] is not None and left['zone'] == right['zone']):
        a, b = date.fromisoformat(left['token']), date.fromisoformat(right['token'])
    else:
        raise IngestionError('import_conflict', '$.time')
    return (a > b) - (a < b)


def _evidence_order(left, right):
    """Compare source assertions without granting snapshot-head authority.

    Identical unknown assertions can agree within one observation. Frozen native
    legacy tokens may also carry an explicit offset; retain their legacy tag but
    honor that offset for evidence containment, as the frozen validator does.
    Head ordering deliberately continues to use the stricter compare_time.
    """
    if {k: v for k, v in left.items() if k != 'legacy'} == {
            k: v for k, v in right.items() if k != 'legacy'}:
        return 0
    if left['tag'] in {'instant', 'legacy_unspecified'} and right['tag'] in {
            'instant', 'legacy_unspecified'}:
        try:
            values = []
            for value in (left, right):
                at = datetime.fromisoformat(value['token'])
                if at.utcoffset() is None or (value['tag'] == 'legacy_unspecified'
                        and at.isoformat() != value['token']):
                    raise ValueError()
                values.append(at)
            return (values[0] > values[1]) - (values[0] < values[1])
        except (ValueError, OverflowError):
            raise IngestionError('import_conflict', '$.time') from None
    return compare_time(left, right)


def _same_evidence_time(left, right):
    try:
        return _evidence_order(left, right) == 0
    except IngestionError:
        return False


def _claim(value, path):
    kind = value['kind']
    if kind in {'holdings', 'cash_flows', 'crypto_transactions', 'activity'}:
        valid = value['source_account_key'] is not None and value['record_kind'] is None
        collection = 'records'
    elif kind == 'coverage':
        valid = value['source_account_key'] is not None and value['record_kind'] is not None
        collection = 'coverage'
    else:
        valid = (value['source_account_key'] is None and value['record_kind'] is None
                 and value['observation_id'] == '')
        collection = {'snapshot': 'snapshots', 'membership': 'membership'}[kind]
    if not valid or ('collection' in value and value['collection'] != collection):
        raise IngestionError('import_invalid', path)


def validate(value, name, *, namespace=None):
    """Validate an in-memory DTO; returned value is an isolated admitted copy."""
    if namespace is None:
        namespace = 'core' if name in CORE_NAMES else 'wire'
    # The canonical encoder bounds nesting and forbids floats in dict/list callers too.
    value = _load(encode(value), MAX_PLAN)
    _shape(value, definition(name, namespace), namespace, '$')
    if namespace == 'core':
        _scalar(name, value, '$')
    if name == 'Minimal' and namespace == 'core':
        _minimal(value)
    return value


def _load(data, limit):
    if type(data) is not bytes or not data or len(data) > limit:
        raise IngestionError('import_limit')
    # Bound nesting before json.loads allocates containers, including ignored
    # whitespace and escaped quotes; a shape validator runs only after this.
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
                raise IngestionError('import_limit')
        elif byte in (93, 125):
            level -= 1

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise IngestionError()
            result[key] = item
        return result

    def forbidden(_):
        raise IngestionError()

    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                            parse_float=forbidden, parse_constant=forbidden)
        if encode(result) != data:
            raise IngestionError()
        return result
    except IngestionError:
        raise
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise IngestionError() from None


def decode(data, name='Minimal', *, limit=None, namespace=None):
    if limit is None:
        limit = MAX_MINIMAL if name in {'Minimal', 'NativeDiscovery'} else MAX_PLAN
    return validate(_load(data, limit), name, namespace=namespace)


def _unique(values, path):
    if len(values) != len(set(values)):
        raise IngestionError('import_invalid', path)


def _minimal(value):
    tables = {}
    for name in ('accounts', 'assets', 'issuers', 'records', 'coverage', 'snapshots'):
        rows = value[name]
        if [x['local_id'] for x in rows] != [str(i) for i in range(len(rows))]:
            raise IngestionError('import_invalid', '$.' + name + '[].local_id')
        tables[name] = {x['local_id']: x for x in rows}
    if sum(len(value[x]) for x in ('records', 'coverage', 'snapshots')) + (
            value['membership'] is not None) > MAX_ROWS:
        raise IngestionError('import_limit')

    def ref(table, key):
        if key not in tables[table]:
            raise IngestionError('import_invalid', '$.' + table)
        return tables[table][key]

    def refs(table, keys):
        _unique(keys, '$.' + table)
        return [ref(table, key) for key in keys]

    def quantity(item):
        asset = ref('assets', item['asset_local_id'])
        if asset['kind'] in {'CRYPTO', 'UNSUPPORTED'} and (
                asset['symbol'] or '').upper() in {'BTC', 'LBTC'}:
            _, fraction, _, _ = decimal_parts_v1(DecimalTokenV1(item['quantity']))
            if any(ch != '0' for ch in fraction[8:]):
                raise IngestionError('import_invalid', '$.quantity')

    provider = value['provenance']['provider_id']
    _unique([(x['provider'], x['source_account_key']) for x in value['accounts']], '$.accounts')
    for account in value['accounts']:
        if account['provider'] != provider or not account['source_account_key'].strip():
            raise IngestionError('import_invalid', '$.accounts')
    for asset in value['assets']:
        if asset['issuer_local_id'] is not None:
            ref('issuers', asset['issuer_local_id'])
        _unique([(x['scheme'], x['value']) for x in asset['identifiers']], '$.assets[].identifiers')
        kind = asset['kind']
        if kind == 'CASH' and (not asset['currency'] or asset['symbol'] not in {
                None, asset['currency']} or any(asset[k] is not None for k in (
                'ticker', 'mic', 'network', 'settlement_identity'))):
            raise IngestionError('import_invalid', '$.assets')
        if kind == 'SECURITY' and (not asset['currency'] or not asset['ticker'] or not asset['mic']
                                   or asset['network'] is not None or asset['settlement_identity'] is not None
                                   or asset['symbol'] not in {None, asset['ticker']}):
            raise IngestionError('import_invalid', '$.assets')
        if kind == 'CRYPTO' and (not asset['symbol'] or not asset['network']
                                 or asset['ticker'] is not None or asset['mic'] is not None):
            raise IngestionError('import_invalid', '$.assets')
    if value['membership'] is not None:
        refs('accounts', value['membership']['account_local_ids'])
    for coverage in value['coverage']:
        ref('accounts', coverage['account_local_id'])
        refs('assets', coverage['instrument_scope']['asset_local_ids'])
        interval = coverage['time']
        if interval['tag'] == 'interval':
            if _evidence_order(interval['start'], interval['end']) > 0:
                raise IngestionError('import_invalid', '$.coverage[].time')
    for record in value['records']:
        ref('accounts', record['source_account_local_id'])
        at = record['as_of'] if record['record_type'] == 'position' else record['event_time']
        applicable = [c for c in value['coverage'] if c['account_local_id'] == record['source_account_local_id']
                      and c['kind'] == record['source_kind']
                      and c['observation_id'] == record['identity']['observation_id']
                      and _contains(c['time'], at)]
        if not applicable:
            raise IngestionError('import_invalid', '$.records[].coverage')
        if record['record_type'] == 'position':
            quantity(record)
            asset = ref('assets', record['asset_local_id'])
            for field in ('market_value', 'unit_price', 'cost_native', 'unrealized'):
                if record[field] is not None and asset['currency'] is not None:
                    if record[field]['currency'] != asset['currency']:
                        raise IngestionError('import_invalid', '$.records[].' + field)
            if record['cost_cad'] is not None and record['cost_cad']['currency'] != 'CAD':
                raise IngestionError('import_invalid', '$.records[].cost_cad')
            negative = record['quantity'].startswith('-') and any(
                c in '123456789' for c in record['quantity'])
            required = ({'signed_position'} if negative else set()) | (
                {'unsupported_instrument'} if asset['kind'] == 'UNSUPPORTED' else set())
            if (record['identity']['change'] == 'void'
                    or not required <= set(record['support']['reasons'])):
                raise IngestionError('import_invalid', '$.records[].support')
            if not any(_in_scope(record, c['instrument_scope'], tables['assets']) for c in applicable):
                raise IngestionError('import_invalid', '$.records[].coverage')
            continue
        recognized = {'purchase': 'BUY', 'buy': 'BUY', 'sale': 'SELL', 'sell': 'SELL',
            'transfer': 'TRANSFER', 'fee': 'FEE', 'income': 'INCOME', 'deposit': 'FUNDING',
            'withdrawal': 'FUNDING', 'funding': 'FUNDING', 'corporate_action': 'CORPORATE_ACTION'}
        source_type = record['source_type'].lower()
        if (not record['source_type'].strip() or not record['source_status'].strip()
                or record['kind'] != recognized.get(source_type, 'UNSUPPORTED')):
            raise IngestionError('import_invalid', '$.records[].kind')
        cash = record['cash_flow']
        is_cash = record['source_kind'] == 'cash_flows' or record['kind'] == 'FUNDING'
        if is_cash != (cash is not None):
            raise IngestionError('import_invalid', '$.records[].cash_flow')
        links = list(record['economic_references'])
        if cash is not None:
            links.extend(x for x in (cash['counterpart'], cash['cash_leg_of']) if x is not None)
            if (Decimal(cash['cash_amount']['amount']) <= 0 or record['legs']
                    or source_type in {'deposit', 'income'} and cash['direction'] != 'in'
                    or source_type in {'withdrawal', 'fee'} and cash['direction'] != 'out'
                    or cash['cash_leg_of'] is not None and (
                        cash['cash_leg_of']['kind'] != 'crypto_transactions'
                        or cash['boundary'] != 'internal')):
                raise IngestionError('import_invalid', '$.records[].cash_flow')
        elif not record['legs']:
            raise IngestionError('import_invalid', '$.records[].legs')
        if any(x['kind'] not in {'cash_flows', 'crypto_transactions', 'activity'}
               or x['revision'] is None and record['identity']['legacy'] is None for x in links):
            raise IngestionError('import_invalid', '$.records[].economic_references')
        required = set()
        if record['kind'] in {'UNSUPPORTED', 'CORPORATE_ACTION'}:
            required.add('unsupported_activity')
        if record['status'] == 'unsupported':
            required.add('unsupported_status')
        for leg in record['legs']:
            ref('accounts', leg['account_local_id'])
            quantity(leg)
            if not any(_in_scope(leg, c['instrument_scope'], tables['assets']) for c in applicable):
                raise IngestionError('import_invalid', '$.records[].coverage')
            if ref('assets', leg['asset_local_id'])['kind'] == 'UNSUPPORTED':
                required.add('unsupported_instrument')
        if record['kind'] == 'BUY':
            acquisitions = [x for x in record['legs'] if x['role'] == 'ACQUISITION']
            if not acquisitions or any(Decimal(x['quantity']) <= 0 or ref(
                    'assets', x['asset_local_id'])['kind'] not in {'CRYPTO', 'SECURITY'}
                    or ref('accounts', x['account_local_id'])['role'] == 'funding'
                    for x in acquisitions):
                raise IngestionError('import_invalid', '$.records[].legs')
            payments = [x for x in record['legs'] if x['role'] == 'PAYMENT']
            if any(Decimal(x['quantity']) >= 0 for x in payments):
                raise IngestionError('import_invalid', '$.records[].legs')
            if value['provenance']['parser_api'] == 2 and (
                    len(acquisitions) != 1 or not payments
                    or len(acquisitions) + len(payments) != len(record['legs'])):
                raise IngestionError('import_evidence_unsupported', '$.records[].legs')
        for fee in record['fees'] or []:
            if fee['account_local_id'] is not None:
                ref('accounts', fee['account_local_id'])
            quantity(fee)
            if ref('assets', fee['asset_local_id'])['kind'] == 'UNSUPPORTED':
                required.add('unsupported_instrument')
            if fee['quantity'].startswith('-') and any(ch in '123456789' for ch in fee['quantity']):
                raise IngestionError('import_invalid', '$.records[].fees')
        if not required <= set(record['support']['reasons']):
            raise IngestionError('import_invalid', '$.records[].support')
        if record['identity']['change'] == 'void' and record['status'] != 'cancelled':
            raise IngestionError('import_invalid', '$.records[].status')
        if record['source_status'] in {'completed', 'pending', 'cancelled'}:
            if record['status'] != record['source_status']:
                raise IngestionError('import_invalid', '$.records[].status')
        elif record['status'] != 'unsupported':
            raise IngestionError('import_invalid', '$.records[].status')
        lifecycle = record['lifecycle']
        if record['lifecycle_reference'] is not None and lifecycle is None:
            raise IngestionError('import_evidence_unsupported', '$.records[].lifecycle')
        if lifecycle is not None:
            quantity(lifecycle['payin'])
            quantity(lifecycle['payout'])
            for field in ('completed_at', 'sent_at'):
                if lifecycle[field] is not None and _evidence_order(
                        lifecycle[field], lifecycle['created_at']) < 0:
                    raise IngestionError('import_invalid', '$.records[].lifecycle.' + field)
            for field in ('payin', 'payout'):
                if lifecycle[field]['quantity'].startswith('-') and any(
                        ch in '123456789' for ch in lifecycle[field]['quantity']):
                    raise IngestionError('import_invalid', '$.records[].lifecycle.' + field)
            if record['status'] == 'completed':
                if lifecycle['completed_at'] is None or not _same_evidence_time(
                        record['event_time'], lifecycle['completed_at']):
                    raise IngestionError('import_invalid', '$.records[].lifecycle.completed_at')
            if (record['kind'] == 'BUY' and value['provenance']['parser_api'] == 2
                    and record['support']['classification'] == 'supported_shape'):
                _purchase(record, lifecycle)
        for field in ('acquisition_cost_cad',):
            if record[field] is not None and record[field]['currency'] != 'CAD':
                raise IngestionError('import_invalid', '$.records[].' + field)
    seen_positions = []
    for snapshot in value['snapshots']:
        accounts = snapshot['account_local_ids']
        if not accounts:
            raise IngestionError('import_invalid', '$.snapshots[].account_local_ids')
        refs('accounts', accounts)
        coverages = refs('coverage', snapshot['coverage_local_ids'])
        positions = refs('records', snapshot['position_local_ids'])
        for coverage in coverages:
            if (coverage['kind'] != 'holdings' or coverage['account_local_id'] not in accounts
                    or coverage['observation_id'] != snapshot['source_id']):
                raise IngestionError('import_invalid', '$.snapshots[].coverage_local_ids')
            if not _contains(coverage['time'], snapshot['as_of']):
                raise IngestionError('import_invalid', '$.snapshots[].coverage_local_ids')
        if set(accounts) != {x['account_local_id'] for x in coverages}:
            raise IngestionError('import_invalid', '$.snapshots[].account_local_ids')
        for position in positions:
            if position['record_type'] != 'position' or position['source_account_local_id'] not in accounts:
                raise IngestionError('import_invalid', '$.snapshots[].position_local_ids')
            if (position['identity']['observation_id'] != snapshot['source_id']
                    or position['identity']['revision'] != snapshot['revision']
                    or not _same_evidence_time(position['as_of'], snapshot['as_of'])):
                raise IngestionError('import_invalid', '$.snapshots[].position_local_ids')
            applicable = [c for c in coverages if c['account_local_id'] == position['source_account_local_id']
                          and _in_scope(position, c['instrument_scope'], tables['assets'])]
            if not applicable:
                raise IngestionError('import_invalid', '$.snapshots[].coverage_local_ids')
        seen_positions.extend(snapshot['position_local_ids'])
    _unique(seen_positions, '$.snapshots[].position_local_ids')
    if set(seen_positions) != {r['local_id'] for r in value['records'] if r['record_type'] == 'position'}:
        raise IngestionError('import_invalid', '$.snapshots')
    for diagnostic in value['provenance']['diagnostics']:
        refs('records', diagnostic['record_local_ids'])


def _in_scope(position, scope, assets):
    return (scope['tag'] == 'all' or (scope['tag'] == 'category'
            and assets[position['asset_local_id']]['kind'] == scope['category'])
            or position['asset_local_id'] in scope['asset_local_ids'])


def _contains(selector, at):
    if selector['tag'] == 'point':
        return _same_evidence_time(selector['at'], at)
    try:
        left = _evidence_order(selector['start'], at)
        right = _evidence_order(selector['end'], at)
    except IngestionError:
        return False
    return ((left < 0 or left == 0 and selector['start_inclusive'])
            and (right > 0 or right == 0 and selector['end_inclusive']))


def _purchase(record, lifecycle):
    acquisitions = [x for x in record['legs'] if x['role'] == 'ACQUISITION']
    payments = [x for x in record['legs'] if x['role'] == 'PAYMENT']
    if len(acquisitions) != 1 or len(payments) != 1 or len(record['legs']) != 2:
        raise IngestionError('import_evidence_unsupported', '$.records[].legs')
    acquired, paid = acquisitions[0], payments[0]
    from decimal import Decimal
    if (Decimal(acquired['quantity']) <= 0 or Decimal(paid['quantity']) >= 0
            or acquired['asset_local_id'] != lifecycle['payout']['asset_local_id']
            or paid['asset_local_id'] != lifecycle['payin']['asset_local_id']
            or Decimal(acquired['quantity']) != Decimal(lifecycle['payout']['quantity'])
            or Decimal(paid['quantity']).copy_abs() != Decimal(lifecycle['payin']['quantity'])):
        raise IngestionError('import_invalid', '$.records[].lifecycle')
