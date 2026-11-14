"""Execute frozen parser admission with literal vectors and public demo CSVs."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import unittest

from kurafolio import source_v2 as parser
from kurafolio.data_sources.compatibility_v1 import builtin_descriptors
from kurafolio.data_sources.contract_v1 import installation_id, primitive
from kurafolio.ingestion.codec import decode, digest, encode
from kurafolio.ingestion.contracts import IngestionError
from kurafolio.ingestion.discovery import admit_native, admit_parser2, verify_selected_profile
from kurafolio.domain.validation_v1 import decode_domain_v1
from kurafolio.source_builtin import registrations

ROOT = Path(__file__).resolve().parents[1]
ORACLE = json.loads((ROOT / 'tests/fixtures/ingestion/oracle.json').read_text())


def fixture(name):
    return deepcopy(ORACLE[name])


class IngestionDiscoveryTests(unittest.TestCase):
    def admit(self, *, data=None, raw=None, context=None, descriptor=None, profile=None):
        return admit_parser2(
            fixture('trade.csv').encode() if raw is None else raw,
            encode(fixture('parser2.json')) if data is None else encode(data),
            encode(fixture('child-context-parser2.json')) if context is None else context,
            fixture('descriptor-parser2.json') if descriptor is None else descriptor,
            fixture('wrapper-parser2.json') if profile is None else profile)

    def test_exact_minimal_projection_and_no_arbitrary_row_archive(self):
        result = self.admit()
        self.assertEqual(encode(fixture('minimal-parser2.json')), result)
        self.assertNotIn(b'FORBIDDEN_ROW_ARCHIVE_R4', result)
        self.assertNotIn(b'FORBIDDEN_RECORD_ARCHIVE_R4', result)
        self.assertNotIn(b'source_fields', result)

    def test_exact_original_decimal_tokens_and_unknown_fees(self):
        result = decode(self.admit())
        record = result['records'][0]
        self.assertEqual('0.01000000', record['legs'][1]['quantity'])
        self.assertEqual('70000.0000', record['lifecycle']['exchange_rate']['amount'])
        self.assertIsNone(record['fees'])

    def test_changed_capture_time_is_rejected_even_with_a_valid_payload(self):
        data = fixture('parser2.json')
        data['evidence']['context']['evidence_at'] = '2026-02-02T13:00:01+00:00'
        with self.assertRaises(IngestionError):
            self.admit(data=data)

    def test_context_canonical_bytes_are_not_silently_reencoded(self):
        context = json.dumps(fixture('child-context-parser2.json'), indent=2).encode()
        with self.assertRaises(IngestionError):
            self.admit(context=context)

    def test_raw_hash_and_profile_bindings_cannot_be_substituted(self):
        with self.assertRaises(IngestionError):
            self.admit(raw=b'changed raw input')
        for field in ('image_digest', 'installation_id', 'wrapper_profile_digest'):
            context = fixture('child-context-parser2.json')
            context[field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(IngestionError):
                self.admit(context=encode(context))

    def test_profile_digest_covers_entrypoint_and_identity_policy(self):
        for field, value in (('entry_point', 'unreviewed.module:run'), ('identity_policy', 'ambiguous')):
            profile = fixture('wrapper-parser2.json')
            profile[field] = value
            with self.subTest(field=field), self.assertRaises(IngestionError):
                self.admit(profile=profile)

    def test_unsupported_diagnostic_blocks_instead_of_disappearing(self):
        data = fixture('parser2.json')
        data['evidence']['diagnostics'] = [{'code': 'unreviewed_warning',
            'severity': 'warning', 'parameters': []}]
        with self.assertRaises(IngestionError) as caught:
            self.admit(data=data)
        self.assertEqual('import_evidence_unsupported', caught.exception.code)

    def test_no_financial_authority_in_an_unrecognized_adapter(self):
        data = fixture('parser2.json')
        data['adapter']['adapter_version'] = '2.0.0'
        with self.assertRaises(IngestionError):
            self.admit(data=data)

    def builtin(self, provider):
        descriptors = builtin_descriptors(package_distribution='kurafolio',
            package_version='0.1.0', artifact_sha256='1' * 64,
            execution_image_digest='2' * 64, entry_point_target='kurafolio.source_builtin:registrations')
        desc = next(d for d in descriptors if d.provider_id == provider)
        adapter = next(r.adapter for r in registrations() if r.adapter.info.provider_id == provider)
        selected = adapter.info.export_versions[0]
        frozen_context = parser.ParseContext(datetime.fromisoformat('2026-02-02T13:00:00+00:00'),
            '70000000-0000-4000-8000-000000000001',
            account_alias='demo-exchange' if provider == 'bullbitcoin' else None,
            format_selection=selected)
        profile = {'version': 1, 'installation_id': installation_id(desc),
            'image_digest': desc.execution_image_digest, 'wrapper_sha256': '3' * 64,
            'distribution': 'kurafolio', 'entry_point': 'kurafolio.ingestion.runner_child:main',
            'projection': 'parser2-minimal-v1', 'format_versions': [selected],
            'identity_policy': 'provider_scoped_stable' if provider == 'bullbitcoin' else 'snapshot_semantic'}
        profile['profile_digest'] = digest(profile)
        context = {'version': 1, 'job_id': '90000000-0000-4000-8000-000000000001',
            'member_id': '20000000-0000-4000-8000-000000000001', 'fence': '1',
            'installation_id': installation_id(desc), 'image_digest': desc.execution_image_digest,
            'wrapper_profile_digest': profile['profile_digest'], 'format_version': selected,
            'payload_kind': 'parser_v2', 'parser_context': primitive(frozen_context)}
        filename = 'bull-orders.csv' if provider == 'bullbitcoin' else 'wealthsimple-holdings.csv'
        raw = (ROOT / 'examples/data' / filename).read_bytes()
        batch = adapter.normalize(raw, export_version=selected, context=frozen_context)
        payload = parser.canonical_json(batch).encode()
        return decode(admit_parser2(raw, payload, encode(context), primitive(desc), profile))

    def test_public_wealthsimple_example_matches_independent_literal_counts(self):
        result = self.builtin('wealthsimple')
        expected = fixture('builtin-inputs.json')['wealthsimple_expected']
        self.assertEqual(expected['accounts'], len(result['accounts']))
        self.assertEqual(expected['positions'], len(result['records']))
        self.assertEqual(expected['membership'], result['membership']['status'])
        values = {'CAD': Decimal(0), 'USD': Decimal(0)}
        for row in result['records']:
            values[row['market_value']['currency']] += Decimal(row['market_value']['amount'])
        self.assertEqual(Decimal(expected['cad_native_positions_sum']), values['CAD'])
        self.assertEqual(Decimal(expected['usd_native_positions_sum']), values['USD'])
        self.assertEqual(expected['as_of'], result['snapshots'][0]['as_of']['token'])
        self.assertEqual([{'name': 'legacy_semantic_hash',
                           'value': result['snapshots'][0]['revision']}],
                         result['provenance']['semantic_digests'])
        self.assertFalse(any(x['source_field'] == 'legacy_semantic_hash'
                             for x in result['provenance']['field_mappings']))

    def test_public_bull_example_has_no_fabricated_contribution_or_wallet_balance(self):
        result = self.builtin('bullbitcoin')
        expected = fixture('builtin-inputs.json')['bull_expected']
        self.assertEqual(expected['accounts'], len(result['accounts']))
        buys = [r for r in result['records'] if r['kind'] == 'BUY']
        self.assertEqual(expected['completed_buys'], len(buys))
        totals = {'BTC': Decimal(0), 'LBTC': Decimal(0)}
        for row in buys:
            for leg in row['legs']:
                if leg['role'] == 'ACQUISITION':
                    symbol = result['assets'][int(leg['asset_local_id'])]['symbol']
                    totals[symbol] += Decimal(leg['quantity'])
        self.assertEqual(Decimal(expected['btc']), totals['BTC'])
        self.assertEqual(Decimal(expected['lbtc']), totals['LBTC'])
        self.assertEqual(Decimal(expected['purchase_cost_cad']),
                         sum(Decimal(r['acquisition_cost_cad']['amount']) for r in buys))
        funding = [r for r in result['records'] if r['kind'] == 'FUNDING']
        self.assertEqual(Decimal(expected['funding_cad']),
                         sum(Decimal(r['cash_flow']['cash_amount']['amount']) for r in funding))
        self.assertTrue(all(r['cash_flow']['boundary'] == expected['contribution_boundary'] for r in funding))
        self.assertTrue(all(r['legs'] == [] for r in funding))
        self.assertEqual([], result['snapshots'])


class NativeDiscoveryTests(unittest.TestCase):
    def admit(self, *, data=None, context=None, profile=None, raw=None,
              descriptor='descriptor-native.json'):
        return admit_native(fixture('trade.csv').encode() if raw is None else raw,
            encode(fixture('native-discovery.json') if data is None else data),
            encode(fixture('child-context-native.json') if context is None else context),
            fixture(descriptor), fixture('wrapper-native.json') if profile is None else profile)

    def test_exact_native_activity_projection_and_no_ephemeral_authority(self):
        result = self.admit()
        self.assertEqual(encode(fixture('minimal-native.json')), result)
        self.assertNotIn(b'10000000-0000-4000-8000-000000000040', result)
        self.assertIsNone(decode(result)['membership'])
        self.assertIsNone(decode(result)['provenance']['parser_api'])

    def test_exact_metadata_and_mapping_only_vectors_keep_all_issuers(self):
        for raw, discovery, context, expected in (
            ('metadata-native.csv', 'metadata-native-discovery.json',
             'child-context-native.json', 'metadata-native-minimal.json'),
            ('branch-mapping_only_existing_issuer.csv',
             'branch-mapping_only_existing_issuer-discovery.json',
             'branch-mapping_only_existing_issuer-context.json',
             'branch-mapping_only_existing_issuer-minimal.json')):
            with self.subTest(vector=expected):
                result = self.admit(data=fixture(discovery), context=fixture(context),
                                    raw=fixture(raw).encode())
                self.assertEqual(encode(fixture(expected)), result)
                if expected == 'metadata-native-minimal.json':
                    self.assertEqual(2, len(decode(result)['issuers']))
                    self.assertEqual(2, len(decode(result)['assets'][1]['identifiers']))

    def test_exact_complete_partial_and_empty_snapshot_vectors(self):
        for family in ('t1', 't2-complete', 't2-empty-complete', 't2-partial', 't2-empty-partial'):
            with self.subTest(family=family):
                context = fixture('snapshot-historical-t1-context.json' if family == 't1'
                                  else 'snapshot-seed-t2-context.json')
                result = self.admit(data=fixture('snapshot-' + family + '-discovery.json'),
                    context=context, profile=fixture('wrapper-snapshot.json'),
                    descriptor='descriptor-snapshot.json', raw=fixture('snapshot-' + family + '.csv').encode())
                self.assertEqual(encode(fixture('snapshot-' + family + '-minimal.json')), result)

    def test_frozen_valid_unknown_dates_and_legacy_archive_time_are_preserved(self):
        for tag in ('date_only', 'legacy_datetime'):
            data = fixture('snapshot-t1-discovery.json')
            domain = data['domain']
            domain['provenance']['canonical_sha256'] = '9' * 64

            def at(collection, ordinal, field):
                if tag == 'date_only':
                    return {'tag': tag, 'token': '2026-01-01', 'zone': None}
                return {'tag': tag, 'token': '2026-01-01T12:00:00+00:00',
                    'precision': 'legacy_unspecified', 'archive': {'canonical_sha256': '9' * 64,
                        'collection': collection, 'ordinal': ordinal, 'field': field}}

            domain['coverage'][0]['time'] = {'tag': 'point', 'at': at('coverage', 0, 'start')}
            domain['snapshots'][0]['as_of'] = at('snapshots', 0, 'as_of')
            for i, item in enumerate(domain['snapshots'][0]['items']):
                item['as_of'] = at('records', i, 'as_of')
            # This prerequisite distinguishes compatibility from accepting a
            # malformed frozen input merely because the new schema permits it.
            decode_domain_v1(encode(domain))
            result = decode(self.admit(data=data, context=fixture('snapshot-historical-t1-context.json'),
                raw=fixture('snapshot-t1.csv').encode(), descriptor='descriptor-snapshot.json',
                profile=fixture('wrapper-snapshot.json')))
            actual = result['snapshots'][0]['as_of']
            if tag == 'date_only':
                self.assertEqual(domain['snapshots'][0]['as_of'], actual)
            else:
                self.assertEqual({'tag': 'legacy_unspecified', 'token': '2026-01-01T12:00:00+00:00',
                    'zone': None, 'legacy': at('snapshots', 0, 'as_of')['archive']}, actual)
                self.assertEqual('records', result['records'][0]['as_of']['legacy']['collection'])
                self.assertEqual('coverage', result['coverage'][0]['time']['at']['legacy']['collection'])
                start, end = at('coverage', 0, 'start'), at('coverage', 0, 'end')
                start['token'], end['token'] = '2026-01-01T11:00:00+00:00', '2026-01-01T13:00:00+00:00'
                domain['coverage'][0]['time'] = {'tag': 'interval', 'start': start, 'end': end,
                    'start_inclusive': True, 'end_inclusive': True}
                decode_domain_v1(encode(domain))
                interval = decode(self.admit(data=data,
                    context=fixture('snapshot-historical-t1-context.json'),
                    raw=fixture('snapshot-t1.csv').encode(), descriptor='descriptor-snapshot.json',
                    profile=fixture('wrapper-snapshot.json')))['coverage'][0]['time']
                self.assertEqual('legacy_unspecified', interval['start']['tag'])
                self.assertEqual(start['token'], interval['start']['token'])
                self.assertEqual(end['archive'], interval['end']['legacy'])

    def test_native_profile_uses_each_exact_allowed_token_without_inventing_prose(self):
        for token in ('provider_scoped_stable', 'snapshot_semantic', 'ambiguous'):
            profile, context = fixture('wrapper-native.json'), fixture('child-context-native.json')
            profile['identity_policy'] = token
            profile['profile_digest'] = digest({k: v for k, v in profile.items() if k != 'profile_digest'})
            context['wrapper_profile_digest'] = profile['profile_digest']
            with self.subTest(token=token):
                result = decode(self.admit(profile=profile, context=context))
                self.assertEqual(token, result['provenance']['id_policy'])
                self.assertIsNone(result['provenance']['parser_api'])
        # These are isolated trusted-profile rule inputs, not positive READY cases.

    def test_retained_policy_cannot_be_forged_by_rehashing_after_raw_deletion(self):
        vectors = fixture('native-policy-cases.json')['native_minimals']
        for row in vectors:
            value = fixture(row['file'].removeprefix('fixtures/'))
            profile = fixture('wrapper-snapshot.json' if row['after'] == 'snapshot_semantic'
                              else 'wrapper-native.json')
            self.assertEqual(value, verify_selected_profile(value, profile))
            for token in ('provider_scoped_stable', 'snapshot_semantic', 'ambiguous',
                          'Explicit synthetic stable order ID', 'unknown'):
                if token == row['after']:
                    continue
                altered = deepcopy(value)
                altered['provenance']['id_policy'] = token
                # A valid new stage digest proves bytes, not selected-profile origin.
                self.assertEqual(64, len(digest(altered)))
                with self.subTest(vector=row['file'], token=token), self.assertRaises(IngestionError) as caught:
                    verify_selected_profile(decode(encode(altered)), profile)
                self.assertEqual('import_invalid', caught.exception.code)

    def test_native_discriminator_cannot_bypass_profile_policy_check(self):
        value = fixture('minimal-native.json')
        value['provenance']['parser_api'] = 2
        value['provenance']['id_policy'] = 'forged source prose'
        with self.assertRaises(IngestionError):
            verify_selected_profile(value, fixture('wrapper-native.json'))

    def test_parser2_policy_prose_is_preserved_and_not_treated_as_profile_authority(self):
        value = fixture('minimal-parser2.json')
        self.assertEqual(value, verify_selected_profile(value, fixture('wrapper-parser2.json')))
        self.assertEqual('Explicit synthetic stable order ID', value['provenance']['id_policy'])

    def test_context_raw_profile_and_namespace_guards(self):
        for field in ('image_digest', 'installation_id', 'wrapper_profile_digest'):
            context = fixture('child-context-native.json')
            context[field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(IngestionError):
                self.admit(context=context)
        for field in ('tenant_id', 'portfolio_id', 'connection_id'):
            context = fixture('child-context-native.json')
            context['namespace'][field] = '60000000-0000-4000-8000-000000000001'
            with self.subTest(namespace=field), self.assertRaises(IngestionError):
                self.admit(context=context)
        for field, value in (('identity_policy', 'unknown'), ('identity_policy', 'ambiguous'),
                             ('profile_digest', '0' * 64)):
            profile = fixture('wrapper-native.json')
            profile[field] = value
            with self.subTest(profile=field), self.assertRaises(IngestionError):
                self.admit(profile=profile)
        with self.assertRaises(IngestionError):
            self.admit(raw=b'changed source')

    def test_closed_native_inputs_and_source_capture_time(self):
        for place in ('root', 'provenance'):
            data = fixture('native-discovery.json')
            target = data if place == 'root' else data['domain']['provenance']
            target['id_policy'] = 'provider_scoped_stable'
            with self.subTest(place=place), self.assertRaises(IngestionError):
                self.admit(data=data)
        data = fixture('native-discovery.json')
        data['domain']['provenance']['evidence_at']['token'] = '2026-02-02T13:00:01+00:00'
        with self.assertRaises(IngestionError):
            self.admit(data=data)

    def test_missing_duplicate_conflicting_and_unbound_lifecycle_sidecars(self):
        for name in ('metadata-sidecar-missing-negative.json',
                     'metadata-sidecar-duplicate-negative.json',
                     'metadata-sidecar-conflicting-negative.json'):
            with self.subTest(vector=name), self.assertRaises(IngestionError):
                self.admit(data=fixture(name), raw=fixture('metadata-native.csv').encode())
        data = fixture('native-discovery.json')
        data['lifecycle_by_activity'][0]['activity_ordinal'] = 1
        with self.assertRaises(IngestionError):
            self.admit(data=data)


if __name__ == '__main__':
    unittest.main()
