"""Pinned wholly synthetic old archives and independent literal bridge expectations.

Archives were frozen once using the unchanged built-ins. Bridge tests replay exact
saved bytes; no parser is needed or allowed during conversion. No private inputs.
"""
from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext
import hashlib
import json
import unittest
from unittest.mock import patch

from wealth_ledger import source_v2 as old
from wealth_ledger import source_protocol as protocol
from wealth_ledger.domain import canonical_v1 as c
from wealth_ledger.domain import validation_v1 as v
from wealth_ledger.domain import legacy_bridge_v1 as b

WS_RAW = b'Account Name,Account Type,Account Classification,Account Number,Symbol,Exchange,MIC,Name,Security Type,Quantity,Position Direction,Market Price,Market Price Currency,Book Value (CAD),Book Value Currency (CAD),Book Value (Market),Book Value Currency (Market),Market Value,Market Value Currency,Market Unrealized Returns,Market Unrealized Returns Currency\r\nTFSA,TFSA,Trade,DEMO-TFSA,VEQT,TSX,XTSE,Synthetic ETF demonstration,EXCHANGE_TRADED_FUND,10,LONG,20,CAD,180,CAD,180,CAD,200,CAD,20,CAD\r\nRRSP,RRSP,Trade,DEMO-RRSP,DEMO-B,NASDAQ,XNAS,Synthetic Beta Corporation,EQUITY,5,LONG,25,USD,150.0,CAD,100,USD,125,USD,25,USD\r\n\r\nAs of 2024-02-01 10:00 GMT-05:00\r\n'
WS_ARCHIVE = b'{"accounts":[{"account_type":"TFSA","key":{"account_id":"a_0ed1813837ced871","provider":"wealthsimple"},"label":"TFSA","masked_identifier":"****TFSA","role":"investment"},{"account_type":"RRSP","key":{"account_id":"a_8c7d2620cdc6d898","provider":"wealthsimple"},"label":"RRSP","masked_identifier":"****RRSP","role":"investment"}],"adapter":{"adapter_id":"wealthsimple.holdings","adapter_version":"0.1.0","api_version":2,"export_versions":["wealthsimple-holdings-footer-v1"],"kinds":["holdings"],"provider_id":"wealthsimple"},"coverage":[{"account":{"account_id":"a_0ed1813837ced871","provider":"wealthsimple"},"basis":"Rows present in this export; no activity or omitted-position inference","end":"2024-02-01T10:00:00-05:00","kind":"holdings","observation_id":"holdings:2024-02-01T15:00:00+00:00","revision":"19413dbdaf6906629fd238ecfaf4ccce2dcfa1271cbbf5b96ad3f1ee70732859","scope_id":"exported-positions","start":"2024-02-01T10:00:00-05:00","status":"partial","supersedes_revision":null},{"account":{"account_id":"a_8c7d2620cdc6d898","provider":"wealthsimple"},"basis":"Rows present in this export; no activity or omitted-position inference","end":"2024-02-01T10:00:00-05:00","kind":"holdings","observation_id":"holdings:2024-02-01T15:00:00+00:00","revision":"19413dbdaf6906629fd238ecfaf4ccce2dcfa1271cbbf5b96ad3f1ee70732859","scope_id":"exported-positions","start":"2024-02-01T10:00:00-05:00","status":"partial","supersedes_revision":null}],"evidence":{"context":{"account_alias":null,"evidence_at":"2024-03-01T12:00:00+00:00","format_selection":null,"revisions":[],"scope_revisions":[],"source_reference":"fabricated-domain-archive-v1","source_timezone":null},"diagnostics":[],"effective_at":"2024-02-01T10:00:00-05:00","id_policy":"Legacy hashed account/security IDs; UTC observation and semantic snapshot hash; explicit correction parents","mappings":[["legacy_semantic_hash","19413dbdaf6906629fd238ecfaf4ccce2dcfa1271cbbf5b96ad3f1ee70732859"]],"raw_sha256":"04ea2e1e7e51b65bba89e47617e742b0047da42c4f9b4324a8816b6302d06184","source_fields":[]},"export_version":"wealthsimple-holdings-footer-v1","membership":{"accounts":[{"account_id":"a_0ed1813837ced871","provider":"wealthsimple"},{"account_id":"a_8c7d2620cdc6d898","provider":"wealthsimple"}],"basis":"Exported accounts only; absence does not establish portfolio completeness","revision":"1fefd369baf2fdf0d5b73360bb04b446fbcfdf35b1cf500b71592c916a817694","scope_id":"exported-accounts","status":"unknown","supersedes_revision":null},"records":[{"as_of":"2024-02-01T10:00:00-05:00","asset":{"currency":"CAD","identifier":null,"kind":"security","market":"XTSE","network":null,"symbol":"VEQT"},"cost_cad":{"amount":"180","currency":"CAD"},"cost_native":{"amount":"180","currency":"CAD"},"exchange":"TSX","instrument_type":"EXCHANGE_TRADED_FUND","key":{"account":{"account_id":"a_0ed1813837ced871","provider":"wealthsimple"},"change":"original","revision":"19413dbdaf6906629fd238ecfaf4ccce2dcfa1271cbbf5b96ad3f1ee70732859","source_id":"XTSE:VEQT:CAD","supersedes_revision":null},"kind":"holdings","market_value":{"amount":"200","currency":"CAD"},"name":"Synthetic ETF demonstration","observation_id":"holdings:2024-02-01T15:00:00+00:00","quantity":"10","revision_reason":null,"source_fields":[],"unit_price":{"amount":"20","currency":"CAD"},"unrealized":{"amount":"20","currency":"CAD"}},{"as_of":"2024-02-01T10:00:00-05:00","asset":{"currency":"USD","identifier":null,"kind":"security","market":"XNAS","network":null,"symbol":"DEMO-B"},"cost_cad":{"amount":"150","currency":"CAD"},"cost_native":{"amount":"100","currency":"USD"},"exchange":"NASDAQ","instrument_type":"EQUITY","key":{"account":{"account_id":"a_8c7d2620cdc6d898","provider":"wealthsimple"},"change":"original","revision":"19413dbdaf6906629fd238ecfaf4ccce2dcfa1271cbbf5b96ad3f1ee70732859","source_id":"XNAS:DEMO-B:USD","supersedes_revision":null},"kind":"holdings","market_value":{"amount":"125","currency":"USD"},"name":"Synthetic Beta Corporation","observation_id":"holdings:2024-02-01T15:00:00+00:00","quantity":"5","revision_reason":null,"source_fields":[],"unit_price":{"amount":"25","currency":"USD"},"unrealized":{"amount":"25","currency":"USD"}}],"snapshots":[{"accounts":[{"account_id":"a_0ed1813837ced871","provider":"wealthsimple"},{"account_id":"a_8c7d2620cdc6d898","provider":"wealthsimple"}],"as_of":"2024-02-01T10:00:00-05:00","revision":"19413dbdaf6906629fd238ecfaf4ccce2dcfa1271cbbf5b96ad3f1ee70732859","source_id":"holdings:2024-02-01T15:00:00+00:00","supersedes_revision":null}]}'
WS_RAW_SHA256 = '04ea2e1e7e51b65bba89e47617e742b0047da42c4f9b4324a8816b6302d06184'
WS_ARCHIVE_SHA256 = 'a1fe06cc6aad4dda4dad135ed92c85aeeb8436746e4986a8d6a1c6ee0908275b'

