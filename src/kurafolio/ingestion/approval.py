"""Verify review-to-plan bindings without granting database write authority."""
from __future__ import annotations

from .codec import decode, digest, encode, sha256, validate
from .contracts import IngestionError, MAX_SET
from .mapping import MappingIndex, compatible, proposed_body
from .reconciliation import financial_projection


def validate_review_bundle(data, *, stages):
    """Check canonical bytes, all review content hashes and exact plan bindings.

    Exact stage bytes are mandatory: rehashing a display is not evidence that its
    financial contents are truthful. Current user/source authority, database generations, accepted chain references
    and head compare-and-swap checks must still run in the acceptance transaction.
    """
    bundle = decode(data, 'ReviewBundle', limit=MAX_SET)
    review, plan = bundle['review'], bundle['plan']
    rows = review['content']['rows']
    if [x['ordinal'] for x in rows] != [str(i) for i in range(len(rows))]:
        raise IngestionError('import_invalid', '$.review.content.rows')
    if review['content_digest'] != digest(review['content']):
        raise IngestionError('import_invalid', '$.review.content_digest')
    _review_evidence(review, plan, stages)
    if review['state'] != 'READY':
        if plan is not None or review['plan_digest'] is not None:
            raise IngestionError('import_invalid', '$.plan')
        return bundle
    if plan is None or review['plan_digest'] != digest(plan):
        raise IngestionError('import_invalid', '$.review.plan_digest')
    pairs = {'id': 'preview_id', 'set_id': 'set_id', 'set_revision': 'expected_set_revision',
             'accepted_generation': 'expected_accepted_generation',
             'mapping_generation': 'expected_mapping_generation',
             'control_generation': 'expected_control_generation', 'expires_at': 'expires_at',
             'content_digest': 'review_content_digest'}
    for left, right in pairs.items():
        if review[left] != plan[right]:
            raise IngestionError('import_invalid', '$.plan.' + right)
    for type_, key, collection in (('mapping', 'mapping', 'mappings'),
                                  ('authority', 'authority', 'authorities'),
                                  ('parent', 'parent', 'parents'),
                                  ('effect', 'effect', 'facts'), ('head', 'head', 'heads')):
        disclosed = [x[key] for x in rows if x['type'] == type_]
        if disclosed != plan[collection]:
            raise IngestionError('import_invalid', '$.review.content.rows')
    if any(x['type'] == 'fact' and (x['action'] == 'conflict' or x['required_decision'] is not None)
           for x in rows):
        raise IngestionError('import_invalid', '$.review.state')
    verify_staged_material(plan, stages)
    return bundle


def _review_evidence(review, plan, stages):
    if not 1 <= len(stages) <= 4:
        raise IngestionError('import_invalid', '$.review.content')
    evidence, entities, facts = {}, {}, {}
    tables = {'account': 'accounts', 'instrument': 'assets', 'issuer': 'issuers'}
    for member_id, data in stages.items():
        validate(member_id, 'UUID')
        minimal = evidence[member_id] = decode(data)
        for kind, collection in tables.items():
            entities.update({(member_id, kind, x['local_id']): x for x in minimal[collection]})
        for collection in ('records', 'coverage', 'snapshots'):
            facts.update({(member_id, collection, x['local_id']): x for x in minimal[collection]})
        if minimal['membership'] is not None:
            facts[member_id, 'membership', '0'] = minimal['membership']
    disclosed_entities, disclosed_facts, candidate_keys = set(), set(), set()
    candidates = [x['candidate'] for x in review['content']['rows'] if x['type'] == 'target_candidate']
    for row in review['content']['rows']:
        if row['type'] == 'source_entity':
            key = row['member_id'], row['entity_kind'], row['local_id']
            if key in disclosed_entities or entities.get(key) != row['source']:
                raise IngestionError('import_invalid', '$.review.content.rows')
            disclosed_entities.add(key)
        elif row['type'] == 'fact':
            key = row['member_id'], row['collection'], row['local_id']
            if key not in facts or key in disclosed_facts:
                raise IngestionError('import_invalid', '$.review.content.rows')
            if row['collection'] == 'records':
                valid = row['record'] == facts[key] and row['scope'] is None
            else:
                valid = row['scope'] == facts[key] and row['record'] is None
            if not valid:
                raise IngestionError('import_invalid', '$.review.content.rows')
            disclosed_facts.add(key)
        elif row['type'] == 'target_candidate':
            candidate = row['candidate']
            key = candidate['member_id'], candidate['entity_kind'], candidate['local_id']
            target, body = candidate['target'], candidate['body']
            candidate_key = key + (target['mode'], target['id'], target['version'])
            if key not in entities or candidate_key in candidate_keys or digest(body) != target['version']:
                raise IngestionError('import_invalid', '$.review.content.rows')
            candidate_keys.add(candidate_key)
            identity = body['id']
            if identity['kind'] != candidate['entity_kind'] or identity['value'] != target['id']:
                raise IngestionError('import_invalid', '$.review.content.rows')
            # READY has an exact server-derived scope in its Plan. Initial
            # candidate scope is rechecked against the trusted request basis by
            # the database preparation function, not by a child declaration.
            tenant_id = plan['tenant_id'] if plan else identity['tenant_id']
            portfolio_id = plan['portfolio_id'] if plan else identity['portfolio_id']
            issuer = body.get('issuer')
            issuer_id = None if issuer is None else issuer['value']
            if not compatible(entities[key], body, key[1], tenant_id=tenant_id,
                              portfolio_id=portfolio_id, issuer_id=issuer_id):
                raise IngestionError('import_conflict', '$.review.content.rows')
            if target['mode'] == 'proposed':
                mappings = [] if plan is None else list(plan['mappings'])
                if key[1] == 'instrument' and entities[key]['issuer_local_id'] is not None:
                    issuer_local = entities[key]['issuer_local_id']
                    if not any(m['member_id'] == key[0] and m['entity_kind'] == 'issuer'
                               and m['local_id'] == issuer_local for m in mappings):
                        matches = [c for c in candidates if c['member_id'] == key[0]
                                   and c['entity_kind'] == 'issuer' and c['local_id'] == issuer_local
                                   and c['target']['id'] == issuer_id]
                        if len(matches) != 1:
                            raise IngestionError('import_mapping_required', '$.review.content.rows')
                        mappings.append({k: matches[0][k] for k in (
                            'member_id', 'entity_kind', 'local_id', 'target')})
                index = MappingIndex(mappings, key[0])
                expected = proposed_body(evidence[key[0]], key[1], key[2], target['id'],
                                         tenant_id, portfolio_id, index)
                if expected != body:
                    raise IngestionError('import_conflict', '$.review.content.rows')
    if disclosed_entities != entities.keys() or (plan is not None and disclosed_facts != facts.keys()):
        raise IngestionError('import_invalid', '$.review.content.rows')
    if plan is not None:
        for mapping in plan['mappings']:
            target = mapping['target']
            key = (mapping['member_id'], mapping['entity_kind'], mapping['local_id'],
                   target['mode'], target['id'], target['version'])
            if key not in candidate_keys:
                raise IngestionError('import_invalid', '$.review.content.rows')


