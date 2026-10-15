"""Meaningful locale regressions use only temporary synthetic portfolios."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

from wealth_ledger.i18n import (PresentationContext, LocalizationError, SourceText,
    catalog, current_context, display_payload, legacy_text, normalize_locale,
    placeholders, presentation_context, registry, sheet_title, tr, validate_catalogs)
from wealth_ledger.settings import report_locale, ensure_report_locale_setting
from wealth_ledger.formatting import money, quantity, percent

ROOT = Path(__file__).resolve().parents[1]
OVERVIEW = 'message.' + hashlib.sha256('資產總覽'.encode()).hexdigest()[:12]
LOCALES = ('zh-TW', 'en-CA', 'zh-CN')


class CatalogTests(unittest.TestCase):
    def test_catalogs_are_complete_with_identical_parameter_contracts(self):
        checked = validate_catalogs()
        self.assertEqual(set(checked['locales']), set(LOCALES))
        self.assertGreater(checked['messages'], 1000)
        self.assertFalse(any(re.search('[\u3400-\u9fff]', value) for value in catalog('en-CA').values()))

    def test_missing_key_and_wrong_parameters_fail_explicitly(self):
        with presentation_context('en-CA'):
            with self.assertRaises(LocalizationError): tr('missing.key')
            with self.assertRaises(LocalizationError): tr(OVERVIEW, unwanted='value')
        with self.assertRaises(LocalizationError): placeholders('{value.__class__}')

    def test_incomplete_or_mismatched_catalog_is_rejected(self):
        original = catalog
        with patch('wealth_ledger.i18n.catalog', side_effect=lambda locale: {} if locale == 'zh-CN' else original(locale)):
            with self.assertRaisesRegex(LocalizationError, 'Incomplete catalog'): validate_catalogs()
        with patch('wealth_ledger.i18n.catalog', side_effect=lambda locale: {'sample': '{other}' if locale == 'zh-CN' else '{value}'}):
            with self.assertRaisesRegex(LocalizationError, 'parameters differ'): validate_catalogs()

    def test_new_offline_errors_and_source_statuses_use_legacy_mapping(self):
        with presentation_context('zh-TW'):
            self.assertEqual(legacy_text('Saved report data hash mismatch'),'已保存報告的資料雜湊不符')
        with presentation_context('en-CA'):
            self.assertEqual(legacy_text('未介接'),'No adapter')
        resource=json.loads((ROOT/'src/wealth_ledger/locales/legacy.json').read_text())
        self.assertEqual(set(resource),{'schema_version','source_locale','messages'})
        for key in resource['messages'].values():self.assertIn(key,catalog('en-CA'))

    def test_invalid_locale_and_documented_aliases(self):
        for alias, expected in [('en', 'en-CA'), ('en_CA', 'en-CA'), ('EN-ca', 'en-CA'),
                                ('zh-Hant', 'zh-TW'), ('zh_Hans', 'zh-CN')]:
            self.assertEqual(normalize_locale(alias), expected)
        for value in ('zh', 'en-US', '../../private', None):
            with self.assertRaises(LocalizationError): normalize_locale(value)

    def test_nested_and_concurrent_contexts_do_not_change_each_other(self):
        original = current_context()
        with presentation_context('en-CA'):
            self.assertEqual(tr(OVERVIEW), 'Overview')
            with presentation_context('zh-CN'): self.assertEqual(tr(OVERVIEW), '资产总览')
            self.assertEqual(tr(OVERVIEW), 'Overview')
        self.assertEqual(current_context(), original)
        def render(locale):
            with presentation_context(locale): return tr(OVERVIEW)
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(list(pool.map(render, LOCALES)), ['資產總覽', 'Overview', '资产总览'])

    def test_quantity_zero_missing_precision_and_negative_pnl_are_distinct(self):
        for locale in LOCALES:
            with presentation_context(locale):
                self.assertEqual(money('1234567.895'), '1,234,567.90')
                self.assertEqual(money('-0.015'), '-0.02')
                self.assertEqual(money('0'), '0.00')
                self.assertNotEqual(money(None), '0.00')
                self.assertEqual(quantity('0.00000001'), '0.00000001')
                self.assertEqual(percent('0'), '0.00%')
                self.assertEqual(percent('0.0000000000001'), '<0.000001%')
                self.assertNotEqual(percent(None), '0.00%')

    def test_user_source_text_is_not_translated_as_program_vocabulary(self):
        with presentation_context('en-CA'):
            self.assertEqual(legacy_text('現金'), 'Cash')
            self.assertEqual(legacy_text(SourceText('現金')), '現金')
            original = {'positions': [{'security_type': 'EQUITY', 'name': '現金', 'account_label': '未知'}],
                        'securities': [], 'cash_flows': [{'note': '費用'}]}
            before = deepcopy(original); view = display_payload(original)
            self.assertEqual(legacy_text(view['positions'][0]['name']), '現金')
            self.assertEqual(legacy_text(view['cash_flows'][0]['note']), '費用')
            self.assertEqual(original, before)

    def test_bundled_fonts_cover_all_catalog_cjk_glyphs(self):
        from fontTools.ttLib import TTFont
        for locale in LOCALES:
            profile = registry()['locales'][locale]
            with TTFont(ROOT/'assets/fonts'/profile['font']) as font:
                cmap = font.getBestCmap()
                chars = {ord(c) for text in catalog(locale).values() for c in text if '\u3400' <= c <= '\u9fff'}
                self.assertFalse(chars-set(cmap), locale)
            metadata = PresentationContext(locale).metadata()
            self.assertEqual(metadata['font'], profile['font'])
            self.assertEqual(metadata['font_sha256'], hashlib.sha256((ROOT/'assets/fonts'/profile['font']).read_bytes()).hexdigest())


class LocaleSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_new_default_and_readonly_legacy_detection(self):
        self.assertEqual(report_locale(self.root), 'en-CA')
        self.assertEqual(list(self.root.iterdir()), [])
        db=self.root/'data/db/portfolio.sqlite3';db.parent.mkdir(parents=True);db.write_bytes(b'legacy marker')
        self.assertEqual(report_locale(self.root), 'zh-TW')
        self.assertFalse((self.root/'config').exists())

    def test_explicit_setting_and_override_preserve_cost_policy(self):
        p=self.root/'config/local.toml';p.parent.mkdir()
        p.write_text('[reporting]\n# preserved\nbtc_cost_policy="bull_average_proxy"\n',encoding='utf-8')
        self.assertEqual(ensure_report_locale_setting(self.root), 'en-CA')
        text=p.read_text(encoding='utf-8')
        self.assertIn('bull_average_proxy',text);self.assertIn('# preserved',text)
        self.assertEqual(report_locale(self.root,'zh-Hant'),'zh-TW')
        self.assertEqual(report_locale(self.root),'en-CA')
        ensure_report_locale_setting(self.root)
        self.assertEqual(p.read_text(encoding='utf-8'),text)

    def test_fresh_data_only_operation_preserves_new_ledger_english_default(self):
        from wealth_ledger import operations
        with operations.project_lock(self.root):
            operations.record_data_operation(self.root, {'kind':'synthetic'}, lambda stage:{'status':'checked'})
        self.assertTrue((self.root/'data/db/portfolio.sqlite3').is_file())
        self.assertEqual(report_locale(self.root),'en-CA')
        self.assertIn('locale = "en-CA"',(self.root/'config/local.toml').read_text())

    def test_invalid_locale_precedes_any_operation_or_ledger_write(self):
        from wealth_ledger.operations import execute_update
        with self.assertRaises(LocalizationError):
            execute_update(self.root, {'report_locale':'invalid'}, lambda *args: None)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_saved_locale_returns_error_without_traceback_or_writes(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from wealth_ledger.cli import run_main
        with tempfile.TemporaryDirectory() as temporary:
            project=Path(temporary);(project/'config').mkdir()
            config=project/'config/local.toml';config.write_text('[reporting]\nlocale="zh"\n')
            before=config.read_bytes();error=StringIO()
            with patch('sys.argv',['update.py']),redirect_stderr(error):
                result=run_main(lambda:report_locale(project),project)
            self.assertEqual(result,2)
            self.assertIn('Unsupported locale',error.getvalue())
            self.assertNotIn('Traceback',error.getvalue())
            self.assertEqual(config.read_bytes(),before)
            self.assertFalse((project/'data').exists())

    def test_help_and_errors_use_locale_before_or_after_subcommand(self):
        env = dict(__import__('os').environ, PYTHONDONTWRITEBYTECODE='1')
        for args, expected in [(['scripts/update.py','--locale','en-CA','--help'],'options:'),
                               (['scripts/update.py','--locale','zh-TW','--help'],'選項:'),
                               (['scripts/update.py','--locale','zh-CN','--help'],'选项:'),
                               (['scripts/btc_events.py','add','--locale','zh-CN','--help'],'选项:')]:
            r=subprocess.run([sys.executable,*args],cwd=ROOT,env=env,text=True,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr);self.assertIn(expected,r.stdout)
        r=subprocess.run([sys.executable,'scripts/btc_events.py','add','--locale','zh-CN'],cwd=ROOT,env=env,text=True,capture_output=True)
        self.assertEqual(r.returncode,2);self.assertIn('缺少必要参数',r.stderr)


class LocalizedReportTests(unittest.TestCase):
    def setUp(self):
        import test_combined
        self.fixture = test_combined.CombinedTests('test_combined_totals_include_quantity_and_remaining_cash_once')
        self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.project=self.fixture.root
        shutil.copyfile(ROOT/'config/company-aliases.json',self.project/'config/company-aliases.json')

    def payload(self):
        from wealth_ledger.lookthrough import attach_analysis
        import test_lookthrough
        from wealth_ledger.fund_sources import holding
        payload=self.fixture.payload()
        attach_analysis(self.project,payload,fetcher=lambda id,directory:test_lookthrough.fund(id,[holding('Synthetic Company',100,ticker='SYNTH',country='CA',gics_sector='Industrials')]))
        return payload

    def render(self,payload,locale,output):
        from wealth_ledger.reporting import generate_reports
        from wealth_ledger.workbook import build_workbook,verify_workbook
        from wealth_ledger.validation import validate_formula_caches
        from wealth_ledger.report_checks import validate_report_presentation
        artifacts=generate_reports(payload,output,locale=locale)
        build_workbook(payload,output/'portfolio.ods',chart_images=artifacts['charts'],locale=locale)
        self.assertEqual(validate_formula_caches(output/'portfolio.ods')['cache_mismatches'],0)
        verified=verify_workbook(output/'portfolio.ods',payload['totals']['total_cad'])
        self.assertEqual(validate_report_presentation(payload,output)['status'],'passed')
        self.assertEqual(Decimal(verified['total_cad']),Decimal(payload['totals']['total_cad']))
        return artifacts

    def test_same_payload_three_languages_preserves_financial_data_and_formulas(self):
        from wealth_ledger.lookthrough import portfolio_signature
        from pypdf import PdfReader
        payload=self.payload();before=json.dumps(payload,sort_keys=True);signature=portfolio_signature(payload)
        db=self.project/'data/db/portfolio.sqlite3';db_before=db.read_bytes()
        formula_counts=[]
        for locale in LOCALES:
            output=self.project/'rendered'/locale
            self.render(payload,locale,output)
            with zipfile.ZipFile(output/'portfolio.ods') as z:
                root=ET.fromstring(z.read('content.xml'))
                formula_counts.append(sum('urn:oasis:names:tc:opendocument:xmlns:table:1.0}formula' in ' '.join(n.attrib) for n in root.iter()))
            md=(output/'report.md').read_text(encoding='utf-8')
            if locale=='en-CA':self.assertFalse(re.search('[\u3400-\u9fff]',md),[l for l in md.splitlines() if re.search('[\u3400-\u9fff]',l)])
            self.assertEqual(PdfReader(output/'report.pdf').trailer['/Root']['/Lang'],locale)
            self.assertEqual(json.dumps(payload,sort_keys=True),before)
            self.assertEqual(portfolio_signature(payload),signature)
        self.assertEqual(len(set(formula_counts)),1)
        self.assertEqual(db.read_bytes(),db_before)

    def test_unknown_cost_and_unexplained_wallet_gap_remain_non_numeric_in_all_languages(self):
        from wealth_ledger.wallet import add_balance
        add_balance(self.project,'.0024','2026-10-09T22:28:00-04:00',source='synthetic wallet',now='2026-10-10T20:00:00Z')
        payload=self.payload()
        self.assertEqual(payload['crypto']['wallet']['unresolved_count'],1)
        payload['crypto']['cost_estimate_policy']='actual_only'
        self.assertIsNone(payload['crypto']['valuation']['unrealized_cad'])
        for locale in LOCALES:self.render(payload,locale,self.project/'unknown'/locale)

    def test_offline_editions_keep_source_bytes_and_do_not_touch_ledger_or_latest(self):
        from wealth_ledger.editions import render_language_edition
        payload=self.payload();source=self.project/'source-report';source.mkdir()
        raw=json.dumps(payload,ensure_ascii=False,indent=2).encode()
        (source/'data.json').write_bytes(raw)
        manifest={'snapshot_as_of':payload['meta']['as_of'],'lookthrough_run_id':payload['lookthrough']['run_id'],'data_sha256':hashlib.sha256(raw).hexdigest()}
        (source/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        original={str(p.relative_to(self.project)):p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')),patch('wealth_ledger.prices.urlopen',side_effect=AssertionError('network forbidden')),patch('wealth_ledger.fund_sources.Client.get',side_effect=AssertionError('network forbidden')):
            result=render_language_edition(source,self.project/'edition','en-CA')
        self.assertFalse(result['ledger_changed']);self.assertFalse(result['latest_changed'])
        self.assertEqual((self.project/'edition/data.json').read_bytes(),raw)
        self.assertIn('replays saved data offline',(self.project/'edition/report.md').read_text(encoding='utf-8'))
        for rel,data in original.items():self.assertEqual((self.project/rel).read_bytes(),data,rel)
        with self.assertRaises(ValueError):render_language_edition(source,self.project/'edition','en-CA')
        with self.assertRaises(ValueError):render_language_edition(source,source/'inside','en-CA')

    def test_offline_editions_reject_tampered_source_before_creating_output(self):
        from wealth_ledger.editions import render_language_edition
        source=self.project/'invalid-bundle';source.mkdir()
        (source/'data.json').write_text('{}',encoding='utf-8')
        (source/'manifest.json').write_text('{"data_sha256":"wrong"}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):render_language_edition(source,self.project/'out','zh-CN')
        self.assertFalse((self.project/'out').exists())
