"""Source identity and typed financial projections, independent of storage.

Only explicit source identities and confirmed scoped mappings establish these
keys. Neither amounts nor a hash alone establish economic identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy

from .codec import compare_time, digest, encode, validate
from .contracts import IngestionError
from .mapping import MappingIndex


def source_revision_key(minimal, collection, local_id, *, tenant_id, portfolio_id, connection_id):
    if collection == 'membership':
        if local_id != '0' or minimal['membership'] is None:
            raise IngestionError('import_invalid', '$.membership')
        row = minimal['membership']
    elif collection in {'records', 'coverage', 'snapshots'}:
        try:
            row = next(x for x in minimal[collection] if x['local_id'] == local_id)
        except StopIteration:
            raise IngestionError('import_invalid', '$.' + collection) from None
    else:
        raise IngestionError('import_invalid')
    source = {'version': 1, 'tenant_id': tenant_id, 'portfolio_id': portfolio_id,
              'connection_id': connection_id, 'collection': collection,
              'provider': minimal['provenance']['provider_id'],
              'source_account_key': None, 'kind': None, 'record_kind': None,
              'source_id': None, 'observation_id': ''}
    if collection == 'records':
        source.update(kind=row['source_kind'], source_id=row['identity']['source_id'],
                      observation_id=row['identity']['observation_id'])
        account = row['source_account_local_id']
        revision = row['identity']['revision']
    elif collection == 'coverage':
        source.update(kind='coverage', record_kind=row['kind'], source_id=row['scope_id'],
                      observation_id=row['observation_id'])
        account = row['account_local_id']
        revision = row['revision']
    else:
        source.update(kind='snapshot' if collection == 'snapshots' else 'membership',
                      source_id=row['source_id'] if collection == 'snapshots' else row['scope_id'])
        account = None
        revision = row['revision']
    if account is not None:
        source['source_account_key'] = minimal['accounts'][int(account)]['source_account_key']
    return validate({'version': 1, 'source': source, 'revision': revision}, 'SourceRevisionKey')


def _sorted_refs(items):
    return sorted(items, key=encode)


def _time_material(value):
    """Exclude only the archive pointer declared by the legacy time schema."""
    return {key: deepcopy(item) for key, item in value.items()
            if not (value['tag'] == 'legacy_unspecified' and key == 'legacy')}


def _selector_material(value):
    if value['tag'] == 'point':
        return {'tag': 'point', 'at': _time_material(value['at'])}
    return {**value, 'start': _time_material(value['start']), 'end': _time_material(value['end'])}


def project_record(record, mappings):
    """Remove only declared lineage fields, preserving all typed financial facts."""
    def convert(value):
        if isinstance(value, list):
            return [convert(x) for x in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in {'account_local_id', 'source_account_local_id', 'asset_local_id'}:
                kind, name = {'account_local_id': ('account', 'account'),
                              'source_account_local_id': ('account', 'source_account'),
                              'asset_local_id': ('instrument', 'instrument')}[key]
                result[name] = None if item is None else mappings.reference(kind, item)
            else:
                result[key] = convert(item)
        return result
    result = convert(deepcopy(record))
    result.pop('local_id')
    result.pop('lifecycle_reference', None)
    result['identity'] = {k: record['identity'][k] for k in ('source_id', 'observation_id')}
    time_field = 'as_of' if record['record_type'] == 'position' else 'event_time'
    result[time_field] = _time_material(record[time_field])
    if result.get('lifecycle') is not None:
        for field in ('created_at', 'completed_at', 'sent_at'):
            if record['lifecycle'][field] is not None:
                result['lifecycle'][field] = _time_material(record['lifecycle'][field])
    return result


def financial_projection(minimal, collection, local_id, mappings, *, scope):
    """Return the exact version-one material preimage for one admitted source row."""
    if collection == 'membership':
        row = minimal['membership']
        if row is None or local_id != '0':
            raise IngestionError('import_invalid', '$.membership')
        return {'scope_id': row['scope_id'], 'status': row['status'], 'basis': row['basis'],
                'accounts': _sorted_refs([mappings.reference('account', x)
                                          for x in row['account_local_ids']])}
    try:
        row = next(x for x in minimal[collection] if x['local_id'] == local_id)
    except (KeyError, StopIteration):
        raise IngestionError('import_invalid') from None
    if collection == 'records':
        return project_record(row, mappings)
    if collection == 'coverage':
        selector = row['instrument_scope']
        return {'account': mappings.reference('account', row['account_local_id']),
                **{k: row[k] for k in ('kind', 'scope_id', 'status', 'basis', 'observation_id')},
                'time': _selector_material(row['time']),
                'instrument_scope': {'tag': selector['tag'], 'category': selector['category'],
                    'instruments': _sorted_refs([mappings.reference('instrument', x)
                                                for x in selector['asset_local_ids']])}}
    if collection != 'snapshots':
        raise IngestionError('import_invalid')
    def children(name, ids):
        result = []
        for child_id in ids:
            key = source_revision_key(minimal, name, child_id, **scope)['source']
            material = financial_projection(minimal, name, child_id, mappings, scope=scope)
            result.append({'source_key': key, 'financial_digest': digest(material)})
        return sorted(result, key=lambda x: encode(x['source_key']))
    return {'source_id': row['source_id'], 'as_of': _time_material(row['as_of']),
            'accounts': _sorted_refs([mappings.reference('account', x) for x in row['account_local_ids']]),
            'coverage': children('coverage', row['coverage_local_ids']),
            'positions': children('records', row['position_local_ids'])}


@dataclass(frozen=True, slots=True)
class RevisionDecision:
    action: str
    prior_revision_id: str | None
    active: bool


def reconcile_revision(*, incoming_key, incoming_material, change, parent_revision_id,
                       current, exact=None):
    """Classify a chain using full key bytes and an explicit current parent.

    `current` and `exact` are trusted accepted-row projections from the same scoped
    basis. The database must revalidate those pins before applying any decision.
    """
    incoming_key = validate(incoming_key, 'SourceRevisionKey')
    material_bytes = encode(incoming_material)
    source_bytes = encode(incoming_key['source'])
    # The caller already supplied this exact current key; an omitted optional
    # historical lookup must not allow the key to become its own correction.
    if current is not None and encode(current['source_revision_key']) == encode(incoming_key):
        if encode(current['material']) != material_bytes:
            raise IngestionError('import_conflict')
        if exact is None:
            exact = current
    if exact is not None:
        if encode(exact['source_revision_key']) != encode(incoming_key):
            raise IngestionError('import_conflict')
        if encode(exact['material']) != material_bytes:
            raise IngestionError('import_conflict')
        return RevisionDecision('duplicate', exact['id'], exact['active'])
    if change not in {'original', 'correction', 'void'}:
        raise IngestionError('import_invalid')
    if current is None:
        if change != 'original' or parent_revision_id is not None:
            raise IngestionError('import_conflict')
        return RevisionDecision('append', None, True)
    if encode(current['source_revision_key']['source']) != source_bytes:
        raise IngestionError('import_conflict')
    if change != 'original' or parent_revision_id is not None:
        if parent_revision_id != current['id'] or not current['active']:
            raise IngestionError('import_conflict')
        return RevisionDecision('append', current['id'], change != 'void')
    if encode(current['material']) == material_bytes:
        return RevisionDecision('duplicate', current['id'], current['active'])
    raise IngestionError('import_conflict')


def snapshot_order(incoming_time, current_time, *, same_material=False, explicit_parent=False):
    """Classify observation ordering without manufacturing omitted zero holdings."""
    if current_time is None:
        # Installing the first head still claims current authority. Unknown
        # ordering must take the separate explicit historical-only path.
        compare_time(incoming_time, incoming_time)
        return 'new'
    order = compare_time(incoming_time, current_time)
    if order < 0:
        return 'historical'
    if order > 0:
        return 'new'
    if explicit_parent:
        return 'correction'
    if same_material:
        return 'duplicate'
    raise IngestionError('import_conflict')
