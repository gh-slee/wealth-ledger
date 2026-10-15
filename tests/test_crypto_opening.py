"""Declared pre-Bull quantities must not fabricate costs, cash flows or returns."""
import csv
from decimal import Decimal
import json
import sqlite3
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import test_combined as combined_fixture
from test_crypto import FIELDS, order
from wealth_ledger.crypto import import_bull_orders, make_crypto_view
from wealth_ledger.crypto_opening import import_opening, latest_opening
from wealth_ledger.reporting import generate_reports
from wealth_ledger.workbook import build_workbook
from wealth_ledger.validation import validate_formula_caches


class OpeningTests(unittest.TestCase):
    setUp = combined_fixture.CombinedTests.setUp
    tearDown = combined_fixture.CombinedTests.tearDown
    payload = combined_fixture.CombinedTests.payload

    def declaration(self, **overrides):
        data={'reported_total_btc_equivalent':'0.00331086',
              'reference_as_of':'2026-10-09T22:28:00-04:00', 'declared_on':'2026-10-10',
              'balance_scope':'all_wallets_btc_plus_lbtc', 'basis':'User attributes difference to pre-Bull holdings',
              'confirmed_by':'synthetic-user'}
        data.update(overrides)
        path=self.root/'incoming/opening.json'
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_exact_difference_is_separate_from_orders_and_unknown_cost(self):
        before=self.payload()
        path=self.declaration()
        result=import_opening(self.root,path)
        self.assertEqual(result['opening_btc_equivalent_qty'],'0.00081086')
        self.assertIsNone(result['historical_contribution_cad'])
        view=make_crypto_view(self.root,before['meta']['as_of'])
        self.assertEqual(view['btc_equivalent_qty'],'0.00331086')
        self.assertEqual(view['purchased_btc_equivalent_qty'],'0.0025')
        self.assertEqual(view['monthly'][-1]['cumulative_btc_equivalent_qty'],'0.0025')
        self.assertEqual(view['total_buy_cost_cad'],'250')
        self.assertEqual(view['total_funding_cad'],'300')
        after=self.payload()
        self.assertNotEqual(before['meta']['scope_id'],after['meta']['scope_id'])
        self.assertEqual(len(after['history']),1)
        self.assertFalse(after['changes']['available'])
        self.assertEqual(Decimal(after['totals']['total_cad'])-Decimal(before['totals']['total_cad']),Decimal('162.172'))
        for row in [r for r in after['positions']+after['securities'] if r['security_type']=='CRYPTO']:
            for key in ('book_native','book_cad','avg_cost','unrealized_native','unrealized_pct'):
                self.assertIsNone(row[key])
        self.assertIsNone(after['totals']['book_native_cad'])
        self.assertIsNone(after['crypto']['valuation']['unrealized_cad'])
        with sqlite3.connect(self.root/'data/db/portfolio.sqlite3') as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM cash_flows').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM crypto_order_revisions').fetchone()[0],3)
            self.assertEqual(json.loads(conn.execute('SELECT opening_json FROM crypto_accounts').fetchone()[0])['btc'],'0')
        archived=self.root/latest_opening(self.root)['source_path']
        self.assertEqual(archived.read_bytes(),path.read_bytes())
        self.assertTrue(latest_opening(self.root)['integrity_ok'])

    def test_duplicate_after_new_order_does_not_recompute_or_double_count(self):
        declaration=self.declaration();first=import_opening(self.root,declaration)
        path=self.root/'incoming/new.csv'
        with path.open('w',newline='', encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,FIELDS);writer.writeheader()
            writer.writerow(order('new','Buy Bitcoin','25','BTC','.0001',created='2026-10-10T00:00:00Z',completed='2026-10-10T01:00:00Z'))
        import_bull_orders(self.root,path)
        duplicate=import_opening(self.root,declaration)
        self.assertEqual(duplicate['status'],'duplicate')
        self.assertEqual(duplicate['id'],first['id'])
        view=make_crypto_view(self.root,'2026-10-10T17:00:00-04:00')
        self.assertEqual(view['opening_btc_equivalent_qty'],'0.00081086')
        self.assertEqual(view['btc_equivalent_qty'],'0.00341086')
        self.assertEqual(view['cash_cad'],'25')
        self.assertEqual(latest_opening(self.root)['reference_purchased_btc_equivalent'],'0.0025')

    def test_invalid_declarations_do_not_record_revisions(self):
        for overrides in [ {'reported_total_btc_equivalent':'0.001'},
              {'reported_total_btc_equivalent':'NaN'}, {'reported_total_btc_equivalent':'bad'},
              {'reported_total_btc_equivalent':'0.003310861'}, {'balance_scope':'one_wallet'},
              {'reference_as_of':'2026-10-09T22:28:00'}, {'basis':None},
              {'reference_as_of':'2026-11-09T22:28:00-05:00'}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                import_opening(self.root,self.declaration(**overrides))
        self.assertIsNone(latest_opening(self.root))

    def test_revision_keeps_original_and_start_boundary(self):
        first=import_opening(self.root,self.declaration())
        second=import_opening(self.root,self.declaration(reported_total_btc_equivalent='0.0034',basis='Explicit corrected total'))
        self.assertEqual(second['revision'],2)
        self.assertEqual(latest_opening(self.root)['id'],second['id'])
        self.assertIsNone(latest_opening(self.root,cutoff='2025-12-31T23:00:00Z'))
        with sqlite3.connect(self.root/'data/db/portfolio.sqlite3') as conn:
            old=json.loads(conn.execute('SELECT payload_json FROM crypto_opening_revisions WHERE id=?',(first['id'],)).fetchone()[0])
            self.assertEqual(old['opening_btc_equivalent_qty'],'0.00081086')

    def test_reports_keep_unknown_cost_text_and_valid_market_formulas(self):
        import_opening(self.root,self.declaration())
        payload=self.payload();output=self.root/'reports-test'
        result=generate_reports(payload,output)
        ods=output/'portfolio.ods'
        build_workbook(payload,ods,chart_images=result['charts'])
        self.assertEqual(validate_formula_caches(ods)['cache_mismatches'],0)
        md=(output/'report.md').read_text(encoding="utf-8")
        self.assertIn('0.00081086',md)
        self.assertIn('使用 Bull 前取得成本 CAD',md)
        self.assertIn('Bull 購入 BTC 等值合計',md)
        self.assertIn('目前有效期初持倉（Bull 使用前）',md)
        self.assertNotIn('原 Bull 假設',md)
        self.assertNotIn('BTC 期初聲明稽核（原始假設）',md)
        self.assertIn('未計算；尚未提供餘額觀測',md)
        self.assertIn('Bull CSV 沒有使用 Bull 前的交易',md)
        self.assertIn('Bull 已知購入成本',md)
        audit=json.loads((output/'btc-opening-audit.json').read_text(encoding="utf-8"))
        self.assertEqual(audit['original_bull_ledger_assumptions'],payload['crypto']['assumptions'])
        self.assertEqual(audit['effective_pre_bull_opening_declaration'],payload['crypto']['opening'])
        self.assertEqual(result['supplements'],['btc-opening-audit.json','btc-cost-estimate.json'])
        self.assertIsNone(audit['effective_pre_bull_opening_declaration']['cost_cad'])
        with zipfile.ZipFile(ods) as archive:
            root=ET.fromstring(archive.read('content.xml'))
        ns={'t':'urn:oasis:names:tc:opendocument:xmlns:table:1.0'}
        sheets=root.findall('.//t:table',ns)
        btc=next(s for s in sheets if s.get('{'+ns['t']+'}name')=='比特幣追蹤')
        rows=btc.findall('t:table-row',ns)
        self.assertIn("期初 BTC＋LBTC 等值", "".join(rows[33].itertext()))
        self.assertIn("0.00081086", "".join(rows[33].itertext()))
        self.assertIn("使用 Bull 前取得成本", "".join(rows[34].itertext()))
        self.assertIn("未提供", "".join(rows[34].itertext()))
        self.assertNotIn("原 Bull 假設", "".join(rows[33].itertext()))
        self.assertNotIn("原 Bull 假設", "".join(btc.itertext()))
        self.assertIn("Bull 已知購入成本", "".join(rows[17].itertext()))
        self.assertEqual(rows[17].findall("t:table-cell",ns)[2].get("{urn:oasis:names:tc:opendocument:xmlns:office:1.0}value"),"250")
        for index,value in ((9,'331.086'),(15,'331.086'),(16,'1'),(31,'100000')):
            cell=rows[index-1].findall('t:table-cell',ns)[2]
            self.assertEqual(Decimal(cell.get('{urn:oasis:names:tc:opendocument:xmlns:office:1.0}value')),Decimal(value))
            self.assertIsNotNone(cell.get('{'+ns['t']+'}formula'))
            if index != 31:self.assertIn('Bull 均價推估',''.join(rows[index-1].itertext()))
        self.assertIn('| 全持倉估算成本 CAD（Bull 均價推估） | 331.09 |',md)
        self.assertGreater((output/'report.pdf').stat().st_size,1000)
        from wealth_ledger.report_checks import validate_report_presentation
        self.assertEqual(validate_report_presentation(payload,output)["status"],"passed")
        original_md=(output/'report.md').read_text(encoding="utf-8")
        (output/'report.md').write_text(original_md+"\n原 Bull 假設 BTC | 0.00000000\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"superseded original assumptions"):
            validate_report_presentation(payload,output)
        (output/'report.md').write_text(original_md, encoding="utf-8")
        (output/'report.md').write_text(original_md.replace('| Bull 已知購入成本 | 250.00 |','| Bull 已知購入成本 | 0.00 |'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"incorrect known Bull purchase amount"):
            validate_report_presentation(payload,output)
        (output/'report.md').write_text(original_md.replace('| 期初 BTC＋LBTC 等值 | 0.00081086 |','| 期初 BTC＋LBTC 等值 | 0 |'), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"misstates effective opening"):
            validate_report_presentation(payload,output)
        (output/'report.md').write_text(original_md, encoding="utf-8")
        original_audit=(output/'btc-opening-audit.json').read_text(encoding="utf-8")
        corrupted=json.loads(original_audit)
        corrupted['effective_pre_bull_opening_declaration']['opening_btc_equivalent_qty']='0'
        (output/'btc-opening-audit.json').write_text(json.dumps(corrupted), encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"active opening audit differs"):
            validate_report_presentation(payload,output)
        (output/'btc-opening-audit.json').write_text(original_audit, encoding="utf-8")
        original_ods=ods.read_bytes()
        with zipfile.ZipFile(ods) as archive:
            files=[(item,archive.read(item.filename)) for item in archive.infolist()]
        import copy
        for index,value,error in [(34,"0","effective opening quantity differs"),
                                  (18,"0","known Bull purchase cost was lost"),
                                  (9,"0","BTC cost estimate differs")]:
            with self.subTest(corrupted_row=index):
                changed=ET.fromstring(next(data for item,data in files if item.filename=='content.xml'))
                changed_btc=next(s for s in changed.findall('.//t:table',ns) if s.get('{'+ns['t']+'}name')=='比特幣追蹤')
                changed_cell=changed_btc.findall('t:table-row',ns)[index-1].findall('t:table-cell',ns)[2]
                changed_cell.set('{urn:oasis:names:tc:opendocument:xmlns:office:1.0}value',value)
                with zipfile.ZipFile(ods,'w') as archive:
                    for item,data in files:
                        archive.writestr(copy.copy(item),ET.tostring(changed) if item.filename=='content.xml' else data)
                with self.assertRaisesRegex(ValueError,error):
                    validate_report_presentation(payload,output)
        ods.write_bytes(original_ods)
        changed=ET.fromstring(next(data for item,data in files if item.filename=='content.xml'))
        changed_btc=next(s for s in changed.findall('.//t:table',ns) if s.get('{'+ns['t']+'}name')=='比特幣追蹤')
        changed_btc.findall('t:table-row',ns)[8].findall('t:table-cell',ns)[2].set('{'+ns['t']+'}formula',"of:=['比特幣追蹤'.C18]")
        with zipfile.ZipFile(ods,'w') as archive:
            for item,data in files:archive.writestr(copy.copy(item),ET.tostring(changed) if item.filename=='content.xml' else data)
        with self.assertRaisesRegex(ValueError,'incorrect cost or quantity basis'):
            validate_report_presentation(payload,output)
        ods.write_bytes(original_ods)


    def test_future_snapshot_keeps_opening_scope_and_unknown_cost(self):
        from test_core import FX,write_holdings
        from wealth_ledger.core import import_holdings
        import_opening(self.root,self.declaration())
        first=self.payload()
        csv_path=write_holdings(self.root/'incoming/next.csv',when='2026-11-09 22:28 GMT-05:00')
        import_holdings(self.root,csv_path,'monthly',{**FX,'usd_cad_date':'2026-11-09','usd_twd_date':'2026-11-09'})
        next_payload=self.payload()
        self.assertEqual(first['meta']['scope_id'],next_payload['meta']['scope_id'])
        self.assertEqual(next_payload['crypto']['btc_equivalent_qty'],'0.00331086')
        self.assertEqual(len(next_payload['history']),2)
        self.assertTrue(next_payload['changes']['available'])
        self.assertEqual(next_payload['changes']['totals']['total_cad']['change'],'0')
        self.assertIsNone(next_payload['crypto']['valuation']['unrealized_cad'])
        output=self.root/'future-report'
        result=generate_reports(next_payload,output)
        build_workbook(next_payload,output/'portfolio.ods',chart_images=result['charts'])
        self.assertEqual(validate_formula_caches(output/'portfolio.ods')['cache_mismatches'],0)
        from wealth_ledger.report_checks import validate_report_presentation
        self.assertEqual(validate_report_presentation(next_payload,output)["status"],"passed")
