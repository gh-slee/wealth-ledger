"""Project frozen parser evidence into typed local evidence while raw is in RAM.

This module does not import a plugin, select mappings or persist raw/discovery
bytes. Installation and profile arguments come from the trusted operator catalog.
"""
from __future__ import annotations

from decimal import Decimal
import re

from .. import source_v2 as parser
from ..data_sources import contract_v1 as source
from ..domain.validation_v1 import DomainValidationError, decode_domain_v1
from .codec import decode, digest, encode, sha256, validate
from .contracts import IngestionError, MAX_CONTEXT, MAX_MINIMAL, MAX_RAW


def instant(token, zone=None):
    if token is None:
        return None
    match = re.search(r'\.(\d+)', token)
    return validate({'tag': 'instant', 'token': token, 'zone': zone,
                     'fractional_digits': len(match[1]) if match else 0}, 'Time')


def _installation(descriptor, profile, context):
    try:
        desc = source.validate_descriptor(source.decode(source.Descriptor, descriptor))
        install_id = source.installation_id(desc)
    except source.ContractError:
        raise IngestionError('import_evidence_unsupported') from None
    profile = validate(profile, 'WrapperProfile')
    if (profile['installation_id'] != install_id
            or profile['image_digest'] != desc.execution_image_digest
            or context['installation_id'] != install_id
            or context['image_digest'] != profile['image_digest']
            or context['wrapper_profile_digest'] != profile['profile_digest']
            or context['format_version'] not in profile['format_versions']
            or context['format_version'] not in desc.format_versions):
        raise IngestionError('import_stale')
    return desc, profile


def admit_parser2(raw, payload, context_bytes, descriptor, profile):
    """Return canonical minimal bytes after frozen parser and trusted-context checks."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RAW:
        raise IngestionError('import_limit')
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_MINIMAL:
        raise IngestionError('import_limit')
    context = decode(context_bytes, 'ParserChildContext', limit=MAX_CONTEXT)
    desc, profile = _installation(descriptor, profile, context)
    if desc.payload_kind != 'parser_v2' or profile['projection'] != 'parser2-minimal-v1':
        raise IngestionError('import_evidence_unsupported')
    try:
        batch = parser.decode_batch(payload, raw)
        frozen_context = source.decode(parser.ParseContext, context['parser_context'])
        parser.validate_batch(batch, raw, context=frozen_context)
        data = source.load_json(payload, limit=MAX_MINIMAL)
    except (ValueError, TypeError, AttributeError, source.ContractError):
        raise IngestionError('import_invalid') from None
    info = data['adapter']
    if (info['provider_id'] != desc.provider_id or info['adapter_id'] != desc.adapter_id
            or info['adapter_version'] != desc.package_version
            or info['api_version'] != desc.parser_api_version
            or data['export_version'] != context['format_version']):
        raise IngestionError('import_evidence_unsupported')
    if data['evidence']['context'] != context['parser_context']:
        raise IngestionError('import_stale')
    if context['parser_context']['revisions'] or context['parser_context']['scope_revisions']:
        raise IngestionError('import_invalid')
    result = _parser_projection(data, context, profile, sha256(payload))
    return _finish_projection(result, profile)


def _finish_projection(result, profile):
    encoded = encode(verify_selected_profile(result, profile))
    if len(encoded) > MAX_MINIMAL:
        raise IngestionError('import_limit')
    return encoded


def verify_selected_profile(minimal, profile):
    """Check retained provenance against a trusted, currently selected profile.

    Call after live source/context guards for new admission or Plan preparation.
    The profile must come from the operator catalog, never the staged document.
    This does not authenticate a source or replace receipt-first replay checks.
    """
    minimal = validate(minimal, 'Minimal')
    profile = validate(profile, 'WrapperProfile')
    provenance = minimal['provenance']
    for field, source_field in (('installation_id', 'installation_id'),
                                ('image_digest', 'image_digest'),
                                ('wrapper_profile_digest', 'profile_digest')):
        if provenance[field] != profile[source_field]:
            raise IngestionError('import_stale')
    if provenance['format_selection'] not in profile['format_versions']:
        raise IngestionError('import_stale')
    native = profile['projection'] == 'domain1-minimal-v1'
    if (native and provenance['parser_api'] is not None) or (
            not native and provenance['parser_api'] != 2):
        raise IngestionError('import_invalid', '$.provenance.parser_api')
    if native and provenance['id_policy'] != profile['identity_policy']:
        raise IngestionError('import_invalid', '$.provenance.id_policy')
    return minimal


def admit_native(raw, payload, context_bytes, descriptor, profile):
    """Validate native discovery in its ephemeral namespace and erase its IDs.

    Frozen domain validation remains authoritative. Lifecycle sidecars retain
    actual wrapper evidence; archive pointers alone never reconstruct values.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RAW:
        raise IngestionError('import_limit')
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_MINIMAL:
        raise IngestionError('import_limit')
    context = decode(context_bytes, 'NativeChildContext', limit=MAX_CONTEXT)
    desc, profile = _installation(descriptor, profile, context)
    if desc.payload_kind != 'domain_v1' or profile['projection'] != 'domain1-minimal-v1':
        raise IngestionError('import_evidence_unsupported')
    data = decode(payload, 'NativeDiscovery')
    domain = data['domain']
    try:
        decode_domain_v1(encode(domain))
    except DomainValidationError:
        raise IngestionError('import_invalid') from None
    namespace, provenance = context['namespace'], domain['provenance']
    if (domain['tenant_id'] != namespace['tenant_id']
            or domain['portfolio_id'] != namespace['portfolio_id']
            or len(domain['connections']) != 1
            or domain['connections'][0]['id']['value'] != namespace['connection_id']
            or domain['connections'][0]['kind'] != 'FILE_IMPORT'
            or domain['connections'][0]['provider'] != desc.provider_id
            or context['provider_id'] != desc.provider_id
            or domain['evidence_reference'] != context['evidence_reference']
            or provenance['evidence_reference'] != context['evidence_reference']
            or provenance['evidence_at'] != context['evidence_at']):
        raise IngestionError('import_stale')
    if (provenance['raw_sha256'] != sha256(raw)
            or provenance['provider'] != desc.provider_id
            or provenance['adapter'] != desc.adapter_id
            or provenance['adapter_version'] != desc.package_version
            or provenance['export_version'] != context['format_version']):
        raise IngestionError('import_invalid')
    return _finish_projection(_native_projection(data, context, profile, sha256(payload)), profile)