BULL_RAW = b'ORDER_ID,ORDER_TYPE,PAYIN_AMOUNT,PAYIN_CURRENCY,PAYOUT_AMOUNT,PAYOUT_CURRENCY,PAYIN_METHOD,PAYOUT_METHOD,ORDER_STATUS,PAYIN_STATUS,PAYOUT_STATUS,CREATED_AT (UTC),COMPLETED_AT (UTC),SENT_AT (UTC),ORDER_NUMBER,ORDER_SUBTYPE,MESSAGE,TRANSACTION_ID,ADDRESS,EXCHANGE_RATE_AMOUNT,EXCHANGE_RATE_CURRENCY,INDEX_RATE_AMOUNT,INDEX_RATE_CURRENCY\r\nDEMO-FUND,Funding,1000,CAD,1000,CAD,Interac e-Transfer (CAD),CAD Balance,Completed,Completed,Completed,2024-01-01T12:00:00Z,2024-01-01T12:01:00Z,2024-01-01T12:01:00Z,SYNTHETIC-EXAMPLE,Market Order,SYNTHETIC EXAMPLE ONLY,,,100000,CAD,100000,\r\nDEMO-BUY-BTC,Buy Bitcoin,400,CAD,.004,BTC,CAD Balance,Bitcoin On-Chain,Completed,Completed,Completed,2024-01-02T12:00:00Z,2024-01-02T12:01:00Z,2024-01-02T12:01:00Z,SYNTHETIC-EXAMPLE,Market Order,SYNTHETIC EXAMPLE ONLY,,,100000,CAD,100000,CAD\r\nDEMO-BUY-LBTC,Buy Bitcoin,300,CAD,.003,LBTC,CAD Balance,Liquid Network,Completed,Completed,Completed,2024-01-03T12:00:00Z,2024-01-03T12:01:00Z,2024-01-03T12:01:00Z,SYNTHETIC-EXAMPLE,Market Order,SYNTHETIC EXAMPLE ONLY,,,100000,CAD,100000,CAD\r\n'
BULL_ARCHIVE = b'{"accounts":[{"account_type":"crypto","key":{"account_id":"fabricated-bull","provider":"bullbitcoin"},"label":"Bitcoin deliveries","masked_identifier":null,"role":"crypto"},{"account_type":"CAD balance","key":{"account_id":"fabricated-bull:cad","provider":"bullbitcoin"},"label":"Purchase funding","masked_identifier":null,"role":"funding"}],"adapter":{"adapter_id":"bullbitcoin.orders","adapter_version":"0.1.0","api_version":2,"export_versions":["bullbitcoin-orders-utc-v1"],"kinds":["cash_flows","crypto_transactions"],"provider_id":"bullbitcoin"},"coverage":[{"account":{"account_id":"fabricated-bull:cad","provider":"bullbitcoin"},"basis":"Observed order rows only; gaps and external wallet events remain unverified","end":"2024-01-01T12:01:00+00:00","kind":"cash_flows","observation_id":"","revision":"17db4b8fb67bc16f0fa08554512001f8064d5111ed474c19a232c9d3f5d54c95","scope_id":"exported-orders","start":"2024-01-01T12:01:00+00:00","status":"partial","supersedes_revision":null},{"account":{"account_id":"fabricated-bull","provider":"bullbitcoin"},"basis":"Observed order rows only; gaps and external wallet events remain unverified","end":"2024-01-03T12:01:00+00:00","kind":"crypto_transactions","observation_id":"","revision":"0178e94d34c04d65dbcac29ee0d8e6ea906c295d5549a1e643cb4b9834511e60","scope_id":"exported-orders","start":"2024-01-02T12:01:00+00:00","status":"partial","supersedes_revision":null}],"evidence":{"context":{"account_alias":"fabricated-bull","evidence_at":"2024-03-01T12:00:00+00:00","format_selection":null,"revisions":[],"scope_revisions":[],"source_reference":"fabricated-domain-archive-v1","source_timezone":null},"diagnostics":[{"code":"wallet_balance_unverified","parameters":[],"severity":"warning"},{"code":"wallet_fees_unknown","parameters":[],"severity":"warning"},{"code":"observed_order_rows","parameters":[["rows","3"],["duplicates","0"]],"severity":"info"}],"effective_at":"2024-01-03T12:01:00+00:00","id_policy":"Legacy provider/alias/order hash and normalized order content hash; explicit revision parents","mappings":[["legacy_semantic_hash","33d40942af5bd04d4fa8d201bd3261f0baca9e397875a0a1d5702d3cc096350a"]],"raw_sha256":"8c1473bf4f9620f6cca4cc727e87a78b2330928aa6add06c386881ae57cfa286","source_fields":[]},"export_version":"bullbitcoin-orders-utc-v1","membership":{"accounts":[{"account_id":"fabricated-bull","provider":"bullbitcoin"},{"account_id":"fabricated-bull:cad","provider":"bullbitcoin"}],"basis":"Named source order accounts only; neither wallet balances nor opening assumptions are declared","revision":"64a343b584eb66a975e1bf5ee07986d37811a0cab1fd19d7b5d2e60b98fcab6c","scope_id":"source-accounts:6a50315cb776feb33b785a3f002dc7eac38e25108ac39ac81d1608ce66a42713","status":"unknown","supersedes_revision":null},"records":[{"acquisition_cost":{"amount":"400","currency":"CAD"},"acquisition_cost_cad":{"amount":"400","currency":"CAD"},"counterpart":null,"fees":null,"key":{"account":{"account_id":"fabricated-bull","provider":"bullbitcoin"},"change":"original","revision":"bc6b1881101a411b3ae82b2ddeb51223696305ec8f43d45620227975e88463d6","source_id":"co_0f4671c887bf5762382933c3eb45c02f2bd06442d427c0dbd8bc1845c666e9e4","supersedes_revision":null},"kind":"crypto_transactions","legs":[{"account":{"account_id":"fabricated-bull:cad","provider":"bullbitcoin"},"asset":{"currency":"CAD","identifier":null,"kind":"cash","market":null,"network":null,"symbol":"CAD"},"quantity":"-400"},{"account":{"account_id":"fabricated-bull","provider":"bullbitcoin"},"asset":{"currency":"CAD","identifier":null,"kind":"crypto","market":null,"network":"bitcoin","symbol":"BTC"},"quantity":"0.004"}],"lifecycle":{"completed_at":"2024-01-02T12:01:00+00:00","created_at":"2024-01-02T12:00:00+00:00","exchange_rate":{"amount":"100000","unit":"CAD"},"index_rate":{"amount":"100000","unit":"CAD"},"payin":{"asset":{"currency":"CAD","identifier":null,"kind":"cash","market":null,"network":null,"symbol":"CAD"},"method":"CAD Balance","quantity":"400"},"payin_status":"Completed","payout":{"asset":{"currency":"CAD","identifier":null,"kind":"crypto","market":null,"network":"bitcoin","symbol":"BTC"},"method":"Bitcoin On-Chain","quantity":"0.004"},"payout_status":"Completed","sent_at":"2024-01-02T12:01:00+00:00","source_status":"Completed","source_subtype":"Market Order","source_type":"Buy Bitcoin"},"occurred_at":"2024-01-02T12:01:00+00:00","revision_reason":null,"source_fields":[["completed_at","2024-01-02T12:01:00.000000+00:00"],["created_at","2024-01-02T12:00:00.000000+00:00"],["exchange_rate_amount","100000"],["exchange_rate_currency","CAD"],["index_rate_amount","100000"],["index_rate_currency","CAD"],["network","bitcoin"],["order_id","DEMO-BUY-BTC"],["order_key","co_0f4671c887bf5762382933c3eb45c02f2bd06442d427c0dbd8bc1845c666e9e4"],["order_status","Completed"],["order_subtype","Market Order"],["order_type","Buy Bitcoin"],["payin_amount","400"],["payin_currency","CAD"],["payin_method","CAD Balance"],["payin_status","Completed"],["payout_amount","0.004"],["payout_currency","BTC"],["payout_method","Bitcoin On-Chain"],["payout_status","Completed"],["sent_at","2024-01-02T12:01:00.000000+00:00"]],"status":"completed","transfer_reference":null,"type":"purchase"},{"acquisition_cost":{"amount":"300","currency":"CAD"},"acquisition_cost_cad":{"amount":"300","currency":"CAD"},"counterpart":null,"fees":null,"key":{"account":{"account_id":"fabricated-bull","provider":"bullbitcoin"},"change":"original","revision":"ee9bc8dcc0b7ed52bd018fd7568794054ce214ebb4a586de4da25b467b6b76cf","source_id":"co_873b0cf8e183795aa643693ae2eb323ec299a4df0ca64ac26b1c9802028ece37","supersedes_revision":null},"kind":"crypto_transactions","legs":[{"account":{"account_id":"fabricated-bull:cad","provider":"bullbitcoin"},"asset":{"currency":"CAD","identifier":null,"kind":"cash","market":null,"network":null,"symbol":"CAD"},"quantity":"-300"},{"account":{"account_id":"fabricated-bull","provider":"bullbitcoin"},"asset":{"currency":"CAD","identifier":null,"kind":"crypto","market":null,"network":"liquid","symbol":"LBTC"},"quantity":"0.003"}],"lifecycle":{"completed_at":"2024-01-03T12:01:00+00:00","created_at":"2024-01-03T12:00:00+00:00","exchange_rate":{"amount":"100000","unit":"CAD"},"index_rate":{"amount":"100000","unit":"CAD"},"payin":{"asset":{"currency":"CAD","identifier":null,"kind":"cash","market":null,"network":null,"symbol":"CAD"},"method":"CAD Balance","quantity":"300"},"payin_status":"Completed","payout":{"asset":{"currency":"CAD","identifier":null,"kind":"crypto","market":null,"network":"liquid","symbol":"LBTC"},"method":"Liquid Network","quantity":"0.003"},"payout_status":"Completed","sent_at":"2024-01-03T12:01:00+00:00","source_status":"Completed","source_subtype":"Market Order","source_type":"Buy Bitcoin"},"occurred_at":"2024-01-03T12:01:00+00:00","revision_reason":null,"source_fields":[["completed_at","2024-01-03T12:01:00.000000+00:00"],["created_at","2024-01-03T12:00:00.000000+00:00"],["exchange_rate_amount","100000"],["exchange_rate_currency","CAD"],["index_rate_amount","100000"],["index_rate_currency","CAD"],["network","liquid"],["order_id","DEMO-BUY-LBTC"],["order_key","co_873b0cf8e183795aa643693ae2eb323ec299a4df0ca64ac26b1c9802028ece37"],["order_status","Completed"],["order_subtype","Market Order"],["order_type","Buy Bitcoin"],["payin_amount","300"],["payin_currency","CAD"],["payin_method","CAD Balance"],["payin_status","Completed"],["payout_amount","0.003"],["payout_currency","LBTC"],["payout_method","Liquid Network"],["payout_status","Completed"],["sent_at","2024-01-03T12:01:00.000000+00:00"]],"status":"completed","transfer_reference":null,"type":"purchase"},{"amount":{"amount":"1000","currency":"CAD"},"boundary":"unclassified","cash_leg_of":null,"counterpart":null,"direction":"in","key":{"account":{"account_id":"fabricated-bull:cad","provider":"bullbitcoin"},"change":"original","revision":"0cfecb85de364e8c15a88f894b7c533d770ed808f8b26de5ad85bb2f6e7137dc","source_id":"co_ee26b8cb21f5f6e8705b153dc2257a556a5a7555f9d34342dc1373d2aaaefcff","supersedes_revision":null},"kind":"cash_flows","lifecycle":{"completed_at":"2024-01-01T12:01:00+00:00","created_at":"2024-01-01T12:00:00+00:00","exchange_rate":{"amount":"100000","unit":"CAD"},"index_rate":null,"payin":{"asset":{"currency":"CAD","identifier":null,"kind":"cash","market":null,"network":null,"symbol":"CAD"},"method":"Interac e-Transfer (CAD)","quantity":"1000"},"payin_status":"Completed","payout":{"asset":{"currency":"CAD","identifier":null,"kind":"cash","market":null,"network":null,"symbol":"CAD"},"method":"CAD Balance","quantity":"1000"},"payout_status":"Completed","sent_at":"2024-01-01T12:01:00+00:00","source_status":"Completed","source_subtype":"Market Order","source_type":"Funding"},"occurred_at":"2024-01-01T12:01:00+00:00","revision_reason":null,"source_fields":[["completed_at","2024-01-01T12:01:00.000000+00:00"],["created_at","2024-01-01T12:00:00.000000+00:00"],["exchange_rate_amount","100000"],["exchange_rate_currency","CAD"],["index_rate_amount","100000"],["index_rate_currency",""],["network",""],["order_id","DEMO-FUND"],["order_key","co_ee26b8cb21f5f6e8705b153dc2257a556a5a7555f9d34342dc1373d2aaaefcff"],["order_status","Completed"],["order_subtype","Market Order"],["order_type","Funding"],["payin_amount","1000"],["payin_currency","CAD"],["payin_method","Interac e-Transfer (CAD)"],["payin_status","Completed"],["payout_amount","1000"],["payout_currency","CAD"],["payout_method","CAD Balance"],["payout_status","Completed"],["sent_at","2024-01-01T12:01:00.000000+00:00"]],"status":"completed","transfer_reference":null,"type":"deposit"}],"snapshots":[]}'
BULL_RAW_SHA256 = '8c1473bf4f9620f6cca4cc727e87a78b2330928aa6add06c386881ae57cfa286'
BULL_ARCHIVE_SHA256 = 'b8b589bb1f95a30f3a14b7be6ecb0de9062b8eabef2b944a75d8931ed9c0a049'

