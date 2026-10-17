"""Offline previews preserve live bytes and use the actual financial rules."""
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import csv
import hashlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest

from wealth_ledger.core import import_holdings, inspect_holdings, initialize
from wealth_ledger.crypto import import_bull_orders
from wealth_ledger.crypto_opening import import_opening
from wealth_ledger.preflight import preview_update, render_preview
from wealth_ledger.wallet import add_balance, add_event
from test_core import FX, write_holdings, synthetic_rows
from test_crypto import FIELDS, ASSUMPTIONS, order
from test_combined import quote

PROJECT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-10-12T12:30:45-04:00')
T1 = '2026-10-10T17:00:00-04:00'


def files(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode & 0o777)
            for path in root.rglob('*') if path.is_file()} | {str(path.relative_to(root)) + '/': ('directory', path.stat().st_mode & 0o777) for path in root.rglob('*') if path.is_dir()}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='preflight-test-')
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        (self.project / 'config').mkdir(parents=True)
        (self.project / 'config/bull-opening.json').write_text(json.dumps(ASSUMPTIONS), encoding="utf-8")
        self.ws = write_holdings(self.root / 'holdings.csv')
        self.orders = [order('fund', amount='100'), order('buy', 'Buy Bitcoin', '100', 'BTC', '.08', completed='2026-01-01T02:00:00Z')]
        self.bull = self.write_orders(self.orders)
        self.network = [patch('wealth_ledger.fx._download', side_effect=AssertionError('Network forbidden')),
                        patch('wealth_ledger.prices.urlopen', side_effect=AssertionError('Network forbidden'))]
        self.mocks = [p.start() for p in self.network]

    def tearDown(self):
        for mock in self.mocks:
            mock.assert_not_called()
        for p in self.network:
            p.stop()
        self.temp.cleanup()

    def write_orders(self, rows, name='orders.csv'):
        path = self.root / name
        with path.open('w', newline='', encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def seed(self, *, ws=True, bull=True):
        initialize(self.project)
        if ws:
            import_holdings(self.project, self.ws, 'baseline', FX)
            self.cache_fx('2026-10-09')
        if bull:
            import_bull_orders(self.project, self.bull, opening_assumption=ASSUMPTIONS)

    def cache_fx(self, day):
        path = self.project / 'data/fx' / (day + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**FX, 'usd_cad_date': day, 'usd_twd_date': day}), encoding="utf-8")
        return path

    def preview(self, paths=(), **kwargs):
        before = files(self.project)
        result = preview_update(self.project, {'paths': list(paths), **kwargs}, now=NOW)
        self.assertEqual(before, files(self.project))
        encoded = json.dumps(result, ensure_ascii=False)
        for private in ('private-source-address', 'private-source-message', 'private-source-transaction', 'private-order-number'):
            self.assertNotIn(private, encoded)
        return result

    def test_new_holdings_without_fx_still_checks_structure_and_cutoff(self):
        result = self.preview([self.ws])
        self.assertEqual(result['status'], 'pending_reference')
        self.assertEqual(result['sources']['wealthsimple']['status'], 'imported')
        self.assertFalse(result['simulation_complete'])
        self.assertEqual(result['valuation_as_of'], '2026-10-09T22:28:00-04:00')
        self.assertFalse((self.project / 'data/db/portfolio.sqlite3').exists())
        self.assertIn('holdings_fx', result['pending_checks'])

    def test_missing_fx_does_not_hide_backfill_or_account_conflicts(self):
        self.seed(bull=False)
        old = write_holdings(self.root / 'old.csv', when='2026-09-09 22:28 GMT-04:00')
        result = self.preview([old])
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('Backfill', result['blockers'][0]['detail'])
        changed = synthetic_rows()
        changed[0][1] = 'RRSP'
        bad = write_holdings(self.root / 'account-conflict.csv', changed, when='2026-11-09 22:28 GMT-05:00')
        self.assertEqual(self.preview([bad])['status'], 'blocked')

    def test_saved_fx_and_duplicate_semantics_match_importer(self):
        self.seed(bull=False)
        source = self.preview([self.ws])['sources']['wealthsimple']
        self.assertEqual(source['status'], 'duplicate')
        self.assertNotIn('snapshot_id', source)
        changed = synthetic_rows()
        changed[0][17] = '101'
        revised = write_holdings(self.root / 'revision.csv', changed)
        self.assertEqual(self.preview([revised])['sources']['wealthsimple']['status'], 'revision')

    def test_missing_account_warning_does_not_become_a_zero_balance(self):
        self.seed(bull=False)
        partial = write_holdings(self.root / 'partial.csv', synthetic_rows()[:1])
        result = self.preview([partial])
        source = result['sources']['wealthsimple']
        self.assertFalse(source['is_complete'])
        self.assertGreater(source['missing_account_count'], 0)
        self.assertIn('missing_accounts', [i['code'] for i in source['issues']])

    def test_both_sources_and_missing_fx_keep_btc_without_fake_valuation(self):
        result = self.preview([self.bull, self.ws])
        self.assertEqual(result['btc']['quantity_btc'], '0.08')
        self.assertEqual(result['valuation_as_of'], '2026-10-09T22:28:00-04:00')
        self.assertEqual(result['sources']['bullbitcoin']['new_orders'], 2)
        self.assertNotIn('market_cad', result['btc'])
        self.assertIn('btc_price', result['pending_checks'])

    def test_bull_first_uses_execution_minute_and_not_order_time(self):
        result = self.preview([self.bull])
        self.assertEqual(result['valuation_as_of'], '2026-10-12T12:30:00-04:00')
        self.assertIsNone(result['holdings_as_of'])
        self.assertEqual(result['source_usage']['wealthsimple'], 'not_available')

    def test_bull_duplicate_and_completed_conflict(self):
        self.seed()
        result = self.preview([self.bull])
        self.assertEqual(result['sources']['bullbitcoin']['new_orders'], 0)
        bad_rows = [dict(row) for row in self.orders]
        bad_rows[1]['PAYOUT_AMOUNT'] = '.09'
        bad = self.write_orders(bad_rows, 'conflict.csv')
        result = self.preview([bad])
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('Completed order', result['blockers'][0]['detail'])

    def test_pending_order_revision_count_uses_actual_importer(self):
        pending = self.write_orders([order('pending', status='Pending', completed='')], 'pending.csv')
        import_bull_orders(self.project, pending, opening_assumption=ASSUMPTIONS)
        completed = self.write_orders([order('pending')], 'completed.csv')
        result = self.preview([completed])
        self.assertEqual(result['sources']['bullbitcoin']['revised_orders'], 1)

    def test_balance_only_difference_no_formal_id_or_fake_contribution(self):
        self.seed()
        result = self.preview(btc_balance='.0799', btc_balance_as_of=T1)
        balance = result['sources']['wallet']
        self.assertEqual(balance['recorded_expected_btc'], '0.08')
        self.assertEqual(balance['recorded_residual_btc'], '-0.00010000')
        self.assertEqual(result['btc']['quantity_btc'], '0.07990000')
        self.assertEqual(result['btc']['unresolved_count'], 1)
        self.assertNotIn('record_id', balance)
        self.assertNotIn('B000001', json.dumps(result))
        self.assertNotIn('contribution_cad', result['btc'])

    def test_fresh_balance_only_unknown_history_and_bull_usage(self):
        result = self.preview(btc_balance='0')
        self.assertEqual(result['btc']['quantity_btc'], '0.00000000')
        self.assertIsNone(result['sources']['wallet']['recorded_expected_btc'])
        self.assertEqual(result['source_usage']['bullbitcoin'], 'not_available')

    def test_same_time_balance_conflict_and_duplicate(self):
        self.seed()
        add_balance(self.project, '.08', T1, now=NOW.isoformat())
        same = self.preview(btc_balance='.08', btc_balance_as_of=T1)
        self.assertEqual(same['sources']['wallet']['status'], 'duplicate')
        conflict = self.preview(btc_balance='.079', btc_balance_as_of=T1)
        self.assertEqual(conflict['status'], 'blocked')
        self.assertIn('Same-time', conflict['blockers'][0]['detail'])

    def test_invalid_balance_precision_future_and_negative(self):
        for options in ({'btc_balance': '-1'}, {'btc_balance': '.000000001'},
                        {'btc_balance': 'NaN'}, {'btc_balance': '.01', 'btc_balance_as_of': '2027-01-01T00:00:00Z'}):
            with self.subTest(options=options):
                self.assertEqual(self.preview(**options)['status'], 'blocked')

    def test_known_fee_before_observation_not_deducted_twice(self):
        self.seed()
        add_event(self.project, type='fee', quantity_btc='.001', occurred_at='2026-10-10T16:00:00-04:00', source='manual', reference='fee-1', now=NOW.isoformat())
        result = self.preview(btc_balance='.079', btc_balance_as_of=T1)
        self.assertEqual(result['sources']['wallet']['recorded_residual_btc'], '0.00000000')
        self.assertEqual(result['btc']['quantity_btc'], '0.07900000')

    def test_pre_bull_opening_remains_fixed(self):
        self.seed()
        path = self.root / 'opening.json'
        path.write_text(json.dumps({'reported_total_btc_equivalent': '.09', 'reference_as_of': T1,
                                   'declared_on': '2026-10-10', 'balance_scope': 'all_wallets_btc_plus_lbtc',
                                   'basis': 'Pre-Bull holding', 'confirmed_by': 'synthetic-user'}), encoding="utf-8")
        import_opening(self.project, path)
        result = self.preview(btc_balance='.095', btc_balance_as_of=NOW.isoformat())
        self.assertEqual(result['sources']['wallet']['recorded_expected_btc'], '0.09')
        self.assertEqual(result['sources']['wallet']['recorded_residual_btc'], '0.00500000')

    def test_late_purchase_uses_execution_time_with_pending_new_fx(self):
        self.seed()
        rows = [order('late-fund', created='2026-10-11T00:00:00Z', completed='2026-10-11T01:00:00Z'),
                order('late-buy', 'Buy Bitcoin', '100', 'BTC', '.01', created='2026-10-11T01:00:00Z', completed='2026-10-11T02:00:00Z')]
        result = self.preview([self.ws, self.write_orders(rows, 'new.csv')])
        self.assertEqual(result['valuation_as_of'], '2026-10-12T12:30:00-04:00')
        self.assertIn('valuation_fx', result['pending_checks'])
        self.assertEqual(result['btc']['quantity_btc'], '0.09')

    def test_no_input_reuses_published_cutoff_not_today(self):
        self.seed()
        with sqlite3.connect(self.project / 'data/db/portfolio.sqlite3') as conn:
            conn.execute('CREATE TABLE combined_observations(as_of_utc TEXT,revision INTEGER,payload_json TEXT)')
            conn.execute('INSERT INTO combined_observations VALUES(?,?,?)', ('2026-10-10T21:00:00+00:00', 1, json.dumps({'as_of': T1})))
        directory = self.project / 'reports/saved'
        directory.mkdir(parents=True)
        (directory / 'data.json').write_text(json.dumps({'meta': {'as_of': T1}}), encoding="utf-8")
        (self.project / 'reports/latest.json').write_text(json.dumps({'path': 'reports/saved'}), encoding="utf-8")
        self.assertEqual(self.preview()['valuation_as_of'], T1)

    def test_corrupt_cache_and_mismatched_overrides_block(self):
        self.seed()
        cache = self.cache_fx('2026-10-09')
        cache.write_text('invalid-json', encoding="utf-8")
        self.assertEqual(self.preview([self.ws])['status'], 'blocked')
        fx_file = self.root / 'bad-fx.json'
        fx_file.write_text(json.dumps({**FX, 'usd_cad_date': '2027-01-01'}), encoding="utf-8")
        self.assertEqual(self.preview([self.ws], fx_file=str(fx_file))['status'], 'blocked')
        price = self.root / 'wrong-time.json'
        price.write_text(json.dumps(quote('2026-10-11T00:00:00Z')), encoding="utf-8")
        self.assertEqual(self.preview(btc_balance='.08', btc_balance_as_of=T1, price_file=str(price))['status'], 'blocked')

    def test_cached_quote_verifies_evidence_and_returns_checked(self):
        self.seed()
        self.cache_fx('2026-10-10')
        from wealth_ledger.prices import parse_time
        key = parse_time(T1).strftime('%Y-%m-%dT%H%M%S%z')
        evidence = self.project / 'data/prices/evidence/quote.json'
        evidence.parent.mkdir(parents=True)
        evidence.write_text('public synthetic evidence', encoding="utf-8")
        value = {**quote(T1), 'evidence_path': str(evidence.relative_to(self.project)), 'evidence_sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}
        path = self.project / 'data/prices' / f'btc-usd-{key}.json'
        path.write_text(json.dumps(value), encoding="utf-8")
        result = self.preview(btc_balance='.08', btc_balance_as_of=T1)
        self.assertEqual(result['status'], 'checked')
        evidence.write_text('corrupt', encoding="utf-8")
        self.assertEqual(self.preview(btc_balance='.08', btc_balance_as_of=T1)['status'], 'blocked')

    def test_lock_duplicate_provider_and_unsupported_file(self):
        self.seed()
        (self.project / 'work/update.lock').write_text('owner', encoding="utf-8")
        self.assertEqual(self.preview([self.ws])['status'], 'blocked')
        (self.project / 'work/update.lock').unlink()
        other = write_holdings(self.root / 'other.csv')
        self.assertEqual(self.preview([self.ws, other])['status'], 'blocked')
        bad = self.root / 'unknown.csv'
        bad.write_text('a,b\n1,2\n', encoding="utf-8")
        self.assertEqual(self.preview([bad])['status'], 'blocked')

    def test_corrupt_second_input_never_imports_first(self):
        bad = self.write_orders([{**self.orders[0], 'PAYIN_CURRENCY': 'USD'}], 'bad.csv')
        result = self.preview([self.ws, bad])
        self.assertEqual(result['status'], 'blocked')
        self.assertIsNone(result['valuation_as_of'])

    def test_read_only_holdings_inspector_alone(self):
        before = files(self.project)
        result = inspect_holdings(self.project, self.ws)
        self.assertEqual(result['status'], 'imported')
        self.assertEqual(before, files(self.project))

    def test_normal_import_matches_pending_fx_structural_plan(self):
        plan = self.preview([self.ws])['sources']['wealthsimple']
        actual = import_holdings(self.project, self.ws, 'monthly', FX)
        self.assertEqual(plan['status'], actual['status'])
        self.assertEqual(plan['is_complete'], actual['is_complete'])

    def test_rendered_summary_and_cli_json_block_exit(self):
        result = self.preview([self.ws])
        text = render_preview(result)
        self.assertIn('待行情確認', text)
        self.assertIn('預計估值截止', text)
        spec = importlib.util.spec_from_file_location('preflight_update_cli', PROJECT / 'scripts/update.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        unknown = self.root / 'bad.csv'
        unknown.write_text('a,b\n1,2\n', encoding="utf-8")
        output = io.StringIO()
        with patch.object(cli, 'PROJECT', self.project), patch('sys.argv', ['update.py', '--dry-run', '--json', str(unknown)]), redirect_stdout(output):
            self.assertEqual(cli.main(), 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'blocked')
        with patch.object(cli, 'PROJECT', self.project), patch('sys.argv', ['update.py', '--dry-run', '--json', str(self.ws)]), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)

    def test_cli_default_still_uses_normal_commit_and_publisher(self):
        spec = importlib.util.spec_from_file_location('default_update_cli', PROJECT / 'scripts/update.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with patch.object(cli, 'PROJECT', self.project), patch('sys.argv', ['update.py', str(self.ws)]), patch.object(cli.ApplicationService, 'update', return_value={'status': 'published'}) as execute, redirect_stdout(io.StringIO()):
            cli.main()
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0]['paths'], [str(self.ws.resolve())])
        self.assertIsNone(execute.call_args.kwargs['resume'])

    def test_preview_rejects_concurrent_live_input_change(self):
        self.seed(bull=False)
        from wealth_ledger import preflight
        original = preflight.inspect_holdings
        def changed(*args, **kwargs):
            value = original(*args, **kwargs)
            with sqlite3.connect(self.project / 'data/db/portfolio.sqlite3') as conn:
                conn.execute("UPDATE accounts SET label='Concurrent change'")
            return value
        with patch('wealth_ledger.preflight.inspect_holdings', side_effect=changed):
            result = preview_update(self.project, {'paths': [self.ws]}, now=NOW)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('concurrent_change', [b['component'] for b in result['blockers']])

    def test_new_source_without_opening_is_blocked(self):
        (self.project / 'config/bull-opening.json').unlink()
        self.assertEqual(self.preview([self.bull])['status'], 'blocked')

    def test_negative_bull_cash_is_detected_before_formal_update(self):
        bad = self.write_orders([self.orders[1]], 'missing-funding.csv')
        result = self.preview([bad])
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('cash ledger is negative', result['blockers'][0]['detail'])

    def test_quote_override_without_evidence_hash_is_blocked(self):
        self.seed()
        price = self.root / 'price.json'
        value = quote(T1)
        value.pop('evidence_sha256', None)
        price.write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual(self.preview(btc_balance='.08', btc_balance_as_of=T1, price_file=str(price))['status'], 'blocked')

    def test_saved_fx_file_allows_first_full_simulation(self):
        fx = self.root / 'fx.json'
        fx.write_text(json.dumps(FX), encoding="utf-8")
        result = self.preview([self.ws], fx_file=str(fx))
        self.assertEqual(result['status'], 'checked')
        self.assertTrue(result['simulation_complete'])
        self.assertEqual(result['sources']['wealthsimple']['kind'], 'baseline')

    def test_source_integrity_warning_is_visible_without_source_ids(self):
        self.seed()
        with sqlite3.connect(self.project / 'data/db/portfolio.sqlite3') as conn:
            archived = conn.execute('SELECT path FROM crypto_sources LIMIT 1').fetchone()[0]
        (self.project / archived).chmod(0o600)
        (self.project / archived).write_text('tampered', encoding="utf-8")
        result = self.preview(btc_balance='.08', btc_balance_as_of=T1)
        self.assertIn('crypto_source_integrity', [item['code'] for item in result['btc']['issues']])
        self.assertNotIn('source_id', json.dumps(result))
        self.assertIn('雜湊不符', render_preview(result))

    def test_new_balance_after_explicit_cutoff_is_not_used_to_value_past(self):
        self.seed()
        result = self.preview(btc_balance='.09', btc_balance_as_of=T1, as_of='2026-10-09T22:28:00-04:00')
        self.assertFalse(result['sources']['wallet']['included_at_cutoff'])
        self.assertEqual(result['btc']['quantity_btc'], '0.08000000')
        self.assertIn('不納入本期數量', render_preview(result))

    def test_cli_exclusive_modes_reject_before_mutation(self):
        spec = importlib.util.spec_from_file_location('exclusive_update_cli', PROJECT / 'scripts/update.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        before = files(self.project)
        for flags in (['--json'], ['--dry-run', '--list-operations'], ['--dry-run', '--resume-operation', 'id'], ['--dry-run', '--lookthrough-run-id', '6']):
            with self.subTest(flags=flags), patch.object(cli, 'PROJECT', self.project), patch('sys.argv', ['update.py', *flags]), redirect_stdout(io.StringIO()), patch('sys.stderr', io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cli.main()
                self.assertEqual(caught.exception.code, 2)
        self.assertEqual(before, files(self.project))

    def test_malformed_options_are_blocked_without_creating_a_project(self):
        for request in ({'btc_balance_source': 'wallet'}, {'snapshot_id': 1, 'paths': [self.ws]},
                        {'lookthrough_run_id': 6}, {'resume_operation': 'id'},
                        {'wealthsimple_only': True, 'btc_balance': '0'}, {}):
            with self.subTest(request=request):
                self.assertEqual(preview_update(self.project, request, now=NOW)['status'], 'blocked')
        self.assertFalse((self.project / 'data/db/portfolio.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