def _native_projection(data, context, profile, discovery_digest):
    domain, original = data['domain'], data['domain']['provenance']
    account_map = {row['id']['value']: str(i) for i, row in enumerate(domain['accounts'])}
    asset_map = {row['id']['value']: str(i) for i, row in enumerate(domain['instruments'])}
    issuer_map = {row['id']['value']: str(i) for i, row in enumerate(domain['issuers'])}
    aliases = {}
    for alias in domain['aliases']:
        key = alias['account']['value']
        if key in aliases:
            # Multiple source aliases for one ephemeral declaration cannot be
            # resolved by guessing which account owns an otherwise unkeyed leg.
            raise IngestionError('import_evidence_unsupported', '$.accounts')
        if alias['evidence_reference'] != context['evidence_reference']:
            raise IngestionError('import_invalid')
        aliases[key] = alias
    if aliases.keys() != account_map.keys():
        raise IngestionError('import_evidence_unsupported', '$.accounts')
    accounts = [{'local_id': str(i), 'provider': aliases[row['id']['value']]['provider'],
                 'source_account_key': aliases[row['id']['value']]['source_account_key'],
                 'category': row['category'], 'role': row['role'], 'label': row['label'],
                 'masked_identifier': None} for i, row in enumerate(domain['accounts'])]
    assets = []
    for row in domain['instruments']:
        if row['evidence_reference'] != context['evidence_reference']:
            raise IngestionError('import_invalid')
        assets.append({'local_id': asset_map[row['id']['value']],
            **{k: row[k] for k in ('kind', 'currency', 'ticker', 'mic', 'symbol', 'network',
                                   'settlement_identity', 'identifiers', 'source_descriptor')},
            'identifier': None, 'issuer_local_id': None if row['issuer'] is None
                else issuer_map[row['issuer']['value']]})

    def claim(ref):
        if ref is None:
            return None
        selector = ref['selector']
        return {k: selector[k] for k in ('provider', 'source_account_key', 'kind',
                'source_id', 'observation_id', 'revision', 'record_kind')}

    def identity(value):
        if value['evidence_reference'] != context['evidence_reference']:
            raise IngestionError('import_invalid')
        selector = value['source']
        return {'source_id': selector['source_id'], 'revision': selector['revision'],
                'observation_id': selector['observation_id'], 'change': value['change'],
                'parent': claim(value['parent']), 'revision_reason': value['reason'],
                'legacy': value['legacy']}

    def money(value):
        return None if value is None else {'amount': value['amount']['token'],
                                          'currency': value['currency']}

    def source_time(value):
        if value is None or value['tag'] != 'legacy_datetime':
            return value
        # Preserve the original token and unavailable archive lineage. An aware
        # legacy token does not upgrade its declared precision or head authority.
        return {'tag': 'legacy_unspecified', 'token': value['token'],
                'zone': None, 'legacy': value['archive']}

    def selector_time(value):
        if value['tag'] == 'point':
            return {'tag': 'point', 'at': source_time(value['at'])}
        return {**value, 'start': source_time(value['start']), 'end': source_time(value['end'])}

    def leg(value):
        return {'account_local_id': account_map[value['account']['value']],
                'asset_local_id': asset_map[value['instrument']['value']],
                'quantity': value['quantity']['token']}

    coverage, coverage_keys = [], {}
    for row in domain['coverage']:
        local_id = str(len(coverage))
        selector = {'provider': original['provider'], 'source_account_key': row['source_account_key'],
                    'kind': 'coverage', 'record_kind': row['kind'], 'source_id': row['scope_id'],
                    'observation_id': row['observation_id'], 'revision': row['revision']}
        coverage_keys[encode(selector)] = local_id
        coverage.append({'local_id': local_id, 'account_local_id': account_map[row['account']['value']],
            **{k: row[k] for k in ('kind', 'scope_id', 'revision', 'status', 'basis',
                                   'observation_id', 'legacy')}, 'time': selector_time(row['time']),
            'parent': claim(row['parent']),
            'instrument_scope': {'tag': row['instrument_scope']['tag'],
                'category': row['instrument_scope']['category'], 'asset_local_ids': sorted(
                    asset_map[x['value']] for x in row['instrument_scope']['instruments'])}})
    records, snapshots = [], []
    for snapshot in domain['snapshots']:
        positions = []
        for row in snapshot['items']:
            local_id = str(len(records))
            positions.append(local_id)
            records.append({'local_id': local_id, 'record_type': 'position',
                'source_account_local_id': account_map[row['account']['value']],
                'source_kind': row['identity']['source']['kind'], 'identity': identity(row['identity']),
                'asset_local_id': asset_map[row['instrument']['value']], 'as_of': source_time(row['as_of']),
                'quantity': row['quantity']['token'], 'name': row['source_name'],
                'instrument_type': row['source_type'], 'exchange': row['source_exchange'],
                'support': row['support'], **{k: money(row[k]) for k in
                    ('market_value', 'unit_price', 'cost_native', 'cost_cad', 'unrealized')}})
        snapshots.append({'local_id': str(len(snapshots)),
            **{k: snapshot[k] for k in ('source_id', 'revision', 'legacy')},
            'as_of': source_time(snapshot['as_of']),
            'parent': claim(snapshot['parent']),
            'account_local_ids': [account_map[x['value']] for x in snapshot['accounts']],
            'coverage_local_ids': [coverage_keys[encode(claim(x))] for x in snapshot['coverage']],
            'position_local_ids': positions})
    sidecars = {}
    for item in data['lifecycle_by_activity']:
        ordinal = item['activity_ordinal']
        if ordinal in sidecars or ordinal >= len(domain['activities']):
            raise IngestionError('import_invalid', '$.records[].lifecycle')
        sidecars[ordinal] = item['value']
    for ordinal, row in enumerate(domain['activities']):
        if row['lifecycle'] is not None and ordinal not in sidecars:
            raise IngestionError('import_evidence_unsupported', '$.records[].lifecycle')
        cash = row['cash_flow']
        selector = row['identity']['source']
        owner = next(x['local_id'] for x in accounts
                     if x['source_account_key'] == selector['source_account_key'])
        records.append({'local_id': str(len(records)), 'record_type': 'activity',
            'source_account_local_id': owner, 'source_kind': selector['kind'],
            'identity': identity(row['identity']), 'event_time': source_time(row['event_time']),
            **{k: row[k] for k in ('kind', 'status', 'transfer_reference', 'support')},
            'source_type': row['source_kind'], 'source_status': row['source_status'],
            'legs': [{**leg(x), 'role': x['role']} for x in row['legs']],
            'acquisition_cost': money(row['acquisition_cost']),
            'acquisition_cost_cad': money(row['acquisition_cost_cad']),
            'fees': None if row['fees'] is None else [{**leg(x),
                'included_in_leg': x['included_in_leg'], 'included_in_cost': x['included_in_cost']}
                for x in row['fees']], 'economic_references': [claim(x) for x in row['economic_references']],
            'cash_flow': None if cash is None else {'cash_amount': money(cash['cash_amount']),
                **{k: cash[k] for k in ('direction', 'boundary', 'transfer_reference')},
                'counterpart': claim(cash['counterpart']), 'cash_leg_of': claim(cash['cash_leg_of'])},
            'lifecycle_reference': row['lifecycle'], 'lifecycle': sidecars.get(ordinal)})
    provenance = {'provider_id': original['provider'], 'adapter_id': original['adapter'],
        'adapter_version': original['adapter_version'], 'parser_api': None,
        'export_version': original['export_version'], 'raw_sha256': original['raw_sha256'],
        'discovery_sha256': discovery_digest, 'installation_id': context['installation_id'],
        'image_digest': profile['image_digest'], 'wrapper_profile_digest': profile['profile_digest'],
        'evidence_reference': original['evidence_reference'], 'evidence_at': source_time(original['evidence_at']),
        'source_timezone': None, 'format_selection': context['format_version'], 'source_alias': None,
        'source_effective_at': source_time(original['source_effective_at']),
        'source_imported_at': source_time(original['imported_at']),
        'source_accepted_at': source_time(original['accepted_at']), 'id_policy': profile['identity_policy'],
        'diagnostics': [], 'field_mappings': [], 'semantic_digests': [], 'legacy': original['legacy']}
    return {'version': 1, 'provenance': provenance, 'accounts': accounts, 'assets': assets,
            'issuers': [{'local_id': str(i), 'label': x['label']}
                        for i, x in enumerate(domain['issuers'])], 'membership': data['membership'],
            'coverage': coverage, 'snapshots': snapshots, 'records': records}


