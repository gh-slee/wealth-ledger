"""Independent literal contract examples: fabricated accounts, listings and facts."""
from dataclasses import FrozenInstanceError, replace
from decimal import localcontext
import hashlib
import json
import unittest
from unittest.mock import patch

from wealth_ledger.domain import canonical_v1 as c
from wealth_ledger.domain import validation_v1 as v

TENANT = "10000000-0000-4000-8000-000000000001"
PORTFOLIO = "10000000-0000-4000-8000-000000000002"


def ref(kind, ordinal):
    return c.ScopedIdV1(TENANT, PORTFOLIO, kind, f"20000000-0000-4000-8000-{ordinal:012d}")


A, B, C1, C2 = ref("account", 1), ref("account", 2), ref("connection", 3), ref("connection", 4)
STOCK, US_STOCK, CASH, BTC, LBTC, ETF, ISSUER = (ref("instrument",5),ref("instrument",6),ref("instrument",7),ref("instrument",8),ref("instrument",9),ref("instrument",10),ref("issuer",11))
AT = c.InstantV1("2024-01-31T17:00:00-05:00", "America/Toronto", 0)
UTC_AT = c.InstantV1("2024-01-31T22:00:00Z", "UTC", 0)
DAY = c.DateOnlyV1("2024-01-31", None)
D = c.DecimalTokenV1


def security(id=STOCK, mic="XTSX", currency="CAD", ticker="DEMO"):
    return c.InstrumentV1(id,"SECURITY",currency,ticker,mic,None,None,None,ISSUER,(),"Fabricated listing","mapping-e1")


def crypto(id=BTC, symbol="BTC", network="bitcoin"):
    return c.InstrumentV1(id,"CRYPTO","CAD",None,None,symbol,network,network,None,(),"Fabricated crypto descriptor","mapping-e1")


def source(kind="holdings", source_id="position-a", observation="snapshot-1", revision="r1", *, connection=C1, account="tf"):
    return c.SourceSelectorV1(connection,"synthetic",account,kind,source_id,observation,revision)


def identity(ordinal=20, *, selector=None):
    return c.FactIdentityV1(ref("fact",ordinal),selector or source(),"original",None,None,"evidence-e1")


def coverage(account=A, kind="holdings", observation="snapshot-1", *, connection=C1, status="complete", at=AT, scope="scope-h", source_key="tf"):
    return c.CoverageV1(connection,source_key,account,kind,scope,"r1",None,c.PointV1(at),c.InstrumentScopeV1("all"),status,"Explicit fabricated declaration",observation)


def base():
    provenance = c.ProvenanceV1("a"*64,None,"synthetic","synthetic.domain","1.0","synthetic-v1","evidence-e1",AT,AT,None,None,None)
    accounts = (c.FinancialAccountV1(A,"TFSA","investment","Fabricated TFSA"),c.FinancialAccountV1(B,"RRSP","investment","Fabricated RRSP"))
    connections = (c.SourceConnectionV1(C1,"synthetic","FILE_IMPORT"),c.SourceConnectionV1(C2,"synthetic","PULL_API"))
    aliases = tuple(c.AccountAliasV1(conn,"synthetic",key,account,"m1","mapping-e1") for conn,key,account in ((C1,"tf",A),(C1,"rr",B),(C2,"rr-api",B)))
    instruments = (security(),security(US_STOCK,"XNAS","USD"),c.InstrumentV1(CASH,"CASH","CAD",None,None,None,None,None,None,(),"Fabricated CAD cash","mapping-e1"),crypto(),crypto(LBTC,"LBTC","liquid"),security(ETF,"XTSX","CAD","BTC"))
    return c.DomainBatchV1(1,c.DECIMAL_PROFILE,TENANT,PORTFOLIO,"m1","evidence-e1",provenance,accounts,connections,aliases,instruments,(c.IssuerV1(ISSUER,"Fabricated issuer"),),(),(),())


def position(quantity="10", ordinal=20, *, account=A, instrument=STOCK, selector=None, at=AT, support=None):
    return c.PositionItemV1(identity(ordinal,selector=selector),account,instrument,at,D(quantity),c.MoneyV1(D("125.00"),"CAD"),None,None,c.MoneyV1(D("0.00"),"CAD"),None,"Fabricated name","STOCK","Fabricated venue",support or c.SupportV1("supported_shape"))


