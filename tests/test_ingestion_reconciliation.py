"""Literal material digests, mapping boundaries and explicit chain decisions."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from wealth_ledger.ingestion.codec import digest, encode
from wealth_ledger.ingestion.contracts import IngestionError
from wealth_ledger.ingestion.mapping import MappingIndex, compatible, proposed_body, verify_target_version
from wealth_ledger.ingestion.reconciliation import (financial_projection, project_record,
    reconcile_revision, snapshot_order, source_revision_key)

ORACLE = json.loads((Path(__file__).parent / 'fixtures/ingestion/oracle.json').read_text())
SCOPE = {'tenant_id': '30000000-0000-4000-8000-000000000001',
         'portfolio_id': '30000000-0000-4000-8000-000000000002',
         'connection_id': '20000000-0000-4000-8000-000000000004'}


def fixture(name):
    return deepcopy(ORACLE[name])


class IngestionReconciliationTests(unittest.TestCase):
    def test_material_and_entity_bodies_match_both_frozen_literal_families(self):
        for native in (False, True):
            with self.subTest(native=native):
                minimal = fixture('minimal-native.json' if native else 'minimal-parser2.json')
                decisions = fixture('decisions-native-first-use.json' if native else 'decisions-first-use.json')
                mappings = decisions['mappings']
                index = MappingIndex(mappings, mappings[0]['member_id'])
                index.require_complete(minimal)
                expected = fixture('financial-projections-native.json' if native else 'financial-projections.json')
                for collection, projection in expected.items():
                    self.assertEqual(projection, financial_projection(minimal, collection, '0', index, scope=SCOPE))
                bodies = fixture('entity-bodies-native.json' if native else 'entity-bodies.json')
                for i, mapping in enumerate(mappings):
                    body = proposed_body(minimal, mapping['entity_kind'], mapping['local_id'],
                        mapping['target']['id'], SCOPE['tenant_id'], SCOPE['portfolio_id'], index)
                    self.assertEqual(bodies['bodies'][i], body)
                    self.assertEqual(bodies['versions'][i], digest(body))

    def test_reordered_entities_preserve_financial_meaning(self):
        case = fixture('reordered-record-counterexample.json')
        for prefix in ('original', 'reordered'):
            mappings = case[prefix + '_mappings']
            index = MappingIndex(mappings, mappings[0]['member_id'])
            material = project_record(case[prefix + '_record'], index)
            self.assertEqual(case['material'], material)
            self.assertEqual(case['material_sha256'], digest(material))

    def test_snapshot_keys_and_material_match_literal_vectors(self):
        for prefix, minimal_name, decision_name in (
                ('snapshot-historical-t1', 'snapshot-t1-minimal.json', 'snapshot-historical-t1-decisions.json'),
                ('snapshot-seed-t2', 'snapshot-t2-complete-minimal.json', 'snapshot-seed-t2-decisions.json')):
            with self.subTest(prefix=prefix):
                minimal = fixture(minimal_name)
                mappings = fixture(decision_name)['mappings']
                index = MappingIndex(mappings, mappings[0]['member_id'])
                for vector in fixture(prefix + '-projections.json')['items']:
                    scope = {k: vector['source_revision_key']['source'][k] for k in SCOPE}
                    actual_key = source_revision_key(minimal, vector['collection'], vector['local_id'], **scope)
                    actual = financial_projection(minimal, vector['collection'], vector['local_id'], index, scope=scope)
                    self.assertEqual(vector['source_revision_key'], actual_key)
                    self.assertEqual(vector['material'], actual)
                    self.assertEqual(vector['sha256'], digest(actual))

    def test_mapping_must_be_explicit_complete_and_member_scoped(self):
        minimal = fixture('minimal-parser2.json')
        mappings = fixture('decisions-first-use.json')['mappings']
        index = MappingIndex(mappings, '30000000-0000-4000-8000-000000000099')
        with self.assertRaises(IngestionError):
            index.require_complete(minimal)
        with self.assertRaises(IngestionError):
            MappingIndex(mappings + [mappings[0]], mappings[0]['member_id'])

    def test_target_labels_do_not_change_identity_but_network_and_scope_do(self):
        minimal = fixture('minimal-native.json')
        source = minimal['assets'][1]
        target = fixture('entity-bodies-native.json')['bodies'][3]
        self.assertTrue(compatible(source, target, 'instrument',
                                   tenant_id=SCOPE['tenant_id'], portfolio_id=SCOPE['portfolio_id']))
        target['source_descriptor'] = 'A different display description'
        self.assertTrue(compatible(source, target, 'instrument',
                                   tenant_id=SCOPE['tenant_id'], portfolio_id=SCOPE['portfolio_id']))
        target['network'] = 'liquid'
        self.assertFalse(compatible(source, target, 'instrument',
                                    tenant_id=SCOPE['tenant_id'], portfolio_id=SCOPE['portfolio_id']))
        target['id']['portfolio_id'] = '30000000-0000-4000-8000-000000000099'
        self.assertFalse(compatible(source, target, 'instrument',
                                    tenant_id=SCOPE['tenant_id'], portfolio_id=SCOPE['portfolio_id']))

    def test_version_checks_preserve_full_canonical_body(self):
        body = fixture('entity-bodies.json')['bodies'][0]
        version = digest(body)
        verify_target_version(body, version)
        body['label'] = 'changed'
        with self.assertRaises(IngestionError):
            verify_target_version(body, version)

    def test_unqualified_identifier_cannot_disappear_in_a_new_proposal(self):
        minimal = fixture('minimal-parser2.json')
        minimal['assets'][1]['identifier'] = 'SYNTHETIC-IDENTIFIER-01'
        mappings = fixture('decisions-first-use.json')['mappings']
        index = MappingIndex(mappings, mappings[0]['member_id'])
        with self.assertRaises(IngestionError) as caught:
            proposed_body(minimal, 'instrument', '1', mappings[3]['target']['id'],
                          SCOPE['tenant_id'], SCOPE['portfolio_id'], index)
        self.assertEqual('import_evidence_unsupported', caught.exception.code)

    def chain(self):
        minimal = fixture('minimal-parser2.json')
        maps = fixture('decisions-first-use.json')['mappings']
        index = MappingIndex(maps, maps[0]['member_id'])
        key = source_revision_key(minimal, 'records', '0', **SCOPE)
        material = project_record(minimal['records'][0], index)
        current = {'id': '80000000-0000-4000-8000-000000000001', 'active': True,
                   'material': material, 'source_revision_key': key}
        return key, material, current

    def test_exact_duplicate_has_no_new_revision(self):
        key, material, current = self.chain()
        result = reconcile_revision(incoming_key=key, incoming_material=material, change='original',
            parent_revision_id=None, current=current, exact=current)
        self.assertEqual('duplicate', result.action)
        self.assertEqual(current['id'], result.prior_revision_id)

    def test_equal_meaning_new_revision_is_duplicate_unless_explicit_correction(self):
        key, material, current = self.chain()
        key = deepcopy(key)
        key['revision'] = 'r2'
        result = reconcile_revision(incoming_key=key, incoming_material=material, change='original',
                                    parent_revision_id=None, current=current)
        self.assertEqual('duplicate', result.action)
        result = reconcile_revision(incoming_key=key, incoming_material=material, change='correction',
                                    parent_revision_id=current['id'], current=current)
        self.assertEqual('append', result.action)

    def test_same_revision_material_change_and_false_hash_identity_conflict(self):
        key, material, current = self.chain()
        altered = deepcopy(material)
        altered['legs'][1]['quantity'] = '0.02000000'
        with self.assertRaises(IngestionError):
            reconcile_revision(incoming_key=key, incoming_material=altered, change='original',
                parent_revision_id=None, current=current, exact=current)
        with self.assertRaises(IngestionError):
            reconcile_revision(incoming_key=key, incoming_material=altered, change='correction',
                parent_revision_id=current['id'], current=current, exact=None)
        wrong_key = deepcopy(key)
        wrong_key['source']['connection_id'] = '20000000-0000-4000-8000-000000000099'
        with self.assertRaises(IngestionError):
            reconcile_revision(incoming_key=wrong_key, incoming_material=material, change='original',
                parent_revision_id=None, current=current, exact=current)

    def test_void_requires_exact_live_parent(self):
        key, material, current = self.chain()
        key = dict(key, revision='r2')
        result = reconcile_revision(incoming_key=key, incoming_material=material, change='void',
                                    parent_revision_id=current['id'], current=current)
        self.assertEqual('append', result.action)
        self.assertFalse(result.active)
        for parent in (None, '80000000-0000-4000-8000-000000000099'):
            with self.assertRaises(IngestionError):
                reconcile_revision(incoming_key=key, incoming_material=material, change='void',
                                    parent_revision_id=parent, current=current)

    def test_snapshot_time_order_and_equal_instant_conflicts(self):
        at = fixture('minimal-parser2.json')['records'][0]['event_time']
        later = dict(at, token='2026-02-01T12:00:00+00:00')
        same = dict(at, token='2026-01-01T07:00:00-05:00')
        self.assertEqual('historical', snapshot_order(at, later))
        self.assertEqual('new', snapshot_order(later, at))
        self.assertEqual('duplicate', snapshot_order(same, at, same_material=True))
        self.assertEqual('correction', snapshot_order(same, at, explicit_parent=True))
        with self.assertRaises(IngestionError):
            snapshot_order(same, at)
        with self.assertRaises(IngestionError):
            snapshot_order({'tag': 'date_only', 'token': '2026-01-01', 'zone': None}, at)

    def test_first_snapshot_head_requires_comparable_time_too(self):
        for at in ({'tag': 'date_only', 'token': '2026-01-01', 'zone': None},
                   {'tag': 'legacy_unspecified', 'token': '2026-01-01T12:00:00+00:00',
                    'zone': None, 'legacy': None}):
            with self.subTest(tag=at['tag']), self.assertRaises(IngestionError) as caught:
                snapshot_order(at, None)
            self.assertEqual('import_conflict', caught.exception.code)
        self.assertEqual('new', snapshot_order(
            {'tag': 'date_only', 'token': '2026-01-01', 'zone': 'America/Toronto'}, None))

    def test_time_lineage_does_not_change_financial_meaning(self):
        legacy = {'tag': 'legacy_unspecified', 'token': '2026-01-01T12:00:00+00:00',
            'zone': None, 'legacy': {'canonical_sha256': '9' * 64,
                'collection': 'records', 'ordinal': 0, 'field': 'occurred_at'}}
        minimal = fixture('minimal-native.json')
        maps = fixture('decisions-native-first-use.json')['mappings']
        index = MappingIndex(maps, maps[0]['member_id'])
        row = minimal['records'][0]
        row['event_time'] = deepcopy(legacy)
        row['lifecycle']['created_at'] = deepcopy(legacy)
        minimal['coverage'][0]['time'] = {'tag': 'point', 'at': deepcopy(legacy)}
        before = {name: financial_projection(minimal, name, '0', index, scope=SCOPE)
                  for name in ('records', 'coverage')}
        row['event_time']['legacy']['canonical_sha256'] = '8' * 64
        row['lifecycle']['created_at']['legacy']['ordinal'] = 1
        minimal['coverage'][0]['time']['at']['legacy']['ordinal'] = 2
        for name in before:
            self.assertEqual(before[name], financial_projection(minimal, name, '0', index, scope=SCOPE))
        self.assertEqual({k: v for k, v in legacy.items() if k != 'legacy'}, before['records']['event_time'])
        row['event_time']['token'] = '2026-01-02T12:00:00+00:00'
        self.assertNotEqual(before['records'], financial_projection(minimal, 'records', '0', index, scope=SCOPE))

    def test_economic_reference_revision_is_preserved_in_material(self):
        minimal = fixture('minimal-native.json')
        maps = fixture('decisions-native-first-use.json')['mappings']
        index = MappingIndex(maps, maps[0]['member_id'])
        row = minimal['records'][0]
        row['economic_references'] = [{'provider': 'synthetic.qa', 'source_account_key': 'crypto',
            'kind': 'crypto_transactions', 'source_id': 'linked-order', 'observation_id': '',
            'revision': 'r1', 'record_kind': None}]
        before = project_record(row, index)
        self.assertEqual('r1', before['economic_references'][0]['revision'])
        row['economic_references'][0]['revision'] = 'r2'
        self.assertNotEqual(before, project_record(row, index))

    def test_snapshot_and_interval_time_material_exclude_only_archive_lineage(self):
        minimal = fixture('snapshot-t1-minimal.json')
        maps = fixture('snapshot-historical-t1-decisions.json')['mappings']
        index = MappingIndex(maps, maps[0]['member_id'])
        legacy = {'tag': 'legacy_unspecified', 'token': '2026-01-01T12:00:00+00:00',
            'zone': None, 'legacy': {'canonical_sha256': '9' * 64,
                'collection': 'snapshots', 'ordinal': 0, 'field': 'as_of'}}
        minimal['snapshots'][0]['as_of'] = deepcopy(legacy)
        minimal['coverage'][0]['time'] = {'tag': 'interval', 'start': deepcopy(legacy),
            'end': deepcopy(legacy), 'start_inclusive': True, 'end_inclusive': True}
        for row in minimal['records']:
            row['as_of'] = deepcopy(legacy)
        before = financial_projection(minimal, 'snapshots', '0', index, scope=SCOPE)
        minimal['snapshots'][0]['as_of']['legacy']['canonical_sha256'] = '8' * 64
        minimal['coverage'][0]['time']['start']['legacy']['ordinal'] = 1
        for row in minimal['records']:
            row['as_of']['legacy']['field'] = 'occurred_at'
        self.assertEqual(before, financial_projection(minimal, 'snapshots', '0', index, scope=SCOPE))
        minimal['coverage'][0]['time']['end_inclusive'] = False
        self.assertNotEqual(before, financial_projection(minimal, 'snapshots', '0', index, scope=SCOPE))


if __name__ == '__main__':
    unittest.main()
