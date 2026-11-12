"""Literal synthetic contract vectors and hostile evidence boundaries."""
from copy import deepcopy
from decimal import localcontext
import hashlib
import json
from pathlib import Path
import unittest

from kurafolio.ingestion.codec import decode, digest, encode, validate
from kurafolio.ingestion.contracts import IngestionError, definition
from kurafolio.ingestion.approval import validate_review_bundle, verify_staged_material

ORACLE = json.loads((Path(__file__).parent / 'fixtures/ingestion/oracle.json').read_text())


def fixture(name):
    return deepcopy(ORACLE[name])


def parser_stages():
    return {'20000000-0000-4000-8000-000000000001': encode(fixture('minimal-parser2.json'))}


class IngestionContractTests(unittest.TestCase):
    def test_all_minimal_families(self):
        names = [n for n in ORACLE if n.startswith('minimal-') or n.endswith('-minimal.json')]
        self.assertEqual(13, len(names))
        for name in names:
            with self.subTest(name=name):
                obj = fixture(name)
                self.assertEqual(obj, decode(encode(obj)))

    def test_code_owned_closed_schemas(self):
        for namespace, definitions in ORACLE['codec-shapes'].items():
            for name, expected in definitions.items():
                with self.subTest(namespace=namespace, name=name):
                    self.assertEqual(expected, definition(name, namespace))
                    altered = definition(name, namespace)
                    altered.clear()
                    self.assertEqual(expected, definition(name, namespace))

    def test_decisions_basis_rows_keep_collection_types_and_positive_revision(self):
        decisions = fixture('decisions-first-use.json')
        header = {'kind': 'decisions_header', 'decision_revision': '1', 'digest': digest(decisions),
                  'version': 1, 'operation_id': decisions['operation_id'], 'expected_set_revision': '1',
                  'counts': {'authorities': 0, 'mappings': 4, 'new_entities': 4, 'parents': 0}}
        self.assertEqual(header, validate(header, 'BasisRow'))
        item = {'kind': 'decision_item', 'collection': 'mappings', 'ordinal': 0, 'value': decisions['mappings'][0]}
        self.assertEqual(item, validate(item, 'BasisRow'))
        for bad in (dict(item, collection='parents'), dict(item, ordinal=128), dict(item, extra=True),
                    dict(header, decision_revision='0'), dict(header, decision_revision='9223372036854775808')):
            with self.subTest(row=bad['kind']):
                self.assert_blocked(bad, name='BasisRow', code='import_invalid')

    def test_key_preimages_match_literal_bytes_and_hashes(self):
        for row in fixture('key-preimages.json')['vectors']:
            with self.subTest(name=row['name']):
                value = validate(row['preimage'], row['schema'])
                self.assertEqual(row['canonical_utf8'].encode(), encode(value))
                self.assertEqual(row['sha256'], digest(value))

    def assert_blocked(self, value, *, name='Minimal', code=None):
        with self.assertRaises(IngestionError) as caught:
            decode(value if type(value) is bytes else encode(value), name)
        if code is not None:
            self.assertEqual(code, caught.exception.code)
        self.assertNotIn('SECRET_SENTINEL', str(caught.exception))
        self.assertNotIn('SECRET_SENTINEL', caught.exception.field)

    def test_rejects_duplicate_keys_float_nonfinite_and_noncanonical_encoding(self):
        for raw in (b'{"x":1,"x":2}', b'1.0', b'1e2', b'NaN', b'Infinity', b'\xff',
                    b'{}\n', b'{ "x":1}', br'{"x":"\ud800"}'):
            with self.subTest(raw=raw):
                self.assert_blocked(raw)

    def test_limits_are_checked_before_decode(self):
        self.assert_blocked(b'x' * (4 * 1024 * 1024 + 1), code='import_limit')
        self.assert_blocked(b'[' * 33 + b'0' + b']' * 33, code='import_limit')

    def test_unknown_fields_and_required_nulls(self):
        obj = fixture('minimal-parser2.json')
        obj['records'][0]['SECRET_SENTINEL'] = 'SECRET_SENTINEL'
        self.assert_blocked(obj)
        obj = fixture('minimal-parser2.json')
        del obj['records'][0]['fees']
        self.assert_blocked(obj)

    def test_versions_are_not_booleans(self):
        obj = fixture('minimal-parser2.json')
        obj['version'] = True
        self.assert_blocked(obj)

    def test_decimal_profile_is_lexical_and_ambient_precision_independent(self):
        with localcontext() as ctx:
            ctx.prec = 2
            for token in ('-0.00000000', '1.230000', '0.' + '0' * 23 + '1', '9' * 38,
                          '0.' + '0' * 230):
                self.assertEqual(token, validate(token, 'Decimal'))
        for token in ('+1', '01', '-01', '1e-8', 'NaN', '9' * 39, '0.' + '0' * 24 + '1',
                      '0.' + '1' * 39, '0.' + '0' * 255):
            with self.subTest(token=token):
                self.assert_blocked(token, name='Decimal')

    def test_counter_overflow_and_noncanonical_uuid(self):
        self.assertEqual('9223372036854775807', validate('9223372036854775807', 'Counter'))
        for token in ('9223372036854775808', '-1', '01', '1e2'):
            self.assert_blocked(token, name='Counter')
        for token in ('00000000-0000-0000-0000-000000000000',
                      'ABCDEF00-0000-4000-8000-000000000001'):
            self.assert_blocked(token, name='UUID')

    def test_subsatoshi_rejected_without_rounding(self):
        obj = fixture('minimal-parser2.json')
        obj['records'][0]['legs'][1]['quantity'] = '0.010000001'
        self.assert_blocked(obj)

    def test_local_graph_and_provider_cannot_be_rebound(self):
        for collection in ('accounts', 'assets', 'records', 'coverage'):
            obj = fixture('minimal-parser2.json')
            obj[collection][0]['local_id'] = '7'
            self.assert_blocked(obj)
        obj = fixture('minimal-parser2.json')
        obj['records'][0]['legs'][0]['account_local_id'] = '12'
        self.assert_blocked(obj)
        obj = fixture('minimal-parser2.json')
        obj['accounts'][0]['provider'] = 'another.provider'
        self.assert_blocked(obj)

    def test_time_calendar_fraction_and_offset_checked(self):
        base = fixture('minimal-parser2.json')['provenance']['evidence_at']
        for token in ('2026-02-30T13:00:00+00:00', '2026-02-02T13:00:00+23:60',
                      '2026-02-02T13:00:00-00:00', '2026-02-02T13:00:00.1+00:00'):
            obj = dict(base, token=token)
            self.assert_blocked(obj, name='Time')

    def test_lifecycle_sidecar_required_when_legacy_reference_exists(self):
        obj = fixture('metadata-native-minimal.json')
        obj['records'][0]['lifecycle'] = None
        self.assert_blocked(obj, code='import_evidence_unsupported')

    def test_diagnostic_context_is_typed(self):
        obj = fixture('minimal-parser2.json')
        obj['provenance']['diagnostics'] = [{'code': 'wallet_fees_unknown', 'severity': 'warning',
            'row_count': '2', 'duplicate_count': None, 'record_local_ids': []}]
        self.assert_blocked(obj)
        obj['provenance']['diagnostics'][0].update(row_count=None, record_local_ids=['999'])
        self.assert_blocked(obj)

    def test_membership_null_is_not_a_fabricated_declaration(self):
        obj = decode(encode(fixture('minimal-native.json')))
        self.assertIsNone(obj['membership'])
        self.assertIsNone(obj['records'][0]['fees'])

    def test_identity_and_claim_selectors(self):
        obj = fixture('minimal-parser2.json')
        obj['records'][0]['identity']['change'] = 'correction'
        self.assert_blocked(obj)
        vectors = fixture('key-preimages.json')['vectors']
        for vector in vectors:
            if vector['schema'] != 'SourceKey':
                continue
            obj = vector['preimage']
            obj['record_kind'] = 'activity' if obj['record_kind'] is None else None
            self.assert_blocked(obj, name='SourceKey')

    def test_snapshot_omission_does_not_create_a_zero_record(self):
        obj = decode(encode(fixture('snapshot-t2-empty-complete-minimal.json')))
        self.assertEqual([], obj['records'])
        self.assertEqual([], obj['snapshots'][0]['position_local_ids'])
        self.assertEqual('complete', obj['coverage'][0]['status'])

    def test_snapshot_missing_and_foreign_positions_are_rejected(self):
        obj = fixture('snapshot-t2-complete-minimal.json')
        obj['snapshots'][0]['position_local_ids'] = []
        self.assert_blocked(obj)
        obj = fixture('snapshot-t2-complete-minimal.json')
        obj['records'][0]['identity']['observation_id'] = 'other-observation'
        self.assert_blocked(obj)

    def test_review_bundles_preserve_literal_content_and_plan_bindings(self):
        for name in ('review-bundle-first-use.json', 'review-bundle-initial.json'):
            obj = fixture(name)
            self.assertEqual(obj, validate_review_bundle(encode(obj), stages=parser_stages()))
        ready = fixture('review-bundle-first-use.json')
        member = ready['plan']['inputs'][0]['member_id']
        self.assertTrue(verify_staged_material(ready['plan'],
            {member: encode(fixture('minimal-parser2.json'))}))

    def test_all_eleven_literal_ready_review_and_stage_families(self):
        minimals = {hashlib.sha256(encode(value)).hexdigest(): encode(value)
                    for name, value in ORACLE.items()
                    if name.startswith('minimal-') or name.endswith('-minimal.json')}
        pairs = [('plan-first-use.json', 'review-parser2-ready.json'),
                 ('plan-native-first-use.json', 'review-native-ready.json'),
                 ('metadata-native-plan.json', 'review-metadata-native-ready.json'),
                 ('mixed-set-plan.json', 'mixed-set-review.json'),
                 ('authority-only-plan.json', 'authority-only-review.json')]
        pairs.extend((name, name[:-10] + '-review.json') for name in ORACLE
                     if name.startswith(('branch-', 'snapshot-seed-', 'snapshot-historical-'))
                     and name.endswith('-plan.json'))
        self.assertEqual(11, len(pairs))
        for planfile, reviewfile in pairs:
            with self.subTest(plan=planfile):
                plan = fixture(planfile)
                stages = {row['member_id']: minimals[row['stage_digest']] for row in plan['inputs']}
                bundle = {'version': 1, 'plan': plan, 'review': fixture(reviewfile)}
                self.assertEqual(bundle, validate_review_bundle(encode(bundle), stages=stages))

    def test_nonready_review_cannot_carry_an_executable_plan(self):
        obj = fixture('review-bundle-initial.json')
        obj['plan'] = fixture('plan-first-use.json')
        with self.assertRaises(IngestionError):
            validate_review_bundle(encode(obj), stages=parser_stages())

    def test_review_omission_fails_even_if_outer_hashes_are_recomputed(self):
        obj = fixture('review-bundle-first-use.json')
        obj['review']['content']['rows'] = [x for x in obj['review']['content']['rows']
                                           if x['type'] != 'effect']
        for i, row in enumerate(obj['review']['content']['rows']):
            row['ordinal'] = str(i)
        obj['review']['content_digest'] = digest(obj['review']['content'])
        obj['plan']['review_content_digest'] = obj['review']['content_digest']
        obj['review']['plan_digest'] = digest(obj['plan'])
        with self.assertRaises(IngestionError):
            validate_review_bundle(encode(obj), stages=parser_stages())

    def test_rehashed_disclosed_facts_and_candidate_bodies_must_match_stages(self):
        for kind in ('quantity', 'network', 'candidate', 'omit-fact'):
            obj = fixture('review-bundle-first-use.json')
            rows = obj['review']['content']['rows']
            if kind == 'quantity':
                row = next(r for r in rows if r['type'] == 'fact' and r['collection'] == 'records')
                row['record']['legs'][1]['quantity'] = '0.99000000'
                row['record']['lifecycle']['payout']['quantity'] = '0.99000000'
            elif kind == 'network':
                row = next(r for r in rows if r['type'] == 'source_entity' and r['entity_kind'] == 'instrument'
                           and r['local_id'] == '1')
                row['source']['network'] = 'liquid'
            elif kind == 'candidate':
                row = next(r for r in rows if r['type'] == 'target_candidate'
                           and r['candidate']['entity_kind'] == 'instrument')
                row['candidate']['body']['currency'] = 'USD'
            else:
                rows[:] = [r for r in rows if not (r['type'] == 'fact' and r['collection'] == 'records')]
            for i, row in enumerate(rows):
                row['ordinal'] = str(i)
            obj['review']['content_digest'] = digest(obj['review']['content'])
            obj['plan']['review_content_digest'] = obj['review']['content_digest']
            obj['review']['plan_digest'] = digest(obj['plan'])
            with self.subTest(kind=kind), self.assertRaises(IngestionError):
                validate_review_bundle(encode(obj), stages=parser_stages())

    def test_buy_sign_and_acquired_asset_are_checked_without_lifecycle(self):
        obj = fixture('minimal-parser2.json')
        obj['records'][0]['lifecycle'] = None
        obj['records'][0]['legs'][1]['quantity'] = '-0.01000000'
        self.assert_blocked(obj)
        obj = fixture('minimal-parser2.json')
        obj['records'][0]['legs'][1]['asset_local_id'] = '0'
        obj['records'][0]['lifecycle']['payout']['asset_local_id'] = '0'
        self.assert_blocked(obj)

    def test_completed_lifecycle_needs_completion_and_chronology(self):
        obj = fixture('minimal-parser2.json')
        obj['records'][0]['lifecycle']['completed_at'] = None
        self.assert_blocked(obj)
        obj = fixture('minimal-parser2.json')
        obj['records'][0]['lifecycle']['created_at']['token'] = '2026-01-02T11:00:00+00:00'
        self.assert_blocked(obj)

    def test_accepted_material_cannot_be_taken_from_browser_substitution(self):
        obj = fixture('review-bundle-first-use.json')
        plan = obj['plan']
        member = plan['inputs'][0]['member_id']
        stages = {member: encode(fixture('minimal-parser2.json'))}
        plan['facts'][0]['financial_digest'] = 'f' * 64
        with self.assertRaises(IngestionError):
            verify_staged_material(plan, stages)
        plan = fixture('plan-first-use.json')
        plan['facts'] = plan['facts'][1:]
        with self.assertRaises(IngestionError):
            verify_staged_material(plan, stages)

    def test_complete_selected_set_is_required(self):
        plan = fixture('plan-first-use.json')
        with self.assertRaises(IngestionError):
            verify_staged_material(plan, {})

    def test_activity_coverage_and_native_currencies_remain_consistent(self):
        obj = fixture('minimal-parser2.json')
        obj['coverage'][0]['time']['end']['token'] = '2026-01-01T11:59:59+00:00'
        self.assert_blocked(obj)
        obj = fixture('snapshot-t2-complete-minimal.json')
        obj['records'][0]['market_value']['currency'] = 'USD'
        self.assert_blocked(obj)

    def test_matching_unknown_time_is_retained_without_head_ordering(self):
        for at in ({'tag': 'date_only', 'token': '2026-01-01', 'zone': None},
                   {'tag': 'legacy_unspecified', 'token': 'source date unavailable',
                    'zone': None, 'legacy': None}):
            obj = fixture('snapshot-t1-minimal.json')
            obj['coverage'][0]['time'] = {'tag': 'point', 'at': deepcopy(at)}
            obj['snapshots'][0]['as_of'] = deepcopy(at)
            for row in obj['records']:
                row['as_of'] = deepcopy(at)
            with self.subTest(tag=at['tag']):
                self.assertEqual(obj, decode(encode(obj)))

    def test_empty_snapshot_requires_containing_selected_coverage(self):
        obj = fixture('snapshot-t2-empty-complete-minimal.json')
        at = obj['snapshots'][0]['as_of']
        interval = {'tag': 'interval', 'start': deepcopy(at), 'end': deepcopy(at),
                    'start_inclusive': True, 'end_inclusive': True}
        obj['coverage'][0]['time'] = interval
        self.assertEqual(obj, decode(encode(obj)))
        for field in ('start_inclusive', 'end_inclusive'):
            altered = deepcopy(obj)
            altered['coverage'][0]['time'][field] = False
            self.assert_blocked(altered, code='import_invalid')
        for token in ('2026-01-30T12:00:00+00:00', '2026-02-02T12:00:00+00:00'):
            altered = deepcopy(obj)
            for field in ('start', 'end'):
                altered['coverage'][0]['time'][field]['token'] = token
            self.assert_blocked(altered, code='import_invalid')

    def cash_input(self):
        obj = fixture('minimal-native.json')
        obj['records'][0].update(kind='FUNDING', source_kind='cash_flows', source_type='deposit',
            legs=[], lifecycle=None, acquisition_cost=None, acquisition_cost_cad=None,
            cash_flow={'cash_amount': {'amount': '100.00', 'currency': 'CAD'}, 'direction': 'in',
                'boundary': 'external', 'transfer_reference': None, 'counterpart': None,
                'cash_leg_of': None})
        obj['coverage'][0]['kind'] = 'cash_flows'
        return obj

    def test_cash_amount_direction_presence_and_legs_are_checked(self):
        obj = self.cash_input()
        self.assertEqual(obj, decode(encode(obj)))
        # Frozen cash-flow coverage has no instrument leg to constrain. Retain
        # an explicit category scope rather than silently requiring 'all'.
        obj['coverage'][0]['instrument_scope'] = {
            'tag': 'category', 'category': 'CASH', 'asset_local_ids': []}
        self.assertEqual(obj, decode(encode(obj)))
        for token in ('0', '-0', '-1.00'):
            altered = self.cash_input()
            altered['records'][0]['cash_flow']['cash_amount']['amount'] = token
            self.assert_blocked(altered, code='import_invalid')
        for change in ('missing', 'legs', 'direction', 'type'):
            altered = self.cash_input()
            row = altered['records'][0]
            if change == 'missing':
                row['cash_flow'] = None
            elif change == 'legs':
                row['legs'] = fixture('minimal-native.json')['records'][0]['legs']
            elif change == 'direction':
                row['cash_flow']['direction'] = 'out'
            else:
                row['source_type'] = 'withdrawal'
            with self.subTest(change=change):
                self.assert_blocked(altered, code='import_invalid')

    def test_cash_purchase_links_require_explicit_internal_revision(self):
        obj = self.cash_input()
        link = {'provider': 'synthetic.qa', 'source_account_key': 'crypto',
            'kind': 'crypto_transactions', 'source_id': 'linked-order', 'observation_id': '',
            'revision': 'r1', 'record_kind': None}
        obj['records'][0]['cash_flow'].update(boundary='internal', cash_leg_of=link)
        self.assertEqual(obj, decode(encode(obj)))
        for change in ('boundary', 'kind', 'revision'):
            altered = deepcopy(obj)
            if change == 'boundary':
                altered['records'][0]['cash_flow']['boundary'] = 'external'
            else:
                altered['records'][0]['cash_flow']['cash_leg_of'][change] = (
                    'holdings' if change == 'kind' else None)
            self.assert_blocked(altered, code='import_invalid')

    def test_generic_source_kind_support_and_reference_invariants(self):
        cases = []
        for source_type in ('sale', 'unknown source'):
            obj = fixture('minimal-native.json')
            obj['records'][0].update(source_type=source_type, lifecycle=None)
            cases.append(obj)
        for support in ({'classification': 'supported_shape', 'reasons': ['unsupported_activity']},
                        {'classification': 'unsupported', 'reasons': []},
                        {'classification': 'unsupported',
                         'reasons': ['unsupported_activity', 'unsupported_activity']}):
            obj = fixture('minimal-native.json')
            obj['records'][0]['support'] = support
            cases.append(obj)
        for kind, source_type, status, source_status in (
                ('UNSUPPORTED', 'unknown', 'completed', 'completed'),
                ('CORPORATE_ACTION', 'corporate_action', 'completed', 'completed'),
                ('BUY', 'purchase', 'unsupported', 'unknown')):
            obj = fixture('minimal-native.json')
            obj['records'][0].update(kind=kind, source_type=source_type, status=status,
                                    source_status=source_status, lifecycle=None)
            cases.append(obj)
        for obj in cases:
            self.assert_blocked(obj, code='import_invalid')
        obj = fixture('minimal-native.json')
        obj['records'][0]['cash_flow'] = self.cash_input()['records'][0]['cash_flow']
        self.assert_blocked(obj, code='import_invalid')

    def test_position_support_accumulates_reasons_and_void_is_not_a_position(self):
        obj = fixture('snapshot-t1-minimal.json')
        obj['assets'][0]['kind'] = 'UNSUPPORTED'
        obj['records'][0]['quantity'] = '-1'
        for reasons in ([], ['signed_position'], ['unsupported_instrument']):
            altered = deepcopy(obj)
            altered['records'][0]['support'] = {'classification': 'unsupported' if reasons
                else 'supported_shape', 'reasons': reasons}
            self.assert_blocked(altered, code='import_invalid')
        obj['records'][0]['support'] = {'classification': 'unsupported',
            'reasons': ['signed_position', 'unsupported_instrument']}
        self.assertEqual(obj, decode(encode(obj)))
        obj['records'][0]['identity'].update(change='void', revision_reason='source void',
            parent={'provider': 'synthetic.qa', 'source_account_key': 'investment',
                'kind': 'holdings', 'source_id': 'A', 'observation_id': 's1',
                'revision': 'r0', 'record_kind': None})
        self.assert_blocked(obj, code='import_invalid')

    def test_empty_complete_observation_still_requires_an_explicit_account(self):
        obj = fixture('snapshot-t2-empty-complete-minimal.json')
        obj['snapshots'][0].update(account_local_ids=[], coverage_local_ids=[])
        self.assert_blocked(obj, code='import_invalid')


if __name__ == '__main__':
    unittest.main()