# This inventory is independently pinned, not generated from production fields.
# Every listed field uses recoverable exact archive evidence; selected domain
# destinations are asserted separately. A newly introduced old field fails here.
INVENTORY = {
    "AccountKey": ("provider","account_id"),
    "AssetKey": ("kind","symbol","currency","market","network","identifier"),
    "Money": ("amount","currency"),
    "RecordKey": ("account","source_id","revision","supersedes_revision","change"),
    "CryptoLeg": ("account","asset","quantity"),
    "AdapterInfo": ("provider_id","adapter_id","adapter_version","export_versions","kinds","api_version"),
    "RevisionContext": ("account","kind","source_id","observation_id","supersedes_revision"),
    "ScopeRevisionContext": ("kind","scope_id","supersedes_revision","account","record_kind","observation_id"),
    "ParseContext": ("evidence_at","source_reference","account_alias","source_timezone","format_selection","revisions","scope_revisions"),
    "Diagnostic": ("code","severity","parameters"),
    "Evidence": ("raw_sha256","context","effective_at","id_policy","mappings","diagnostics","source_fields"),
    "Account": ("key","account_type","label","role","masked_identifier"),
    "Membership": ("scope_id","revision","accounts","status","basis","supersedes_revision"),
    "Coverage": ("kind","account","start","end","status","basis","scope_id","revision","supersedes_revision","observation_id"),
    "Snapshot": ("source_id","revision","as_of","accounts","supersedes_revision"),
    "Position": ("key","observation_id","as_of","asset","name","instrument_type","exchange","quantity","market_value","unit_price","cost_native","cost_cad","unrealized","revision_reason","source_fields","kind"),
    "Reference": ("account","kind","source_id"),
    "AssetAmount": ("asset","quantity","method"),
    "Rate": ("amount","unit"),
    "Lifecycle": ("created_at","completed_at","sent_at","source_type","source_subtype","source_status","payin_status","payout_status","payin","payout","exchange_rate","index_rate"),
    "Fee": ("account","asset","quantity","included_in_leg","included_in_cost"),
    "CashFlow": ("key","occurred_at","type","direction","amount","status","boundary","transfer_reference","counterpart","cash_leg_of","lifecycle","revision_reason","source_fields","kind"),
    "CryptoTransaction": ("key","occurred_at","type","status","legs","acquisition_cost","acquisition_cost_cad","fees","lifecycle","transfer_reference","counterpart","revision_reason","source_fields","kind"),
    "NormalizedBatch": ("adapter","export_version","evidence","accounts","membership","snapshots","coverage","records"),
}
TENANT="30000000-0000-4000-8000-000000000001"
PORTFOLIO="30000000-0000-4000-8000-000000000002"


