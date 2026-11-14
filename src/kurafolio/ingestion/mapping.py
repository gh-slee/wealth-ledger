"""Explicit scoped entity mapping; this module never selects a target for a user."""
from __future__ import annotations

from .codec import digest, validate
from .contracts import IngestionError

_COLLECTIONS = {'account': 'accounts', 'instrument': 'assets', 'issuer': 'issuers'}


class MappingIndex:
    """Pinned references from an admitted Decisions document, not child UUIDs."""

    def __init__(self, mappings, member_id):
        self._targets = {}
        for row in mappings:
            row = validate(row, 'Mapping')
            if row['member_id'] != member_id:
                continue
            key = row['entity_kind'], row['local_id']
            if key in self._targets:
                raise IngestionError('import_conflict', '$.mappings')
            self._targets[key] = row['target']

    def target(self, kind, local_id):
        try:
            return dict(self._targets[kind, local_id])
        except KeyError:
            raise IngestionError('import_mapping_required', '$.mappings') from None

    def reference(self, kind, local_id):
        row = self.target(kind, local_id)
        return {'id': row['id'], 'version': row['version']}

    def require_complete(self, minimal):
        expected = {(kind, row['local_id']) for kind, collection in _COLLECTIONS.items()
                    for row in minimal[collection]}
        if self._targets.keys() - expected:
            raise IngestionError('import_invalid', '$.mappings')
        if expected - self._targets.keys():
            raise IngestionError('import_mapping_required', '$.mappings')


def _scoped(tenant_id, portfolio_id, kind, value):
    for identifier in (tenant_id, portfolio_id, value):
        validate(identifier, 'UUID')
    return {'tenant_id': tenant_id, 'portfolio_id': portfolio_id, 'kind': kind, 'value': value}


def proposed_body(minimal, kind, local_id, entity_id, tenant_id, portfolio_id, mappings):
    """Derive an immutable proposed entity body from admitted source metadata."""
    try:
        source = next(x for x in minimal[_COLLECTIONS[kind]] if x['local_id'] == local_id)
    except (KeyError, StopIteration):
        raise IngestionError('import_invalid', '$.mappings') from None
    result = {'id': _scoped(tenant_id, portfolio_id, kind, entity_id)}
    if kind == 'account':
        result.update({k: source[k] for k in ('category', 'role', 'label')})
    elif kind == 'issuer':
        result['label'] = source['label']
    else:
        if source['identifier'] is not None and not any(
                x['value'] == source['identifier'] for x in source['identifiers']):
            # An unqualified parser identifier has no reviewed canonical scheme.
            # Retain it in evidence, but do not silently lose it in a new target.
            raise IngestionError('import_evidence_unsupported', '$.mappings')
        result.update({k: source[k] for k in (
            'kind', 'currency', 'ticker', 'mic', 'symbol', 'network',
            'settlement_identity', 'source_descriptor', 'identifiers')})
        if source['kind'] == 'CASH':
            result['symbol'] = None
        if source['kind'] == 'SECURITY':
            result['symbol'] = None
        if source['kind'] == 'CRYPTO' and source['settlement_identity'] is None:
            result['settlement_identity'] = source['network']
        result['issuer'] = (None if source['issuer_local_id'] is None else _scoped(
            tenant_id, portfolio_id, 'issuer', mappings.target(
                'issuer', source['issuer_local_id'])['id']))
        result['evidence_reference'] = minimal['provenance']['evidence_reference']
    result = validate(result, 'EntityBody')
    issuer = result.get('issuer')
    if not compatible(source, result, kind, tenant_id=tenant_id, portfolio_id=portfolio_id,
                      issuer_id=None if issuer is None else issuer['value']):
        raise IngestionError('import_evidence_unsupported', '$.mappings')
    return result


def compatible(source, target, kind, *, tenant_id, portfolio_id, issuer_id=None):
    """Compare identifying fields only; labels never establish financial identity."""
    target = validate(target, 'EntityBody')
    identity = target['id']
    if (identity['tenant_id'], identity['portfolio_id'], identity['kind']) != (
            tenant_id, portfolio_id, kind):
        return False
    if kind == 'account':
        return all(source[k] == target.get(k) for k in ('category', 'role'))
    if kind == 'issuer':
        return source['label'] == target.get('label')
    fields = ('kind', 'currency', 'ticker', 'mic', 'symbol', 'network', 'settlement_identity')
    expected = {k: source[k] for k in fields}
    if source['kind'] == 'CASH':
        expected['symbol'] = None
    if source['kind'] == 'SECURITY':
        expected['symbol'] = None
    if source['kind'] == 'CRYPTO' and expected['settlement_identity'] is None:
        expected['settlement_identity'] = source['network']
    if any(target.get(k) != v for k, v in expected.items()):
        return False
    hints = sorted(source['identifiers'], key=lambda x: (x['scheme'], x['value']))
    if source['identifier'] is not None:
        # The frozen parser's single unqualified identifier cannot establish an
        # equivalence with differently identified native instruments.
        if not any(x['value'] == source['identifier'] for x in target.get('identifiers', [])):
            return False
    elif hints != sorted(target.get('identifiers', []), key=lambda x: (x['scheme'], x['value'])):
        return False
    issuer = target.get('issuer')
    return (None if issuer is None else issuer['value']) == issuer_id


def verify_target_version(body, expected_version):
    if digest(validate(body, 'EntityBody')) != expected_version:
        raise IngestionError('import_stale', '$.mappings[].target.version')