def with_positions(items=None, *, at=AT, status="complete"):
    items = (position(),) if items is None else items
    cv = coverage(at=at,status=status)
    cvref = c.ExternalSourceRefV1(TENANT,PORTFOLIO,replace(source("coverage","scope-h","snapshot-1"),record_kind="holdings"))
    snapshot = c.PositionSnapshotV1(ref("snapshot",30),C1,"snapshot-1","r1",None,at,(A,),(cvref,),items)
    return replace(base(),coverage=(cv,),snapshots=(snapshot,))


def event(quantity="0.01000000", ordinal=40, *, source_id="purchase-x", status="completed"):
    ident = identity(ordinal,selector=source("crypto_transactions",source_id,""))
    legs = (c.ActivityLegV1(A,CASH,D("-700.00"),"PAYMENT"),c.ActivityLegV1(A,BTC,D(quantity),"ACQUISITION"))
    return c.ActivityEventV1(ident,AT,"BUY","purchase",status,status,legs,None,c.MoneyV1(D("0.00"),"CAD"),(),(),None,None,None,c.SupportV1("supported_shape"))


def with_events(*events):
    return replace(base(),coverage=(coverage(kind="crypto_transactions",observation="",scope="scope-c"),),activities=events or (event(),))


class DomainV1Tests(unittest.TestCase):
    def code(self, code, operation, *args):
        with self.assertRaises(v.DomainValidationError) as caught:
            operation(*args)
        self.assertEqual(caught.exception.diagnostic.code,code)
        self.assertLessEqual(len(str(caught.exception)),256)
        return caught.exception

    def test_closed_canonical_roundtrip_and_immutable_objects(self):
        value = with_positions()
        encoded = v.encode_domain_v1(value)
        self.assertEqual(v.decode_domain_v1(encoded),value)
        self.assertEqual(encoded,json.dumps(json.loads(encoded),ensure_ascii=False,sort_keys=True,separators=(",",":")).encode())
        with self.assertRaises(FrozenInstanceError): value.mapping_revision="changed"
        self.code("domain_version_unsupported",v.validate_domain_v1,replace(value,contract_version=2))
        self.code("domain_invalid_type",v.validate_domain_v1,replace(value,contract_version=True))
        self.code("domain_profile_unsupported",v.validate_domain_v1,replace(value,profile="other"))
        self.code("domain_invalid_type",v.validate_domain_v1,replace(value,accounts=list(value.accounts)))

    def test_strict_decoder_and_safe_fixed_paths(self):
        good=v.encode_domain_v1(with_positions())
        self.code("domain_duplicate_key",v.decode_domain_v1,good.replace(b'"contract_version":1',b'"contract_version":1,"contract_version":1'))
        data=json.loads(good); data["SENSITIVE_SENTINEL_account_9988"]=1
        error=self.code("domain_schema_unknown_field",v.decode_domain_v1,json.dumps(data).encode())
        self.assertNotIn("SENSITIVE_SENTINEL",str(error))
        data=json.loads(good); del data["accounts"]
        self.code("domain_schema_missing_field",v.decode_domain_v1,json.dumps(data).encode())
        for raw in (good+b" ",good.replace(b'"token":"10"',b'"token":10'),good.replace(b'"token":"10"',b'"token":10.0'),b'{"__class__":"untrusted.constructor"}',b'\xff',b'{"x":NaN}'):
            with self.subTest(raw=raw[:40]),self.assertRaises(v.DomainValidationError):v.decode_domain_v1(raw)
        # Independent dictionary insertion order does not select a different failure.
        d=json.loads(good); d["snapshots"][0]["items"][0]["quantity"]={"token":12}; d["accounts"][0]["role"]=False
        errors=[]
        for sort in (False,True):
            try:v.decode_domain_v1(json.dumps(d,sort_keys=sort).encode())
            except v.DomainValidationError as error:errors.append(error.diagnostic)
        self.assertEqual(errors[0],errors[1])

    def test_many_aliases_connection_namespaces_and_typed_scope(self):
        value=base(); v.validate_domain_v1(value)
        self.assertEqual((len(value.accounts),len(value.aliases),len(value.connections)),(2,3,2))
        another=c.AccountAliasV1(C2,"synthetic","tf",B,"m1","mapping-e2")
        value=replace(value,aliases=value.aliases+(another,))
        v.validate_domain_v1(value)
        self.code("domain_duplicate_key",v.validate_domain_v1,replace(value,aliases=value.aliases+(another,)))
        self.code("domain_alias_conflict",v.validate_domain_v1,replace(value,aliases=value.aliases+(replace(another,account=A),)))
        bad=replace(value.aliases[0],account=STOCK)
        self.code("domain_reference_out_of_scope",v.validate_domain_v1,replace(value,aliases=(bad,)+value.aliases[1:]))
        bad=replace(A,portfolio_id="10000000-0000-4000-8000-000000000099")
        self.code("domain_reference_out_of_scope",v.validate_domain_v1,replace(value,accounts=(replace(value.accounts[0],id=bad),value.accounts[1])))
        # One text key belongs to distinct accounts under distinct connections.
        row=position(selector=source(connection=C2),account=B)
        cv=replace(coverage(account=B,connection=C2,source_key="tf"),connection=C2)
        cvref=c.ExternalSourceRefV1(TENANT,PORTFOLIO,replace(source("coverage","scope-h",connection=C2),record_kind="holdings"))
        snap=c.PositionSnapshotV1(ref("snapshot",30),C2,"snapshot-1","r1",None,AT,(B,),(cvref,),(row,))
        v.validate_domain_v1(replace(value,coverage=(cv,),snapshots=(snap,)))
        self.code("domain_reference_out_of_scope",v.validate_domain_v1,replace(value,coverage=(cv,),snapshots=(replace(snap,items=(replace(row,account=A),)),)))

    def test_listing_issuer_cash_crypto_and_etf_do_not_merge(self):
        value=base(); v.validate_domain_v1(value)
        self.assertEqual(value.instruments[0].issuer,value.instruments[1].issuer)
        self.assertNotEqual(value.instruments[0].id,value.instruments[1].id)
        self.assertEqual(len(set(i.id for i in value.instruments)),6)
        self.code("domain_instrument_identity_ambiguous",v.validate_domain_v1,replace(value,instruments=(replace(value.instruments[0],mic=None),)+value.instruments[1:]))
        # An ETF ticker BTC is not subject to crypto integrality.
        v.validate_domain_v1(with_positions((position("0.000000001",instrument=ETF),)))

    def test_decimal_literal_boundaries_without_ambient_rounding(self):
        accepted=("12345678901234.123456789012345678901234","0.000000000000000000000001","10000000000000000000000000000000000000","-0.00000","1.2300000000000000000000000000000000000000000","0."+"0"*254)
        rejected=("123456789012345.123456789012345678901234","0.0000000000000000000000001","100000000000000000000000000000000000000")
        for precision in (6,100):
            with localcontext() as context:
                context.prec=precision
                for token in accepted:
                    with self.subTest(token=token,precision=precision):
                        v.decimal_parts_v1(D(token))
                        value=with_positions((position(token),))
                        self.assertEqual(v.decode_domain_v1(v.encode_domain_v1(value)).snapshots[0].items[0].quantity.token,token)
                for token in rejected:self.code("domain_decimal_envelope",v.decimal_parts_v1,D(token))
        for token in ("+1"," 1","1 ","01","1.",".1","1e2","1E+1000","0E-999999","--1","١"):
            self.code("domain_decimal_invalid",v.decimal_parts_v1,D(token))
        for token in ("NaN","sNaN","Infinity","-Infinity"):self.code("domain_decimal_nonfinite",v.decimal_parts_v1,D(token))
        for token in (True,1,1.5):self.code("domain_invalid_type",v.decimal_parts_v1,D(token))
        self.code("domain_decimal_token_limit",v.decimal_parts_v1,D("0."+"0"*255))

    def test_satoshi_signs_roles_fees_and_unsupported_escape(self):
        for token in ("0.00000001","0.0000000100"):
            v.validate_domain_v1(with_events(event(token)))
        for token in ("0.000000001","-0.000000001"):
            self.code("domain_subsatoshi",v.validate_domain_v1,with_events(event(token)))
        for token in ("0","-0.0000","-0.01000000"):
            self.code("domain_unsupported_semantics",v.validate_domain_v1,with_events(event(token)))
        good=event(); payment=c.ActivityLegV1(A,BTC,D("-0.01"),"PAYMENT"); acquired=c.ActivityLegV1(A,STOCK,D("2"),"ACQUISITION")
        v.validate_domain_v1(with_events(replace(good,legs=(payment,acquired))))
        self.code("domain_unsupported_semantics",v.validate_domain_v1,with_events(replace(good,legs=(replace(payment,role="OTHER"),))))
        self.code("domain_unsupported_semantics",v.validate_domain_v1,with_events(replace(event("-0.01"),kind="UNSUPPORTED",support=c.SupportV1("unsupported",("unsupported_activity",)))))
        fee=c.FeeV1(A,BTC,D("0.00000001"),True,False)
        v.validate_domain_v1(with_events(replace(good,fees=(fee,))))
        self.code("domain_unsupported_semantics",v.validate_domain_v1,with_events(replace(good,fees=(replace(fee,quantity=D("-0.00000001")),))))
        self.code("domain_subsatoshi",v.validate_domain_v1,with_events(replace(good,fees=(replace(fee,quantity=D("-0.000000001")),))))
        v.validate_domain_v1(with_events(replace(good,legs=good.legs+(c.ActivityLegV1(A,BTC,D("-0.00000001"),"FEE"),))))

    def test_time_tokens_precision_date_only_and_legacy_provenance(self):
        for at in (AT,UTC_AT,DAY,c.DateOnlyV1("2024-01-31","Unverified/Zone"),c.InstantV1("2024-01-31T22:00:00.1234+00:00",None,4)):
            value=with_positions((position(at=at),),at=at)
            self.assertEqual(v.decode_domain_v1(v.encode_domain_v1(value)),value)
        self.assertNotEqual(v.encode_domain_v1(with_positions()),v.encode_domain_v1(with_positions((position(at=UTC_AT),),at=UTC_AT)))
        cases=(("2024-02-30T22:00:00Z",0,"domain_time_invalid"),("2024-01-31T22:00:60Z",0,"domain_time_invalid"),("2024-01-31T22:00:00",0,"domain_time_invalid"),("2024-01-31T22:00:00-00:00",0,"domain_time_invalid"),("2024-01-31T22:00:00.1234567Z",7,"domain_time_precision_unsupported"),("2024-01-31T22:00:00.1Z",0,"domain_time_precision_unsupported"))
        for token,scale,code in cases:self.code(code,v.validate_domain_v1,replace(base(),provenance=replace(base().provenance,evidence_at=c.InstantV1(token,None,scale))))
        for zone in ("../private","Area//City","Area/..","Area/City name","a"*256):
            self.code("domain_time_invalid",v.validate_domain_v1,replace(base(),provenance=replace(base().provenance,evidence_at=replace(AT,zone=zone))))
        digest="b"*64; archive=c.LegacyRecordRefV1(digest,"evidence",None,"effective_at")
        legacy=c.LegacyDateTimeV1("2024-01-31T22:00:00+00:00",archive)
        value=replace(base(),provenance=replace(base().provenance,canonical_sha256=digest,source_effective_at=legacy))
        v.validate_domain_v1(value)
        for token in ("2024-01-31T22:00:00.1234567+00:00","2024-01-31T22:00:00Z","2024-01-31T22:00:00"):
            self.code("domain_time_invalid",v.validate_domain_v1,replace(value,provenance=replace(value.provenance,source_effective_at=replace(legacy,token=token))))
        self.code("domain_time_invalid",v.validate_domain_v1,replace(value,provenance=replace(value.provenance,source_effective_at=replace(legacy,archive=replace(archive,field="")))))

    def test_complete_empty_partial_unknown_and_scoped_snapshot_references(self):
        for status in ("complete","partial","unknown"):
            value=with_positions((),status=status)
            self.assertEqual(v.decode_domain_v1(v.encode_domain_v1(value)).coverage[0].status,status)
        value=with_positions()
        self.code("domain_coverage_mismatch",v.validate_domain_v1,replace(value,coverage=(replace(value.coverage[0],time=c.PointV1(DAY)),)))
        self.code("domain_coverage_mismatch",v.validate_domain_v1,replace(value,coverage=(replace(value.coverage[0],instrument_scope=c.InstrumentScopeV1("instruments",(BTC,))),)))
        self.code("domain_coverage_mismatch",v.validate_domain_v1,replace(value,snapshots=(replace(value.snapshots[0],accounts=(B,)),)))
        bad=replace(value.snapshots[0].coverage[0],selector=replace(value.snapshots[0].coverage[0].selector,revision="r2"))
        self.code("domain_coverage_mismatch",v.validate_domain_v1,replace(value,snapshots=(replace(value.snapshots[0],coverage=(bad,)),)))

    def test_two_dated_snapshots_and_buy_stay_separate_literal_facts(self):
        later=c.InstantV1("2024-02-29T22:00:00Z","UTC",0)
        first_a=position("10",selector=source(observation="t1"))
        first_b=position("5",ordinal=21,account=B,selector=source(source_id="position-b",observation="t1",account="rr"))
        later_a=position("7",ordinal=22,selector=source(observation="t2"),at=later)
        cv_a=coverage(observation="t1")
        cv_b=coverage(B,observation="t1",source_key="rr")
        cv_later=coverage(observation="t2",status="partial",at=later)
        def cvref(account,observation):
            return c.ExternalSourceRefV1(TENANT,PORTFOLIO,replace(source("coverage","scope-h",observation,account=account),record_kind="holdings"))
        first=c.PositionSnapshotV1(ref("snapshot",30),C1,"t1","r1",None,AT,(A,B),(cvref("tf","t1"),cvref("rr","t1")),(first_a,first_b))
        second=c.PositionSnapshotV1(ref("snapshot",31),C1,"t2","r1",None,later,(A,),(cvref("tf","t2"),),(later_a,))
        buy=replace(event(),legs=(c.ActivityLegV1(A,STOCK,D("2"),"ACQUISITION"),))
        value=replace(base(),coverage=(cv_a,cv_b,cv_later,coverage(kind="crypto_transactions",observation="",scope="scope-c")),snapshots=(first,second),activities=(buy,))
        restored=v.decode_domain_v1(v.encode_domain_v1(value))
        self.assertEqual([[p.quantity.token for p in snapshot.items] for snapshot in restored.snapshots],[["10","5"],["7"]])
        self.assertEqual([cv.status for cv in restored.coverage],["complete","complete","partial","complete"])
        self.assertEqual(restored.activities[0].legs[0].quantity.token,"2")
        self.assertFalse(hasattr(restored,"resulting_balance"))

    def test_source_alias_coverage_is_not_collapsed_within_one_connection(self):
        value=with_positions((position("1.2500"),))
        alias=c.AccountAliasV1(C1,"synthetic","tf-alias",A,"m1","mapping-e2")
        second=position("7.00",ordinal=21,selector=source(source_id="position-alias",account="tf-alias"))
        other_cv=replace(value.coverage[0],source_account_key="tf-alias")
        other_ref=replace(value.snapshots[0].coverage[0],selector=replace(value.snapshots[0].coverage[0].selector,source_account_key="tf-alias"))
        snapshot=replace(value.snapshots[0],items=value.snapshots[0].items+(second,),coverage=value.snapshots[0].coverage+(other_ref,))
        value=replace(value,aliases=value.aliases+(alias,),coverage=value.coverage+(other_cv,),snapshots=(snapshot,))
        restored=v.decode_domain_v1(v.encode_domain_v1(value))
        self.assertEqual(restored.snapshots[0].accounts,(A,))
        self.assertEqual([cv.source_account_key for cv in restored.coverage],["tf","tf-alias"])
        self.assertEqual([item.quantity.token for item in restored.snapshots[0].items],["1.2500","7.00"])
        self.assertEqual([item.identity.source.source_account_key for item in restored.snapshots[0].items],["tf","tf-alias"])
        self.assertFalse(hasattr(restored,"resulting_balance"))
        # Both aliases explicitly map A, but tf coverage cannot certify tf-alias.
        self.code("domain_coverage_mismatch",v.validate_domain_v1,replace(value,snapshots=(replace(snapshot,coverage=snapshot.coverage[:1]),)))
        self.code("domain_reference_out_of_scope",v.validate_domain_v1,replace(value,coverage=(value.coverage[0],replace(other_cv,source_account_key="rr"))))
        self.code("domain_mapping_required",v.validate_domain_v1,replace(value,coverage=(value.coverage[0],replace(other_cv,source_account_key="unmapped-alias"))))
        activity=replace(event(),identity=replace(event().identity,source=replace(event().identity.source,source_account_key="tf-alias")))
        activities=replace(with_events(activity),aliases=value.aliases)
        self.code("domain_coverage_mismatch",v.validate_domain_v1,activities)

    def test_snapshot_items_use_only_explicitly_selected_source_scopes(self):
        value=with_positions()
        stock=replace(value.coverage[0],scope_id="scope-stock",instrument_scope=c.InstrumentScopeV1("instruments",(STOCK,)))
        btc=replace(value.coverage[0],scope_id="scope-btc",instrument_scope=c.InstrumentScopeV1("instruments",(BTC,)))
        stock_ref=replace(value.snapshots[0].coverage[0],selector=replace(value.snapshots[0].coverage[0].selector,source_id="scope-stock"))
        btc_ref=replace(stock_ref,selector=replace(stock_ref.selector,source_id="scope-btc"))
        snapshot=replace(value.snapshots[0],coverage=(btc_ref,))
        value=replace(value,coverage=(stock,btc),snapshots=(snapshot,))
        self.code("domain_coverage_mismatch",v.validate_domain_v1,value)
        selected=replace(value,snapshots=(replace(snapshot,coverage=(btc_ref,stock_ref)),))
        self.assertEqual(v.decode_domain_v1(v.encode_domain_v1(selected)),selected)
        self.code("domain_coverage_mismatch",v.validate_domain_v1,replace(value,coverage=(btc,stock)))

    def test_snapshot_source_identity_duplicates_are_independent_of_uuid(self):
        value=with_positions(())
        duplicate=replace(value.snapshots[0],id=ref("snapshot",31))
        self.code("domain_duplicate_key",v.validate_domain_v1,replace(value,snapshots=value.snapshots+(duplicate,)))
        # Different revisions and connections remain distinct; no head selection.
        historical=replace(duplicate,revision="r2")
        v.validate_domain_v1(replace(value,snapshots=value.snapshots+(historical,)))
        connection_alias=c.AccountAliasV1(C2,"synthetic","tf",A,"m1","mapping-e2")
        other_cv=replace(value.coverage[0],connection=C2)
        other_ref=replace(duplicate.coverage[0],selector=replace(duplicate.coverage[0].selector,connection=C2))
        other=replace(duplicate,connection=C2,coverage=(other_ref,))
        v.validate_domain_v1(replace(value,aliases=value.aliases+(connection_alias,),coverage=value.coverage+(other_cv,),snapshots=value.snapshots+(other,)))

    def test_unsupported_fee_instrument_requires_truthful_activity_support(self):
        fee_instrument=replace(security(ref("instrument",99),ticker="FEE-UNIT"),kind="UNSUPPORTED")
        fee=c.FeeV1(A,fee_instrument.id,D("1.2500"),True,False)
        value=with_events(replace(event(),fees=(fee,)))
        value=replace(value,instruments=value.instruments+(fee_instrument,))
        self.code("domain_unsupported_semantics",v.validate_domain_v1,value)
        explicit=replace(value.activities[0],support=c.SupportV1("unsupported",("unsupported_instrument",)))
        value=replace(value,activities=(explicit,))
        restored=v.decode_domain_v1(v.encode_domain_v1(value))
        self.assertEqual(restored.activities[0].support,c.SupportV1("unsupported",("unsupported_instrument",)))
        self.assertEqual(restored.activities[0].fees,(fee,))
        negative=replace(explicit,legs=(explicit.legs[0],replace(explicit.legs[1],quantity=D("-0.01"))))
        self.code("domain_unsupported_semantics",v.validate_domain_v1,replace(value,activities=(negative,)))

    def test_older_unreleased_coverage_shape_fails_closed(self):
        value=json.loads(v.encode_domain_v1(with_positions()))
        del value["coverage"][0]["source_account_key"]
        prototype=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
        error=self.code("domain_schema_missing_field",v.decode_domain_v1,prototype)
        self.assertEqual(error.diagnostic.field,"$.coverage[0].source_account_key")

    def test_distinct_equal_events_and_external_historical_correction(self):
        value=with_events(event(),event(ordinal=41,source_id="purchase-y"))
        v.validate_domain_v1(value)
        self.assertEqual([e.identity.source.source_id for e in value.activities],["purchase-x","purchase-y"])
        self.assertEqual(v.encode_domain_v1(value),v.encode_domain_v1(value))
        original=value.activities[0]
        parent=c.ExternalSourceRefV1(TENANT,PORTFOLIO,original.identity.source)
        corrected=replace(original,identity=replace(original.identity,source=replace(original.identity.source,revision="r2"),change="correction",parent=parent,reason="Fabricated source correction"))
        v.validate_domain_v1(with_events(corrected))
        for selector in (replace(parent.selector,revision="r2"),replace(parent.selector,kind="cash_flows")):
            self.code("domain_revision_invalid",v.validate_domain_v1,with_events(replace(corrected,identity=replace(corrected.identity,parent=replace(parent,selector=selector)))))
        self.code("domain_reference_out_of_scope",v.validate_domain_v1,with_events(replace(corrected,identity=replace(corrected.identity,parent=replace(parent,portfolio_id="10000000-0000-4000-8000-000000000099")))))

    def test_unsupported_signed_positions_pending_cancelled_and_nulls(self):
        signed=position("-2.5",support=c.SupportV1("unsupported",("signed_position",)))
        self.assertEqual(v.decode_domain_v1(v.encode_domain_v1(with_positions((signed,)))).snapshots[0].items[0].quantity.token,"-2.5")
        self.code("domain_unsupported_semantics",v.validate_domain_v1,with_positions((replace(signed,support=c.SupportV1("supported_shape")),)))
        for status in ("pending","cancelled"):v.validate_domain_v1(with_events(event(status=status)))
        unknown=replace(event(),source_status="UNSUPPORTED_SOURCE",status="unsupported",support=c.SupportV1("unsupported",("unsupported_status",)))
        v.validate_domain_v1(with_events(unknown))
        self.code("domain_unsupported_semantics",v.validate_domain_v1,with_events(replace(unknown,status="completed")))
        self.assertNotEqual(v.encode_domain_v1(with_events(replace(event(),fees=None))),v.encode_domain_v1(with_events(replace(event(),fees=()))))
        self.assertNotEqual(v.encode_domain_v1(with_events(replace(event(),acquisition_cost_cad=None))),v.encode_domain_v1(with_events(event())))

    def test_cash_observation_and_movements_do_not_create_balances(self):
        row=position("125.00",instrument=CASH)
        value=with_positions((row,))
        ident=identity(50,selector=source("cash_flows","funding-1",""))
        cash=c.SourceCashFlowV1(c.MoneyV1(D("1000.00"),"CAD"),"in","external",None,None,None)
        funding=c.ActivityEventV1(ident,AT,"FUNDING","deposit","completed","completed",(),None,None,None,(),None,None,cash,c.SupportV1("supported_shape"))
        value=replace(value,coverage=value.coverage+(coverage(kind="cash_flows",observation="",scope="cash-scope"),),activities=(funding,))
        restored=v.decode_domain_v1(v.encode_domain_v1(value))
        self.assertEqual(restored.snapshots[0].items[0].quantity.token,"125.00")
        self.assertEqual(restored.activities[0].cash_flow.cash_amount.amount.token,"1000.00")
        self.assertFalse(hasattr(restored,"balance"))
        self.code("domain_unsupported_semantics",v.validate_domain_v1,replace(value,activities=(replace(funding,cash_flow=None),)))
        self.code("domain_unsupported_semantics",v.validate_domain_v1,replace(value,activities=(replace(funding,source_kind="Deposit",cash_flow=replace(cash,direction="out")),)))

    def test_admission_limits_exact_and_one_over(self):
        value=base(); v.validate_domain_v1(replace(value,evidence_reference="x"*4096))
        self.code("domain_resource_limit",v.validate_domain_v1,replace(value,evidence_reference="x"*4097))
        # Shared constant testing isolates each exact boundary without allocating
        # huge financial graphs; real byte-limit overflow is exercised separately.
        wire=v.encode_domain_v1(value)
        with patch.object(c,"MAX_CANONICAL_BYTES",len(wire)):
            self.assertEqual(v.encode_domain_v1(value),wire)
            self.assertEqual(v.decode_domain_v1(wire),value)
        with patch.object(c,"MAX_CANONICAL_BYTES",len(wire)-1):
            self.code("domain_resource_limit",v.encode_domain_v1,value)
            self.code("domain_resource_limit",v.decode_domain_v1,wire)
        self.code("domain_resource_limit",v.decode_domain_v1,b" "*(4*1024*1024+1))
        with patch.object(c,"MAX_COLLECTION",6):v.validate_domain_v1(value)
        with patch.object(c,"MAX_COLLECTION",5):self.code("domain_resource_limit",v.validate_domain_v1,value)
        self.code("domain_resource_limit",v.decode_domain_v1,b"["*33+b"]"*33)
        # No source ID, amount, free-form unknown key or malicious path is echoed.
        error=v.DomainValidationError("domain_invalid_type","/private/SENSITIVE_SENTINEL")
        self.assertEqual(error.diagnostic.field,"$")

    def test_admission_precedence_scope_completeness_and_no_legacy_reference_escape(self):
        value=with_positions()
        self.code("domain_resource_limit",v.validate_domain_v1,replace(value,contract_version=True,evidence_reference="x"*4097))
        self.code("domain_coverage_mismatch",v.validate_domain_v1,replace(value,snapshots=(replace(value.snapshots[0],coverage=()),)))
        unsupported=replace(base().instruments[3],kind="UNSUPPORTED")
        item=position("0.000000001",instrument=BTC,support=c.SupportV1("unsupported",("unsupported_instrument",)))
        graph=with_positions((item,))
        graph=replace(graph,instruments=graph.instruments[:3]+(unsupported,)+graph.instruments[4:])
        self.code("domain_subsatoshi",v.validate_domain_v1,graph)
        graph=replace(graph,instruments=graph.instruments[:3]+(replace(unsupported,symbol="btc"),)+graph.instruments[4:])
        self.code("domain_subsatoshi",v.validate_domain_v1,graph)
        target=c.ExternalSourceRefV1(TENANT,PORTFOLIO,source("crypto_transactions","historical-link","",None))
        self.code("domain_revision_invalid",v.validate_domain_v1,with_events(replace(event(),economic_references=(target,))))
        selector=replace(target.selector,revision="r0")
        v.validate_domain_v1(with_events(replace(event(),economic_references=(replace(target,selector=selector),))))

    def test_real_collection_depth_and_four_mib_boundaries(self):
        value=base()
        hints=tuple(c.IdentifierHintV1("synthetic",str(i)) for i in range(50_000))
        large=replace(value,instruments=(replace(value.instruments[0],identifiers=hints),)+value.instruments[1:])
        v.validate_domain_v1(large)
        self.code("domain_resource_limit",v.validate_domain_v1,replace(large,instruments=(replace(large.instruments[0],identifiers=hints+(c.IdentifierHintV1("synthetic","50000"),)),)+large.instruments[1:]))
        # Actual 4 MiB boundary, using ASCII hint text so each added x is one
        # independently known byte. No amount is generated by the codec.
        hints=tuple(c.IdentifierHintV1("synthetic","") for _ in range(1024))
        large=replace(value,instruments=(replace(value.instruments[0],identifiers=hints),)+value.instruments[1:])
        remaining=4*1024*1024-len(v.encode_domain_v1(large))
        expanded=[]
        for hint in hints:
            count=min(4096,remaining); remaining-=count
            expanded.append(replace(hint,value="x"*count))
        self.assertEqual(remaining,0)
        large=replace(large,instruments=(replace(large.instruments[0],identifiers=tuple(expanded)),)+large.instruments[1:])
        wire=v.encode_domain_v1(large)
        self.assertEqual(len(wire),4*1024*1024)
        self.assertEqual(v.decode_domain_v1(wire),large)
        self.code("domain_resource_limit",v.encode_domain_v1,replace(large,evidence_reference=large.evidence_reference+"x"))
        self.code("domain_resource_limit",v.decode_domain_v1,wire+b" ")
        v._json_depth(b"["*32+b"]"*32)
        self.code("domain_resource_limit",v._json_depth,b"["*33+b"]"*33)

    def test_known_literal_empty_wire_and_unknown_kind_cannot_promote(self):
        provenance=c.ProvenanceV1("a"*64,None,"synthetic","synthetic.domain","1.0","synthetic-v1","e1",None,None,None,None,None)
        value=c.DomainBatchV1(1,"decimal-38s-24f-38i-v1",TENANT,PORTFOLIO,"m1","e1",provenance,(),(),(),(),(),(),(),())
        expected=(b'{"accounts":[],"activities":[],"aliases":[],"connections":[],"contract_version":1,"coverage":[],"evidence_reference":"e1","instruments":[],"issuers":[],"mapping_revision":"m1","portfolio_id":"10000000-0000-4000-8000-000000000002","profile":"decimal-38s-24f-38i-v1","provenance":{"accepted_at":null,"adapter":"synthetic.domain","adapter_version":"1.0","canonical_sha256":null,"evidence_at":null,"evidence_reference":"e1","export_version":"synthetic-v1","imported_at":null,"legacy":null,"provider":"synthetic","raw_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","source_effective_at":null},"snapshots":[],"tenant_id":"10000000-0000-4000-8000-000000000001"}')
        self.assertEqual(v.encode_domain_v1(value),expected)
        self.assertEqual(v.decode_domain_v1(expected),value)
        strange=replace(event(),source_kind="unrecognized_source_action")
        self.code("domain_unsupported_semantics",v.validate_domain_v1,with_events(strange))
        unsupported=replace(strange,kind="UNSUPPORTED",support=c.SupportV1("unsupported",("unsupported_activity",)))
        v.validate_domain_v1(with_events(unsupported))

    def test_pure_calls_do_not_touch_application_io_or_clocks(self):
        import builtins
        import pathlib
        import socket
        import sqlite3
        import subprocess
        import uuid
        value=with_events(); wire=v.encode_domain_v1(value)
        with patch.object(builtins,"open",side_effect=AssertionError("file I/O")),patch.object(pathlib.Path,"open",side_effect=AssertionError("path I/O")),patch.object(socket,"socket",side_effect=AssertionError("network")),patch.object(sqlite3,"connect",side_effect=AssertionError("database")),patch.object(subprocess,"Popen",side_effect=AssertionError("process")),patch.object(uuid,"uuid4",side_effect=AssertionError("random UUID")):
            v.validate_domain_v1(value)
            self.assertEqual(v.decode_domain_v1(wire),value)
            self.assertEqual(v.encode_domain_v1(value),wire)


if __name__ == "__main__":unittest.main()