def ref(kind, number):
    return c.ScopedIdV1(TENANT,PORTFOLIO,kind,f"40000000-0000-4000-8000-{number:012d}")


def context_for(batch):
    """Synthetic host assignments by exact source selectors, never labels/signs."""
    connection=ref("connection",1)
    accounts=tuple(c.FinancialAccountV1(ref("account",10+i),a.account_type,a.role,a.label) for i,a in enumerate(batch.accounts))
    aliases=tuple(c.AccountAliasV1(connection,a.key.provider,a.key.account_id,accounts[i].id,"mapping-v1","fabricated-mapping-e1") for i,a in enumerate(batch.accounts))
    def selector(record):
        return c.SourceSelectorV1(connection,batch.adapter.provider_id,record.key.account.account_id,record.kind,record.key.source_id,record.observation_id if type(record) is old.Position else "",record.key.revision)
    sources=tuple(selector(record) for record in batch.records)
    assets=[]
    for record in batch.records:
        candidates=[record.asset] if type(record) is old.Position else []
        if type(record) is old.CryptoTransaction:
            candidates += [leg.asset for leg in record.legs]
            candidates += [fee.asset for fee in record.fees or ()]
        if type(record) is not old.Position and record.lifecycle is not None:
            candidates += [record.lifecycle.payin.asset,record.lifecycle.payout.asset]
        for asset in candidates:
            if asset not in assets:assets.append(asset)
    mappings=[]
    for i,asset in enumerate(assets):
        instrument=c.InstrumentV1(ref("instrument",50+i),asset.kind.upper(),asset.currency,asset.symbol if asset.kind=="security" else None,asset.market,asset.symbol if asset.kind=="crypto" else None,asset.network,asset.network if asset.kind=="crypto" else None,None,(),"Fabricated explicit source descriptor","fabricated-mapping-e1")
        mappings.append(b.InstrumentMappingV1(asset,instrument))
    # These builtin synthetic purchases have a documented CAD payment at ordinal
    # zero and BTC/LBTC acquisition at ordinal one. Roles are explicit, not signs.
    roles=tuple(b.LegRoleAssignmentV1(sources[i],j,role) for i,r in enumerate(batch.records) if type(r) is old.CryptoTransaction for j,role in enumerate(("PAYMENT","ACQUISITION")))
    return b.BridgeContextV1(TENANT,PORTFOLIO,connection,(c.SourceConnectionV1(connection,batch.adapter.provider_id,"FILE_IMPORT"),),accounts,aliases,tuple(mappings),(),tuple(b.FactMappingV1(s,ref("fact",100+i)) for i,s in enumerate(sources)),tuple(b.SnapshotMappingV1(s.source_id,s.revision,ref("snapshot",200+i)) for i,s in enumerate(batch.snapshots)),roles,"mapping-v1","fabricated-mapping-e1")