def verify_staged_material(plan, stages):
    """Recompute source material from exact stage bytes, never from browser facts.

    `stages` is the trusted basis map member UUID -> canonical Minimal bytes. It
    must be read under an active scoped worker lease and pinned generations.
    This check is necessary but does not replace transaction-time authorization.
    """
    plan = validate(plan, 'Plan')
    if not 1 <= len(plan['inputs']) <= 4:
        raise IngestionError('import_invalid', '$.plan.inputs')
    inputs = {x['member_id']: x for x in plan['inputs']}
    if len(inputs) != len(plan['inputs']) or inputs.keys() != stages.keys():
        raise IngestionError('import_invalid', '$.plan.inputs')
    pinned = {x['member_id']: x for x in plan['pinned_sources']}
    if len(pinned) != len(plan['pinned_sources']) or pinned.keys() != stages.keys():
        raise IngestionError('import_invalid', '$.plan.pinned_sources')
    indexes, evidence, expected_facts = {}, {}, set()
    for member_id, raw in stages.items():
        minimal = decode(raw)
        provenance = minimal['provenance']
        wanted = inputs[member_id]
        if (sha256(raw) != wanted['stage_digest']
                or provenance['raw_sha256'] != wanted['raw_digest']
                or provenance['discovery_sha256'] != wanted['discovery_digest']
                or provenance['installation_id'] != pinned[member_id]['installation_id']
                or provenance['wrapper_profile_digest'] != pinned[member_id]['wrapper_profile_digest']
                or provenance['format_selection'] != pinned[member_id]['format_version']):
            raise IngestionError('import_stale', '$.plan.inputs')
        index = MappingIndex(plan['mappings'], member_id)
        index.require_complete(minimal)
        indexes[member_id], evidence[member_id] = index, minimal
        for collection in ('records', 'coverage', 'snapshots'):
            expected_facts.update((member_id, collection, x['local_id']) for x in minimal[collection])
        if minimal['membership'] is not None:
            expected_facts.add((member_id, 'membership', '0'))
    verify_proposals(plan, evidence, indexes)
    actual_facts = [(x['member_id'], x['collection'], x['local_id']) for x in plan['facts']]
    if len(actual_facts) != len(set(actual_facts)) or set(actual_facts) != expected_facts:
        raise IngestionError('import_invalid', '$.plan.facts')
    for effect in plan['facts']:
        member_id = effect['member_id']
        scope = {'tenant_id': plan['tenant_id'], 'portfolio_id': plan['portfolio_id'],
                 'connection_id': pinned[member_id]['connection_id']}
        material = financial_projection(evidence[member_id], effect['collection'], effect['local_id'],
                                        indexes[member_id], scope=scope)
        if digest(material) != effect['financial_digest']:
            raise IngestionError('import_conflict', '$.plan.facts[].financial_digest')
    return True


def verify_proposals(plan, evidence, indexes):
    """Check every proposed body and shared target without accepting an entity."""
    bodies, proposed = {}, {}
    for mapping in plan['mappings']:
        member_id = mapping['member_id']
        if member_id not in evidence:
            raise IngestionError('import_invalid', '$.plan.mappings')
        if mapping['target']['mode'] != 'proposed':
            continue
        kind, local_id = mapping['entity_kind'], mapping['local_id']
        target = mapping['target']
        body = proposed_body(evidence[member_id], kind, local_id, target['id'],
                             plan['tenant_id'], plan['portfolio_id'], indexes[member_id])
        version = digest(body)
        if version != target['version']:
            raise IngestionError('import_conflict', '$.plan.new_entities')
        key = kind, target['id']
        if key in bodies and bodies[key] != body:
            raise IngestionError('import_conflict', '$.plan.new_entities')
        bodies[key] = body
        proposed[member_id, kind, local_id] = target
    declared = set()
    for row in plan['new_entities']:
        key = row['kind'], row['id']
        target = proposed.get((row['member_id'], row['kind'], row['local_id']))
        if (key in declared or key not in bodies or target is None
                or target['id'] != row['id'] or target['version'] != row['version']):
            raise IngestionError('import_invalid', '$.plan.new_entities')
        declared.add(key)
    if declared != bodies.keys():
        raise IngestionError('import_invalid', '$.plan.new_entities')
