"""Lossless parser-v2 fixtures and strict archive replay; no live financial data."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import Decimal as D
import hashlib
import json
import unittest

from wealth_ledger import source_v2 as v2
from wealth_ledger.source_protocol import AccountKey, AdapterInfo, AssetKey, CryptoLeg, Detection, Money, RecordKey
from wealth_ledger.source_testing import check_contract_v2

AT = datetime.fromisoformat("2024-01-31T17:00:00-05:00")
CONTEXT = v2.ParseContext(datetime.fromisoformat("2024-02-01T12:00:00+00:00"), "synthetic-export", "source-alias", "America/Toronto", "synthetic-v2")
RAW = b"format,source_id,quantity\nsynthetic-v2,position-001,1.25\n"
ACCOUNT = AccountKey("synthetic", "account-001")
META = v2.Account(ACCOUNT,"TFSA","Synthetic account","investment","****0001")
INFO = AdapterInfo("synthetic","synthetic.v2","0.1.0",("synthetic-v2",),("holdings","cash_flows","crypto_transactions"),api_version=2)
CAD = AssetKey("cash","CAD","CAD")
BTC = AssetKey("crypto","BTC","CAD",network="bitcoin")
LBTC = AssetKey("crypto","LBTC","CAD",network="liquid")
STOCK = AssetKey("security","DEMO","CAD",market="XTSX")
KEY = RecordKey(ACCOUNT,"position-001","r1")
POSITION = v2.Position(KEY,"snapshot-2024-01-31",AT,STOCK,"Synthetic company","STOCK","Synthetic exchange",D("1.25"),
    Money(D("125.00"),"CAD"),Money(D("100.00"),"CAD"),Money(D("90.00"),"CAD"),Money(D("90.00"),"CAD"),Money(D("35.00"),"CAD"))


def batch(records=(POSITION,), *, raw=RAW, accounts=(META,), snapshots=None, membership=None, context=CONTEXT, coverage=None):
    if snapshots is None:
        grouped = {}
        for record in records:
            if isinstance(record,v2.Position):
                grouped.setdefault(record.observation_id,[]).append(record)
        snapshots = tuple(v2.Snapshot(name,rows[0].key.revision,rows[0].as_of,
            tuple(dict.fromkeys(row.key.account for row in rows)),rows[0].key.supersedes_revision) for name,rows in grouped.items())
    if coverage is None:
        grouped = {}
        for record in records:
            observation = record.observation_id if isinstance(record,v2.Position) else ""
            grouped.setdefault((record.kind,record.key.account,observation),[]).append(record)
        coverage = []
        for (kind,account,observation),rows in grouped.items():
            times = [r.as_of if isinstance(r,v2.Position) else r.occurred_at for r in rows]
            snapshot = next((s for s in snapshots if s.source_id==observation),None)
            coverage.append(v2.Coverage(kind,account,min(times),max(times),"partial","Synthetic declared scope","records-"+kind,
                snapshot.revision if snapshot else "scope1",snapshot.supersedes_revision if snapshot else None,observation))
        coverage = tuple(coverage)
    membership = membership or v2.Membership("exported-accounts","scope1",tuple(a.key for a in accounts),"partial","Only supplied accounts")
    return v2.NormalizedBatch(INFO,"synthetic-v2",v2.Evidence(hashlib.sha256(raw).hexdigest(),context,AT,"Required stable source IDs"),
        accounts,membership,snapshots,coverage,records)


def purchase(*, key=None, fees=None, status="completed"):
    return v2.CryptoTransaction(key or replace(KEY,source_id="purchase-001"),AT,"purchase",status,
        (CryptoLeg(ACCOUNT,CAD,D("-100.00")),CryptoLeg(ACCOUNT,BTC,D("0.00100000"))),
        Money(D("100.00"),"CAD"),Money(D("100.00"),"CAD"),fees)


def funding(*, key=None):
    return v2.CashFlow(key or replace(KEY,source_id="funding-001"),AT,"deposit","in",Money(D("100.00"),"CAD"),"completed","unclassified")


class ParserV2Tests(unittest.TestCase):
    def test_native_and_cad_costs_prices_unknowns_and_source_detail_roundtrip(self):
        asset = replace(STOCK,currency="USD")
        position = replace(POSITION,asset=asset,market_value=Money(D("125.00"),"USD"),unit_price=Money(D("100.00"),"USD"),
            cost_native=Money(D("90.00"),"USD"),cost_cad=Money(D("111.11"),"CAD"),unrealized=Money(D("35.00"),"USD"))
        original = batch((position,))
        v2.validate_batch(original,RAW,context=CONTEXT)
        encoded = v2.canonical_json(original).encode()
        self.assertEqual(v2.decode_batch(encoded,RAW),original)
        self.assertEqual(original.records[0].cost_cad.amount,D("111.11"))
        zero = replace(POSITION,quantity=D(0),unit_price=None,cost_native=None,cost_cad=Money(D(0),"CAD"),unrealized=None)
        restored = v2.decode_batch(v2.canonical_json(batch((zero,))).encode(),RAW).records[0]
        self.assertIsNone(restored.unit_price)
        self.assertIsNone(restored.cost_native)
        self.assertEqual(restored.cost_cad.amount,D(0))

    def test_explicit_host_context_is_immutable_and_part_of_evidence(self):
        with self.assertRaises(FrozenInstanceError):
            CONTEXT.account_alias="changed"
        for context in (None,replace(CONTEXT,evidence_at=AT.replace(tzinfo=None)),replace(CONTEXT,source_timezone="Not/AZone"),
                        replace(CONTEXT,revisions=[]),replace(CONTEXT,revisions=(v2.RevisionContext(ACCOUNT,"holdings","p","s","r1"),)*2)):
            with self.subTest(context=context),self.assertRaises(ValueError):
                v2.validate_context(context)
        with self.assertRaises(ValueError):
            v2.validate_batch(batch(),RAW,context=replace(CONTEXT,account_alias="different"))
        with self.assertRaises(ValueError):
            v2.validate_batch(batch(context=replace(CONTEXT,format_selection="other")),RAW)

    def test_lifecycle_retains_all_order_values_and_delivery_network(self):
        event = replace(purchase(),legs=(CryptoLeg(ACCOUNT,CAD,D(-100)),CryptoLeg(ACCOUNT,LBTC,D("0.00100000"))))
        lifecycle = v2.Lifecycle(AT.replace(hour=16),AT,AT,"Buy Bitcoin","synthetic subtype","COMPLETED","COMPLETED","COMPLETED",
            v2.AssetAmount(CAD,D(100),"CAD Balance"),v2.AssetAmount(LBTC,D("0.00100000"),"Liquid Network"),
            v2.Rate(D("100000.000"),"CAD/BTC"),v2.Rate(D("99999.123"),"CAD/BTC"))
        event = replace(event,lifecycle=lifecycle,source_fields=(("source_note","Synthetic unmodified source field"),))
        value = batch((event,))
        self.assertEqual(v2.decode_batch(v2.canonical_json(value).encode(),RAW),value)
        for life in (replace(lifecycle,completed_at=None),replace(lifecycle,completed_at=AT.replace(hour=15)),
                     replace(lifecycle,payin=replace(lifecycle.payin,quantity=D(-1)))):
            with self.assertRaises(ValueError):
                v2.validate_batch(batch((replace(event,lifecycle=life),)),RAW)

    def test_cash_direction_links_fees_and_satoshi_validation(self):
        event = purchase(fees=())
        cash = v2.CashFlow(replace(KEY,source_id="purchase-cash"),AT,"transfer","out",Money(D(100),"CAD"),"completed","internal",
            "synthetic-link",cash_leg_of=v2.Reference(ACCOUNT,"crypto_transactions","purchase-001"))
        v2.validate_batch(batch((event,cash)),RAW)
        self.assertNotEqual(v2.canonical_json(batch((event,))),v2.canonical_json(batch((purchase(fees=None),))))
        bad = [replace(cash,direction="in",type="withdrawal"),replace(cash,cash_leg_of=replace(cash.cash_leg_of,kind="cash_flows")),
               replace(cash,boundary="external"),replace(cash,amount=Money(D(0),"CAD")),
               replace(event,fees=(v2.Fee(ACCOUNT,BTC,D("0.000000001"),False,False),)),
               replace(event,legs=(CryptoLeg(ACCOUNT,BTC,D("0.000000001")),)),
               replace(event,fees=(v2.Fee(ACCOUNT,CAD,D(1),1,False),))]
        for record in bad:
            with self.subTest(record=record),self.assertRaises(ValueError):
                v2.validate_batch(batch((record,)),RAW)

    def test_metadata_membership_scope_revisions_and_voids(self):
        corrected = replace(POSITION,key=replace(KEY,revision="r2",supersedes_revision="r1",change="correction"),revision_reason="Source correction")
        v2.validate_batch(batch((corrected,)),RAW)
        bad = [batch(records=(POSITION,POSITION)),replace(batch(),coverage=()),replace(batch(),accounts=(META,META)),
               replace(batch(),membership=replace(batch().membership,accounts=())),
               replace(batch(),snapshots=(replace(batch().snapshots[0],revision="wrong"),)),
               batch((replace(corrected,revision_reason=None),)),batch((replace(POSITION,quantity=1.25),)),
               batch((replace(POSITION,cost_cad=Money(D(1),"USD")),)),batch((replace(POSITION,as_of=AT.replace(tzinfo=None)),))]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):
                v2.validate_batch(value,RAW)
        void = replace(funding(),key=replace(funding().key,revision="r2",supersedes_revision="r1",change="void"),
            status="cancelled",revision_reason="Source void")
        v2.validate_batch(batch((void,)),RAW)
        with self.assertRaises(ValueError):
            v2.validate_batch(batch((replace(void,status="completed"),)),RAW)

    def test_strict_decoder_rejects_unknown_types_keys_nonfinite_and_noncanonical_json(self):
        original = v2.canonical_json(batch()).encode()
        values = [original+b" ",original.replace(b'"quantity":"1.25"',b'"quantity":1.25'),
                  original.replace(b'"quantity":"1.25"',b'"quantity":"NaN"'),
                  original.replace(b'"quantity":"1.25"',b'"quantity":"invalid"'),
                  original.replace(b'"api_version":2',b'"api_version":1'),
                  original.replace(b'"api_version":2',b'"api_version":2,"api_version":2'),
                  b'{"__class__":"untrusted.code"}',b'['*1500+b']'*1500]
        for raw in values:
            with self.subTest(raw=raw[:80]),self.assertRaises(ValueError):
                v2.decode_batch(raw,RAW)
        with self.assertRaises(ValueError):
            v2.decode_batch(original,b"changed source")

    def test_host_record_and_scope_parent_choices_cannot_be_ignored(self):
        corrected=replace(POSITION,key=replace(KEY,revision="r2",supersedes_revision="r1",change="correction"),revision_reason="Host-reviewed correction")
        context=replace(CONTEXT,revisions=(v2.RevisionContext(ACCOUNT,"holdings",KEY.source_id,POSITION.observation_id,"r1"),),
            scope_revisions=(v2.ScopeRevisionContext("snapshot",POSITION.observation_id,"r1"),
                v2.ScopeRevisionContext("coverage","records-holdings","r1",ACCOUNT,"holdings",POSITION.observation_id)))
        value=batch((corrected,),context=context)
        self.assertEqual(v2.decode_batch(v2.canonical_json(value).encode(),RAW),value)
        with self.assertRaises(ValueError):v2.validate_batch(batch(context=context),RAW)
        for bad in (replace(context,revisions=(replace(context.revisions[0],source_id="missing"),)),
                    replace(context,scope_revisions=(replace(context.scope_revisions[0],supersedes_revision="wrong"),))):
            with self.assertRaises(ValueError):v2.validate_batch(batch((corrected,),context=bad),RAW)

    def test_v2_sdk_and_registry_detection_are_separate_from_v1_source_plans(self):
        from wealth_ledger.source_registry import AdapterRegistration,ProviderInfo,build_registry
        from wealth_ledger.source_pipeline import DEFAULT_CONFIG,SourcePlanError,_plan
        class Adapter:
            info=INFO
            def detect(self,raw):return Detection(True,"synthetic-v2","Synthetic exact format")
            def normalize(self,raw,*,export_version,context):return batch(context=context)
        adapter=Adapter()
        self.assertEqual(check_contract_v2(adapter,RAW,context=CONTEXT).record_count,1)
        registry=build_registry(builtins=(AdapterRegistration(ProviderInfo("synthetic","Synthetic Provider"),adapter),))
        self.assertEqual(registry.detect(RAW).descriptor.info.api_version,2)
        with self.assertRaises(SourcePlanError) as caught:
            _plan((RAW,),DEFAULT_CONFIG,{},registry=registry,environment="a"*64)
        self.assertEqual(caught.exception.code,"protocol_v2_context_required")