def archived(batch, raw=BULL_RAW):
    return old.canonical_json(batch).encode(),raw


class DomainBridgeV1Tests(unittest.TestCase):
    def blocked(self,result,code,*,decoded=True):
        self.assertIsNone(result.candidate)
        self.assertIsNone(result.candidate_bytes)
        self.assertFalse(result.ingestible)
        self.assertEqual(result.blockers[0].code,code)
        self.assertEqual(result.original_batch is not None,decoded)
        return result

    def test_fixed_builtin_archives_hashes_ids_and_literal_financial_facts(self):
        for raw,canonical,rawhash,archivehash in ((WS_RAW,WS_ARCHIVE,WS_RAW_SHA256,WS_ARCHIVE_SHA256),(BULL_RAW,BULL_ARCHIVE,BULL_RAW_SHA256,BULL_ARCHIVE_SHA256)):
            self.assertEqual(hashlib.sha256(raw).hexdigest(),rawhash)
            self.assertEqual(hashlib.sha256(canonical).hexdigest(),archivehash)
            original=old.decode_batch(canonical,raw)
            result=b.bridge_parser_v2(raw,canonical,context_for(original))
            self.assertEqual(result.original_canonical,canonical)
            self.assertEqual(result.original_batch,original)
            self.assertEqual(result.canonical_sha256,archivehash)
            self.assertEqual(result.raw_sha256,rawhash)
            self.assertEqual(result.blockers,())
            self.assertFalse(result.ingestible)
            self.assertEqual(v.decode_domain_v1(result.candidate_bytes),result.candidate)
            self.assertIsNone(result.candidate.provenance.imported_at)
            self.assertIsNone(result.candidate.provenance.accepted_at)
        ws=b.bridge_parser_v2(WS_RAW,WS_ARCHIVE,context_for(old.decode_batch(WS_ARCHIVE,WS_RAW)))
        self.assertEqual([a.id for a in ws.candidate.accounts],[ref("account",10),ref("account",11)])
        items=ws.candidate.snapshots[0].items
        self.assertEqual([(p.identity.source.source_id,p.quantity.token,p.market_value.amount.token,p.market_value.currency) for p in items],[("XTSE:VEQT:CAD","10","200","CAD"),("XNAS:DEMO-B:USD","5","125","USD")])
        self.assertEqual([p.identity.source.source_account_key for p in items],["a_0ed1813837ced871","a_8c7d2620cdc6d898"])
        self.assertEqual([p.cost_cad.amount.token for p in items],["180","150"])
        self.assertEqual([cv.status for cv in ws.candidate.coverage],["partial","partial"])
        self.assertEqual(len(ws.candidate.snapshots[0].coverage),2)
        self.assertNotEqual(ws.candidate.snapshots[0].coverage[0].selector.source_account_key,ws.candidate.snapshots[0].coverage[1].selector.source_account_key)
        self.assertEqual(b.recover_legacy_v1(ws,c.LegacyRecordRefV1(WS_ARCHIVE_SHA256,"membership",None,"status")),"unknown")
        bull=b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,context_for(old.decode_batch(BULL_ARCHIVE,BULL_RAW)))
        buy=next(e for e in bull.candidate.activities if e.identity.source.source_id=="co_0f4671c887bf5762382933c3eb45c02f2bd06442d427c0dbd8bc1845c666e9e4")
        self.assertEqual((buy.kind,buy.legs[0].quantity.token,buy.legs[1].quantity.token),("BUY","-400","0.004"))
        self.assertEqual((buy.legs[0].role,buy.legs[1].role),("PAYMENT","ACQUISITION"))
        self.assertIsNone(buy.fees)
        self.assertEqual(buy.acquisition_cost.amount.token,"400")
        funding=next(e for e in bull.candidate.activities if e.cash_flow is not None)
        self.assertEqual((funding.cash_flow.cash_amount.amount.token,funding.cash_flow.direction,funding.cash_flow.boundary),("1000","in","unclassified"))
        self.assertEqual(funding.legs,())
        self.assertEqual({i.network for i in bull.candidate.instruments if i.kind=="CRYPTO"},{"bitcoin","liquid"})
        self.assertEqual(b.recover_legacy_v1(bull,buy.lifecycle).source_subtype,"Market Order")

    def test_full_separately_pinned_old_dataclass_inventory_and_recovery(self):
        protocol_names={"AccountKey","AssetKey","Money","RecordKey","CryptoLeg","AdapterInfo"}
        for name,names in INVENTORY.items():
            cls=getattr(protocol if name in protocol_names else old,name)
            self.assertEqual(tuple(field.name for field in fields(cls)),names,name)
        original=old.decode_batch(BULL_ARCHIVE,BULL_RAW)
        context=context_for(original)
        result=b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,context)
        recovered=b.recover_legacy_v1(result,c.LegacyRecordRefV1(BULL_ARCHIVE_SHA256,"batch",None,""))
        seen=set()
        def walk(value):
            if is_dataclass(value):
                name=type(value).__name__; seen.add(name)
                self.assertIn(name,INVENTORY)
                for fieldname in INVENTORY[name]:walk(getattr(value,fieldname))
            elif type(value) is tuple:
                for item in value:walk(item)
        walk(recovered)
        self.assertTrue({"NormalizedBatch","Evidence","ParseContext","Lifecycle","AssetAmount","Rate","AccountKey","AssetKey","CryptoLeg","CashFlow","CryptoTransaction"} <= seen)
        for i,record in enumerate(original.records):
            for fieldname in INVENTORY[type(record).__name__]:
                refvalue=c.LegacyRecordRefV1(BULL_ARCHIVE_SHA256,"records",i,fieldname)
                self.assertEqual(b.recover_legacy_v1(result,refvalue),getattr(record,fieldname))
        self.assertEqual(b.recover_legacy_v1(result,c.LegacyRecordRefV1(BULL_ARCHIVE_SHA256,"evidence",None,"context.source_reference")),"fabricated-domain-archive-v1")
        for reference in (c.LegacyRecordRefV1("f"*64,"batch",None,""),c.LegacyRecordRefV1(BULL_ARCHIVE_SHA256,"records",999,""),c.LegacyRecordRefV1(BULL_ARCHIVE_SHA256,"records",0,"__class__")):
            with self.assertRaises(v.DomainValidationError):b.recover_legacy_v1(result,reference)

    def test_missing_extra_ambiguous_roles_and_mapping_blocks_whole_candidate(self):
        oldbatch=old.decode_batch(BULL_ARCHIVE,BULL_RAW); context=context_for(oldbatch)
        variants=(replace(context,aliases=context.aliases[:-1]),replace(context,instruments=context.instruments[:-1]),replace(context,facts=context.facts[:-1]),replace(context,facts=context.facts+context.facts[:1]),replace(context,leg_roles=context.leg_roles[:-1]),replace(context,leg_roles=context.leg_roles+context.leg_roles[:1]),replace(context,accounts=(replace(context.accounts[0],role="funding"),)+context.accounts[1:]))
        for value in variants:
            with self.subTest(value=value):
                result=b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,value)
                self.assertIsNone(result.candidate)
                self.assertTrue(result.blockers)
                self.assertEqual(result.original_batch,oldbatch)
                self.assertEqual(result.original_canonical,BULL_ARCHIVE)
        self.blocked(b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,replace(context,leg_roles=())),"bridge_mapping_required")
        negative_roles=tuple(replace(role,role="ACQUISITION") for role in context.leg_roles)
        self.blocked(b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,replace(context,leg_roles=negative_roles)),"bridge_semantics_unrepresentable")

    def test_listing_dimensions_cannot_collapse_and_funding_role_preserved(self):
        original=old.decode_batch(WS_ARCHIVE,WS_RAW); context=context_for(original)
        first=context.instruments[0]
        # A caller may not quietly remap the same ticker to another venue/currency.
        for changes in ({"ticker":"OTHER"},{"mic":"XNAS"},{"currency":"USD"}):
            changed=replace(first,instrument=replace(first.instrument,**changes))
            result=b.bridge_parser_v2(WS_RAW,WS_ARCHIVE,replace(context,instruments=(changed,)+context.instruments[1:]))
            self.assertIsNone(result.candidate)
        second=replace(original.records[1],asset=replace(original.records[1].asset,symbol="VEQT",currency="CAD"),market_value=protocol.Money(Decimal("125"),"CAD"),unit_price=protocol.Money(Decimal("25"),"CAD"),cost_native=protocol.Money(Decimal("100"),"CAD"),unrealized=protocol.Money(Decimal("25"),"CAD"))
        changed=replace(original,records=(original.records[0],second)); canonical=old.canonical_json(changed).encode(); old.decode_batch(canonical,WS_RAW)
        ctx=context_for(changed); wrong=replace(ctx.instruments[1],instrument=ctx.instruments[0].instrument)
        self.blocked(b.bridge_parser_v2(WS_RAW,canonical,replace(ctx,instruments=(ctx.instruments[0],wrong))),"bridge_mapping_required")

    def test_legacy_70_integer_18_fraction_still_valid_optional_bridge_blocks(self):
        original=old.decode_batch(WS_ARCHIVE,WS_RAW)
        literal="1234567890"*7+".123456789012345678"
        record=replace(original.records[0],quantity=Decimal(literal))
        changed=replace(original,records=(record,)+original.records[1:])
        canonical=old.canonical_json(changed).encode()
        self.assertEqual(old.decode_batch(canonical,WS_RAW).records[0].quantity,Decimal(literal))
        result=self.blocked(b.bridge_parser_v2(WS_RAW,canonical,context_for(changed)),"bridge_precision_unrepresentable")
        self.assertEqual(result.original_canonical,canonical)
        self.assertEqual(old.decode_batch(canonical,WS_RAW).records[0].quantity.as_tuple(),Decimal(literal).as_tuple())
        # Huge exponents and legacy zero scale are inspected before fixed expansion.
        for token in ("1E+1000","0E-999999","1E-25","0E+39"):
            with self.assertRaises(v.DomainValidationError) as caught:b._decimal(Decimal(token))
            self.assertEqual(caught.exception.diagnostic.code,"bridge_precision_unrepresentable")
        for token,expected in (("1E+3","1000"),("1.2300","1.2300"),("-0.00","-0.00"),("0E+38","0")):
            self.assertEqual(b._decimal(Decimal(token)).token,expected)

    def test_invalid_old_bytes_no_original_object_no_arbitrary_old_error_echo(self):
        original=old.decode_batch(BULL_ARCHIVE,BULL_RAW); context=context_for(original)
        for raw,canonical in ((b"wrong",BULL_ARCHIVE),(BULL_RAW,BULL_ARCHIVE+b" "),(BULL_RAW,b'{"secret":"SENSITIVE_SENTINEL_123"}'),(BULL_RAW,BULL_ARCHIVE.replace(b'"api_version":2',b'"api_version":1'))):
            result=self.blocked(b.bridge_parser_v2(raw,canonical,context),"bridge_legacy_invalid",decoded=False)
            self.assertEqual(result.original_canonical,canonical)
            self.assertNotIn("SENSITIVE_SENTINEL",repr(result.blockers))
        result=self.blocked(b.bridge_parser_v2(BULL_RAW,b"x"*(4*1024*1024+1),context),"bridge_legacy_invalid",decoded=False)
        self.assertIsNone(result.canonical_sha256)
        bad=BULL_ARCHIVE.replace(b'"api_version":2',b'"api_version":1')
        with self.assertRaises(ValueError) as before:old.decode_batch(bad,BULL_RAW)
        b.bridge_parser_v2(BULL_RAW,bad,context)
        with self.assertRaises(ValueError) as after:old.decode_batch(bad,BULL_RAW)
        self.assertEqual(str(before.exception),str(after.exception))

    def test_exact_lifecycle_fields_fees_cash_links_source_fields_and_corrections(self):
        original=old.decode_batch(BULL_ARCHIVE,BULL_RAW)
        buy=next(r for r in original.records if type(r) is old.CryptoTransaction)
        fee=old.Fee(buy.legs[1].account,buy.legs[1].asset,Decimal("0.00000001"),True,False)
        parent=buy.key.revision
        buy=replace(buy,key=replace(buy.key,revision="corrected-r2",supersedes_revision=parent,change="correction"),revision_reason="Fabricated source correction",fees=(fee,),source_fields=(("fabricated_field","exact original value"),))
        context_old=replace(original.evidence.context,revisions=(old.RevisionContext(buy.key.account,buy.kind,buy.key.source_id,"",parent),))
        evidence=replace(original.evidence,context=context_old,diagnostics=(old.Diagnostic("synthetic_notice","info",(("source_detail","untouched source text"),)),),source_fields=(("original_header","exact source header"),))
        changed=replace(original,evidence=evidence,records=tuple(buy if r.key.source_id==buy.key.source_id else r for r in original.records))
        canonical=old.canonical_json(changed).encode(); old.decode_batch(canonical,BULL_RAW)
        result=b.bridge_parser_v2(BULL_RAW,canonical,context_for(changed))
        self.assertEqual(result.blockers,())
        converted=next(e for e in result.candidate.activities if e.identity.source.source_id==buy.key.source_id)
        self.assertEqual(converted.identity.parent.selector.revision,parent)
        self.assertEqual((converted.fees[0].quantity.token,converted.fees[0].included_in_leg,converted.fees[0].included_in_cost),("0.00000001",True,False))
        self.assertEqual(b.recover_legacy_v1(result,converted.lifecycle),buy.lifecycle)
        self.assertEqual(b.recover_legacy_v1(result,converted.identity.legacy).source_fields,(("fabricated_field","exact original value"),))
        self.assertEqual(result.original_batch.evidence.context.revisions,context_old.revisions)
        self.assertEqual(result.original_batch.evidence.diagnostics,evidence.diagnostics)
        self.assertEqual(result.original_batch.evidence.source_fields,evidence.source_fields)
        self.assertTrue(all(cv.time.start_inclusive and cv.time.end_inclusive for cv in result.candidate.coverage))
        self.assertTrue(all(e.event_time.precision=="legacy_unspecified" for e in result.candidate.activities))

    def test_same_connection_aliases_to_one_account_retain_each_source_fact(self):
        original=old.decode_batch(WS_ARCHIVE,WS_RAW)
        rows=(replace(original.records[0],quantity=Decimal("1.2500")),replace(original.records[1],quantity=Decimal("7.00")))
        changed=replace(original,records=rows)
        canonical=old.canonical_json(changed).encode()
        self.assertEqual(len(old.decode_batch(canonical,WS_RAW).accounts),2)
        context=context_for(changed)
        financial=context.accounts[0]
        context=replace(context,accounts=(financial,),aliases=tuple(replace(alias,account=financial.id) for alias in context.aliases))
        result=b.bridge_parser_v2(WS_RAW,canonical,context)
        self.assertEqual(result.blockers,())
        self.assertFalse(result.ingestible)
        self.assertEqual(result.candidate.snapshots[0].accounts,(financial.id,))
        self.assertEqual(len(result.candidate.coverage),2)
        self.assertEqual(len(result.candidate.snapshots[0].coverage),2)
        self.assertEqual([cv.source_account_key for cv in result.candidate.coverage],["a_0ed1813837ced871","a_8c7d2620cdc6d898"])
        self.assertEqual([item.quantity.token for item in result.candidate.snapshots[0].items],["1.2500","7.00"])
        self.assertEqual([item.identity.source.source_account_key for item in result.candidate.snapshots[0].items],["a_0ed1813837ced871","a_8c7d2620cdc6d898"])
        self.assertEqual(result.original_canonical,canonical)
        self.assertEqual(result.original_batch,changed)
        archived_snapshot=b.recover_legacy_v1(result,result.candidate.snapshots[0].legacy)
        self.assertEqual(archived_snapshot.accounts,original.snapshots[0].accounts)
        self.assertEqual(result.original_batch.membership.accounts,original.membership.accounts)
        self.assertEqual(v.decode_domain_v1(result.candidate_bytes),result.candidate)

    def test_bridge_fee_only_unsupported_instrument_is_explicit_and_exact(self):
        original=old.decode_batch(BULL_ARCHIVE,BULL_RAW)
        purchase=next(record for record in original.records if type(record) is old.CryptoTransaction)
        asset=protocol.AssetKey("security","FEE-UNIT","CAD",market="XTSX")
        fee=old.Fee(purchase.key.account,asset,Decimal("1.2500"),True,False)
        purchase=replace(purchase,fees=(fee,))
        changed=replace(original,records=tuple(purchase if record.key.source_id==purchase.key.source_id else record for record in original.records))
        canonical=old.canonical_json(changed).encode()
        old.decode_batch(canonical,BULL_RAW)
        context=context_for(changed)
        context=replace(context,instruments=tuple(replace(mapping,instrument=replace(mapping.instrument,kind="UNSUPPORTED")) if mapping.source==asset else mapping for mapping in context.instruments))
        result=b.bridge_parser_v2(BULL_RAW,canonical,context)
        self.assertEqual(result.blockers,())
        self.assertFalse(result.ingestible)
        event=next(event for event in result.candidate.activities if event.identity.source.source_id==purchase.key.source_id)
        self.assertEqual(event.support,c.SupportV1("unsupported",("unsupported_instrument",)))
        self.assertEqual((event.fees[0].quantity.token,event.fees[0].included_in_leg,event.fees[0].included_in_cost),("1.2500",True,False))
        self.assertEqual(b.recover_legacy_v1(result,event.identity.legacy).fees,(fee,))
        self.assertEqual(result.original_canonical,canonical)
        self.assertEqual(v.decode_domain_v1(result.candidate_bytes),result.candidate)

    def test_repeat_context_precision_and_supplied_times_are_exact(self):
        original=old.decode_batch(BULL_ARCHIVE,BULL_RAW); context=context_for(original)
        supplied=c.InstantV1("2024-03-02T12:34:56.123456Z",None,6)
        context=replace(context,imported_at=supplied,accepted_at=supplied)
        results=[]
        for precision in (6,100):
            with localcontext() as decimal_context:
                decimal_context.prec=precision
                results.append(b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,context))
        self.assertEqual(results[0],results[1])
        self.assertEqual(results[0].candidate.provenance.imported_at,supplied)
        self.assertEqual(results[0].candidate.provenance.accepted_at,supplied)
        self.assertEqual(results[0].original_canonical,BULL_ARCHIVE)
        self.assertEqual(old.canonical_json(original).encode(),BULL_ARCHIVE)

    def test_representation_overhead_is_all_or_nothing(self):
        original=old.decode_batch(BULL_ARCHIVE,BULL_RAW); context=context_for(original)
        good=b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,context)
        with patch.object(c,"MAX_CANONICAL_BYTES",len(good.candidate_bytes)):
            self.assertEqual(b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,context).candidate_bytes,good.candidate_bytes)
        with patch.object(c,"MAX_CANONICAL_BYTES",len(good.candidate_bytes)-1):
            result=self.blocked(b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,context),"domain_resource_limit")
            self.assertEqual(result.original_canonical,BULL_ARCHIVE)
            self.assertEqual(result.original_batch,original)

    def test_hostile_nested_context_cannot_execute_arbitrary_methods(self):
        class Unexpected:
            def __hash__(self):raise AssertionError("unexpected hash")
            def __eq__(self,other):raise AssertionError("unexpected equality")
            def __str__(self):raise AssertionError("unexpected formatter")
        original=old.decode_batch(BULL_ARCHIVE,BULL_RAW); context=context_for(original)
        asset=replace(context.instruments[0].source,symbol=Unexpected())
        variants=(replace(context,instruments=(replace(context.instruments[0],source=asset),)+context.instruments[1:]),replace(context,facts=(replace(context.facts[0],source=replace(context.facts[0].source,source_id=Unexpected())),)+context.facts[1:]),replace(context,aliases=(replace(context.aliases[0],source_account_key=Unexpected()),)+context.aliases[1:]))
        for value in variants:
            self.blocked(b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,value),"bridge_mapping_required")

    def test_bridge_never_dispatches_parser_or_application_io(self):
        import builtins
        from pathlib import Path
        import socket,sqlite3,subprocess,uuid
        from wealth_ledger.source_builtin import WealthsimpleHoldings,BullBitcoinOrders
        # No declared legacy source_timezone is supplied, so old strict validation
        # needs no timezone-reference lookup. Cold ZoneInfo I/O is not claimed pure.
        original=old.decode_batch(BULL_ARCHIVE,BULL_RAW); context=context_for(original)
        with patch.object(builtins,"open",side_effect=AssertionError("file I/O")),patch.object(Path,"open",side_effect=AssertionError("path I/O")),patch.object(socket,"socket",side_effect=AssertionError("network")),patch.object(sqlite3,"connect",side_effect=AssertionError("database")),patch.object(subprocess,"Popen",side_effect=AssertionError("process")),patch.object(uuid,"uuid4",side_effect=AssertionError("random UUID")),patch.object(WealthsimpleHoldings,"normalize",side_effect=AssertionError("parser call")),patch.object(BullBitcoinOrders,"normalize",side_effect=AssertionError("parser call")):
            result=b.bridge_parser_v2(BULL_RAW,BULL_ARCHIVE,context)
        self.assertEqual(result.blockers,())
        self.assertFalse(result.ingestible)


if __name__ == "__main__":unittest.main()