def _parser_projection(data, context, profile, discovery_digest):
    evidence = data['evidence']
    adapter = data['adapter']
    accounts, assets = [], []
    account_map, asset_map = {}, {}
    for account in data['accounts']:
        local_id = str(len(accounts))
        account_map[encode(account['key'])] = local_id
        accounts.append({'local_id': local_id, 'provider': account['key']['provider'],
            'source_account_key': account['key']['account_id'], 'category': account['account_type'],
            'role': account['role'], 'label': account['label'],
            'masked_identifier': account['masked_identifier']})

    def account_id(key):
        try:
            return account_map[encode(key)]
        except KeyError:
            raise IngestionError('import_invalid', '$.accounts') from None

    def asset_id(asset):
        key = encode(asset)
        if key not in asset_map:
            local_id = str(len(assets))
            kind = {'cash': 'CASH', 'security': 'SECURITY', 'crypto': 'CRYPTO'}.get(
                asset['kind'], 'UNSUPPORTED')
            assets.append({'local_id': local_id, 'kind': kind, 'symbol': asset['symbol'],
                'currency': asset['currency'], 'ticker': asset['symbol'] if kind == 'SECURITY' else None,
                'mic': asset['market'] if kind == 'SECURITY' else None,
                'network': asset['network'], 'settlement_identity': None,
                'identifier': asset['identifier'], 'identifiers': [], 'issuer_local_id': None,
                'source_descriptor': key.decode('utf-8')})
            asset_map[key] = local_id
        return asset_map[key]

    def claim(ref, observation=''):
        if ref is None:
            return None
        return {'provider': ref['account']['provider'],
                'source_account_key': ref['account']['account_id'], 'kind': ref['kind'],
                'source_id': ref['source_id'], 'observation_id': observation,
                'revision': ref['revision'], 'record_kind': None}

    def parent(kind, scope_id, revision, account=None, observation='', record_kind=None):
        if revision is None:
            return None
        return {'provider': adapter['provider_id'], 'source_account_key':
                None if account is None else account['account_id'], 'kind': kind,
                'source_id': scope_id, 'observation_id': observation,
                'revision': revision, 'record_kind': record_kind}

    def lifecycle(value):
        if value is None:
            return None
        result = {k: value[k] for k in ('source_type', 'source_subtype', 'source_status',
                                       'payin_status', 'payout_status', 'exchange_rate', 'index_rate')}
        result.update({k: instant(value[k]) for k in ('created_at', 'completed_at', 'sent_at')})
        for name in ('payin', 'payout'):
            result[name] = {'asset_local_id': asset_id(value[name]['asset']),
                            'quantity': value[name]['quantity'], 'method': value[name]['method']}
        return result

    records = []
    for row in data['records']:
        key = row['key']
        observation = row.get('observation_id', '')
        identity = {'source_id': key['source_id'], 'revision': key['revision'],
            'change': key['change'], 'parent': parent(row['kind'], key['source_id'],
            key['supersedes_revision'], key['account'], observation),
            'revision_reason': row.get('revision_reason'), 'observation_id': observation,
            'legacy': None}
        base = {'local_id': str(len(records)), 'source_account_local_id': account_id(key['account']),
                'source_kind': row['kind'], 'identity': identity,
                'support': {'classification': 'supported_shape', 'reasons': []}}
        if row['kind'] == 'holdings':
            base.update(record_type='position', as_of=instant(row['as_of']),
                        asset_local_id=asset_id(row['asset']))
            base.update({k: row[k] for k in ('name', 'instrument_type', 'exchange', 'quantity',
                'market_value', 'unit_price', 'cost_native', 'cost_cad', 'unrealized')})
            reasons = []
            if assets[int(base['asset_local_id'])]['kind'] == 'UNSUPPORTED':
                reasons.append('unsupported_instrument')
            if Decimal(row['quantity']) < 0:
                reasons.append('signed_position')
            if reasons:
                base['support'] = {'classification': 'unsupported', 'reasons': reasons}
        else:
            base.update(record_type='activity', event_time=instant(row['occurred_at']),
                source_type=row['type'], source_status=row['status'], status=row['status'],
                transfer_reference=row['transfer_reference'], lifecycle_reference=None,
                economic_references=[], cash_flow=None)
            if row['counterpart'] is not None:
                base['economic_references'].append(claim(row['counterpart']))
            if row['kind'] == 'crypto_transactions':
                if row['type'] != 'purchase' or len(row['legs']) != 2:
                    raise IngestionError('import_evidence_unsupported', '$.records[].legs')
                base.update(kind='BUY', acquisition_cost=row['acquisition_cost'],
                            acquisition_cost_cad=row['acquisition_cost_cad'])
                base['legs'] = []
                for leg in row['legs']:
                    if Decimal(leg['quantity']) > 0 and leg['asset']['kind'] == 'crypto':
                        role = 'ACQUISITION'
                    elif Decimal(leg['quantity']) < 0:
                        role = 'PAYMENT'
                    else:
                        raise IngestionError('import_evidence_unsupported', '$.records[].legs')
                    base['legs'].append({'account_local_id': account_id(leg['account']),
                        'asset_local_id': asset_id(leg['asset']), 'quantity': leg['quantity'], 'role': role})
                base['fees'] = None if row['fees'] is None else [
                    {'account_local_id': account_id(f['account']), 'asset_local_id': asset_id(f['asset']),
                     **{k: f[k] for k in ('quantity', 'included_in_leg', 'included_in_cost')}}
                    for f in row['fees']]
            else:
                kind = {'deposit': 'FUNDING', 'withdrawal': 'FUNDING', 'transfer': 'TRANSFER',
                        'income': 'INCOME', 'fee': 'FEE'}[row['type']]
                base.update(kind=kind, acquisition_cost=None, acquisition_cost_cad=None, fees=None,
                    legs=[],
                    cash_flow={'direction': row['direction'], 'boundary': row['boundary'],
                        'cash_amount': row['amount'], 'counterpart': claim(row['counterpart']),
                        'cash_leg_of': claim(row['cash_leg_of']), 'transfer_reference': row['transfer_reference']})
                if row['cash_leg_of'] is not None:
                    base['economic_references'].append(claim(row['cash_leg_of']))
            base['lifecycle'] = lifecycle(row['lifecycle'])
        records.append(base)
    coverage = []
    for row in data['coverage']:
        coverage.append({'local_id': str(len(coverage)), 'kind': row['kind'],
            'account_local_id': account_id(row['account']), 'scope_id': row['scope_id'],
            'revision': row['revision'], 'parent': parent('coverage', row['scope_id'],
                row['supersedes_revision'], row['account'], row['observation_id'], row['kind']),
            'time': {'tag': 'interval', 'start': instant(row['start']), 'end': instant(row['end']),
                     'start_inclusive': True, 'end_inclusive': True},
            'instrument_scope': {'tag': 'all', 'category': None, 'asset_local_ids': []},
            'status': row['status'], 'basis': row['basis'], 'observation_id': row['observation_id'],
            'legacy': None})
    snapshots = []
    for row in data['snapshots']:
        snapshots.append({'local_id': str(len(snapshots)), 'source_id': row['source_id'],
            'revision': row['revision'], 'parent': parent('snapshot', row['source_id'], row['supersedes_revision']),
            'as_of': instant(row['as_of']), 'account_local_ids': [account_id(x) for x in row['accounts']],
            'coverage_local_ids': [c['local_id'] for c in coverage if c['observation_id'] == row['source_id']],
            'position_local_ids': [r['local_id'] for r in records
                if r['record_type'] == 'position' and r['identity']['observation_id'] == row['source_id']],
            'legacy': None})
    membership = data['membership']
    membership = {'scope_id': membership['scope_id'], 'revision': membership['revision'],
        'parent': parent('membership', membership['scope_id'], membership['supersedes_revision']),
        'account_local_ids': [account_id(x) for x in membership['accounts']],
        'status': membership['status'], 'basis': membership['basis']}
    provenance = {'provider_id': adapter['provider_id'], 'adapter_id': adapter['adapter_id'],
        'adapter_version': adapter['adapter_version'], 'parser_api': adapter['api_version'],
        'export_version': data['export_version'], 'raw_sha256': evidence['raw_sha256'],
        'discovery_sha256': discovery_digest, 'installation_id': context['installation_id'],
        'image_digest': profile['image_digest'], 'wrapper_profile_digest': profile['profile_digest'],
        'evidence_reference': evidence['context']['source_reference'],
        'evidence_at': instant(evidence['context']['evidence_at']),
        'source_timezone': evidence['context']['source_timezone'],
        'format_selection': context['format_version'], 'source_alias': evidence['context']['account_alias'],
        'source_effective_at': instant(evidence['effective_at']),
        'source_imported_at': None, 'source_accepted_at': None, 'id_policy': evidence['id_policy'],
        'diagnostics': _diagnostics(evidence['diagnostics'], records, accounts, assets),
        'field_mappings': [{'source_field': k, 'canonical_field': v} for k, v in evidence['mappings']
                           if k != 'legacy_semantic_hash'],
        'semantic_digests': [{'name': k, 'value': v} for k, v in evidence['mappings']
                             if k == 'legacy_semantic_hash'], 'legacy': None}
    return {'version': 1, 'provenance': provenance, 'accounts': accounts, 'assets': assets,
            'issuers': [], 'membership': membership, 'coverage': coverage,
            'snapshots': snapshots, 'records': records}


def _diagnostics(rows, records, accounts, assets):
    result = []
    for row in rows:
        parameters = dict(row['parameters'])
        if len(parameters) != len(row['parameters']):
            raise IngestionError('import_evidence_unsupported', '$.diagnostics')
        code = row['code']
        item = {'code': code, 'severity': row['severity'], 'row_count': None,
                'duplicate_count': None, 'record_local_ids': []}
        if code in {'market_math', 'unrealized_math', 'nonpositive_cost_quantity'}:
            if parameters.keys() != {'account_id', 'symbol'}:
                raise IngestionError('import_evidence_unsupported', '$.diagnostics')
            item['record_local_ids'] = [r['local_id'] for r in records if r['record_type'] == 'position'
                and accounts[int(r['source_account_local_id'])]['source_account_key'] == parameters['account_id']
                and assets[int(r['asset_local_id'])]['symbol'] == parameters['symbol']]
            if not item['record_local_ids']:
                raise IngestionError('import_evidence_unsupported', '$.diagnostics')
        elif code == 'observed_order_rows':
            if parameters.keys() != {'rows', 'duplicates'}:
                raise IngestionError('import_evidence_unsupported', '$.diagnostics')
            item.update(row_count=parameters['rows'], duplicate_count=parameters['duplicates'])
        elif code not in {'wallet_balance_unverified', 'wallet_fees_unknown'} or parameters:
            raise IngestionError('import_evidence_unsupported', '$.diagnostics')
        result.append(validate(item, 'Diagnostic'))
    return result
