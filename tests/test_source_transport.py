"""Complete decoded candidates and independently specified reference/error cases."""
from dataclasses import replace
import base64
import copy
import hashlib
import json
import unittest

from wealth_ledger.data_sources import contract_v1 as s
from wealth_ledger.data_sources.transport_v1 import make_envelope, validate_transport
from wealth_ledger.domain import canonical_v1 as c
from wealth_ledger.domain import legacy_bridge_v1 as b
from wealth_ledger.domain.validation_v1 import encode_domain_v1, decode_domain_v1
from test_source_capabilities import context_vector
from test_domain_v1 import with_events, event, C1

RAW = b"synthetic direct source evidence"


def direct_case():
    batch = with_events()
    batch = replace(batch,connections=tuple(x for x in batch.connections if x.id==C1),
                    aliases=tuple(x for x in batch.aliases if x.connection==C1),
                    provenance=replace(batch.provenance,raw_sha256=hashlib.sha256(RAW).hexdigest()))
    # Expected graph is authored from fixed existing test declarations, without the
    # new production reference projection or comparison functions as an oracle.
    activity = batch.activities[0]
    graph = s.ReferenceGraphV1(
        tuple(s.CoverageReference(x.connection,x.source_account_key,x.account,x.kind,x.scope_id,x.revision,x.parent,x.instrument_scope,x.observation_id) for x in batch.coverage),(),
        (s.ActivityReference(s.IdentityReference(activity.identity.id,activity.identity.source,"original",None),
            tuple(s.LegReference(x.account,x.instrument,x.role) for x in activity.legs),(),(),None,None),))
    allowed = s.DomainAllowed(batch.tenant_id,batch.portfolio_id,batch.connections[0],batch.accounts,batch.aliases,batch.instruments,batch.issuers,
        (b.FactMappingV1(activity.identity.source,activity.identity.id),),(),
        tuple(b.LegRoleAssignmentV1(activity.identity.source,i,leg.role) for i,leg in enumerate(activity.legs)),
        batch.mapping_revision,batch.evidence_reference,None,None,graph)
    descriptor = s.Descriptor(1,"synthetic","synthetic","synthetic.domain","synthetic-source","1.0","synthetic.domain","synthetic_source:factory",
        "a"*64,"b"*64,1,1,None,"domain_v1",("FILE_IMPORT",),("synthetic-v1",),("CASH","CRYPTO","SECURITY"),"forbidden","reviewed-file-v1")
    context = s.SourceContextV1(1,s.InternalRealm("synthetic_db","101",None,None,"44444444-4444-4444-8444-444444444444","0"),
        batch.tenant_id,batch.portfolio_id,batch.connections[0],s.digest(s.primitive(batch.connections[0])),"0","1","1",descriptor,
        s.installation_id(descriptor),"FILE_IMPORT","synthetic-v1",batch.mapping_revision,batch.evidence_reference,None,
        s.DomainBinding("domain_allowed_v1",allowed),batch.provenance)
    # This is a real accepted complete candidate, including coverage, not just a
    # syntax/hash vector. Structural validation occurs before transport tests.
    payload = encode_domain_v1(batch)
    return batch,context,payload


class SourceTransportTests(unittest.TestCase):
    def outcome(self, context, payload, *, raw=RAW, edits=None):
        env = json.loads(make_envelope(payload,context))
        if edits:
            env.update(edits)
        return validate_transport(raw,s.context_bytes(context),s.canonical(env))

    def test_complete_domain_candidate_traverses_decode_and_reference_stages(self):
        batch,context,payload = direct_case()
        result = self.outcome(context,payload)
        self.assertEqual((result.status,result.diagnostics,result.ingestible),("VALID_SHAPE",(),False))
        self.assertEqual(decode_domain_v1(base64.b64decode(result.candidate_domain_base64)),batch)
        self.assertEqual(batch.activities[0].legs[1].quantity.token,"0.01000000")
        self.assertEqual(batch.activities[0].acquisition_cost_cad.amount.token,"0.00")

    def test_same_scope_parent_revision_substitution_after_valid_decode_is_blocked(self):
        batch,context,payload = direct_case();activity=batch.activities[0]
        source=replace(activity.identity.source,revision="r2")
        parent=c.ExternalSourceRefV1(batch.tenant_id,batch.portfolio_id,replace(source,revision="r1"))
        identity=replace(activity.identity,source=source,change="correction",parent=parent,reason="Synthetic correction")
        activity=replace(activity,identity=identity);batch=replace(batch,activities=(activity,));payload=encode_domain_v1(batch)
        allowed=context.binding_context.value;oldgraph=allowed.reference_graph
        graph=replace(oldgraph,activities=(replace(oldgraph.activities[0],identity=s.IdentityReference(identity.id,source,"correction",parent)),))
        allowed=replace(allowed,reference_graph=graph,facts=(b.FactMappingV1(source,identity.id),),leg_roles=tuple(replace(x,source=source) for x in allowed.leg_roles))
        context=replace(context,binding_context=s.DomainBinding("domain_allowed_v1",allowed))
        self.assertEqual(self.outcome(context,payload).status,"VALID_SHAPE")
        badparent=replace(parent,selector=replace(parent.selector,revision="r9"))
        bad=replace(batch,activities=(replace(activity,identity=replace(identity,parent=badparent)),))
        badpayload=encode_domain_v1(bad)  # Prove stage9 admits this same-scope variation.
        result=self.outcome(context,badpayload)
        self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].field),("source_reference_mismatch","$.envelope.payload_base64"))
        self.assertIsNone(result.candidate_domain_base64)

    def test_unapproved_economic_reference_with_valid_domain_schema_is_blocked(self):
        batch,context,payload=direct_case();activity=batch.activities[0]
        reference=c.ExternalSourceRefV1(batch.tenant_id,batch.portfolio_id,replace(activity.identity.source,source_id="separate-funding",revision="r1"))
        bad=replace(batch,activities=(replace(activity,economic_references=(reference,)),))
        result=self.outcome(context,encode_domain_v1(bad))
        self.assertEqual(result.diagnostics[0].code,"source_reference_mismatch")

    def test_hash_precedes_all_payload_syntax_decoding_in_both_branches(self):
        _,domain_context,_=direct_case()
        parser_context=s.decode_context(context_vector()["canonical_utf8"].encode())
        for context in (domain_context,parser_context):
            with self.subTest(kind=context.installation_descriptor.payload_kind):
                result=self.outcome(context,b"\xff",edits={"payload_sha256":"0"*64})
                self.assertEqual((result.diagnostics[0].namespace,result.diagnostics[0].code,result.diagnostics[0].field),("source_v1","source_payload_digest_mismatch","$.envelope.payload_sha256"))
                result=self.outcome(context,b"\xff")
                self.assertEqual(result.diagnostics[0].code,"domain_invalid_type" if context.parse_context is None else "source_payload_invalid")

    def test_schema_then_context_then_versions_and_fingerprint_before_base64(self):
        _,context,payload=direct_case();env=json.loads(make_envelope(payload,context))
        badcontext=s.canonical({"unexpected":True})
        edited=env | {"envelope_version":True}
        result=validate_transport(RAW,badcontext,s.canonical(edited));self.assertEqual(result.diagnostics[0].code,"source_transport_invalid")
        edited=env | {"envelope_version":2}
        result=validate_transport(RAW,badcontext,s.canonical(edited));self.assertEqual(result.diagnostics[0].code,"source_context_invalid")
        result=validate_transport(RAW,s.context_bytes(context),s.canonical(edited));self.assertEqual(result.diagnostics[0].code,"source_version_unsupported")
        edited=copy.deepcopy(env);edited["fingerprint"]["availability_generation"]="3";edited["payload_base64"]="not base64"
        result=validate_transport(RAW,s.context_bytes(context),s.canonical(edited));self.assertEqual(result.diagnostics[0].field,"$.envelope.fingerprint.availability_generation")

    def test_base64_empty_and_size_boundaries_never_round_or_accept(self):
        _,context,payload=direct_case()
        for encoded in ("", "Zh==", "/w", "***", "é"):
            self.assertEqual(self.outcome(context,payload,edits={"payload_base64":encoded}).diagnostics[0].code,"source_payload_invalid")
        oversized=base64.b64encode(b"x"*(s.MAX_PAYLOAD+1)).decode()
        self.assertEqual(len(oversized),5592408)
        self.assertEqual(self.outcome(context,payload,edits={"payload_base64":oversized}).diagnostics[0].code,"source_transport_limit")

    def test_raw_and_context_limits_have_priority_over_envelope_faults(self):
        self.assertEqual(validate_transport(b"x"*(s.MAX_RAW+1),b"x"*(s.MAX_CONTEXT+1),b"{}").diagnostics[0].field,"$.raw")
        self.assertEqual(validate_transport(b"",b"x"*(s.MAX_CONTEXT+1),b"{}").diagnostics[0].field,"$.context")


    def test_malformed_native_times_are_context_invalid_before_fingerprint_or_payload(self):
        _,context,payload=direct_case();original=json.loads(make_envelope(payload,context))
        for badtime in (c.InstantV1('NOT-A-TIME','UTC',0),c.InstantV1('2024-02-30T12:00:00Z',None,0),
                        c.InstantV1('2024-01-31T22:00:00.1234567Z',None,7),c.DateOnlyV1('2024-02-30',None)):
            bad=replace(context,expected_provenance=replace(context.expected_provenance,evidence_at=badtime))
            raw_context=s.canonical(s.primitive(bad))
            for matching in (False,True):
                env=copy.deepcopy(original)
                if matching:env['fingerprint']['context_sha256']=hashlib.sha256(raw_context).hexdigest()
                env['payload_base64']='/w==';env['payload_sha256']='0'*64
                result=validate_transport(RAW,raw_context,s.canonical(env))
                self.assertEqual((result.diagnostics[0].namespace,result.diagnostics[0].code,result.diagnostics[0].field),('source_v1','source_context_invalid','$.context'))
            for operation in (s.context_bytes,s.fingerprint,s.adapter_input):
                with self.assertRaises(s.ContractError):operation(bad)

    def test_direct_external_selector_semantics_and_aliases_precede_fingerprint(self):
        batch,context,payload=direct_case();source=batch.activities[0].identity.source
        variants=(replace(source,source_account_key=None),replace(source,source_account_key='ghost-alias'),
                  replace(source,record_kind='cash_flows'),replace(source,source_id=''),replace(source,revision=''),
                  replace(source,kind='coverage',record_kind=None),replace(source,kind='snapshot'),replace(source,kind='membership'))
        for selector in variants:
            reference=c.ExternalSourceRefV1(batch.tenant_id,batch.portfolio_id,selector)
            graph=context.binding_context.value.reference_graph
            for destination in ('economic','counterpart','cash_leg'):
                activity=graph.activities[0]
                if destination=='economic':activity=replace(activity,economic_references=(reference,))
                else:activity=replace(activity,cash_flow=s.CashFlowReference('in','external',None,reference if destination=='counterpart' else None,reference if destination=='cash_leg' else None))
                binding=replace(context.binding_context.value,reference_graph=replace(graph,activities=(activity,)))
                bad=replace(context,binding_context=replace(context.binding_context,value=binding))
                raw_context=s.canonical(s.primitive(bad));envelope=make_envelope(payload,context)
                result=validate_transport(RAW,raw_context,envelope)
                self.assertEqual((result.diagnostics[0].code,result.diagnostics[0].field),('source_context_invalid','$.context'))

    def test_historical_reference_uses_declared_alias_without_current_fact_lookup(self):
        batch,context,_=direct_case();activity=batch.activities[0]
        reference=c.ExternalSourceRefV1(batch.tenant_id,batch.portfolio_id,replace(activity.identity.source,source_id='historical-only',revision='r0'))
        graph=context.binding_context.value.reference_graph
        allowed=replace(context.binding_context.value,reference_graph=replace(graph,activities=(replace(graph.activities[0],economic_references=(reference,)),)))
        context=replace(context,binding_context=replace(context.binding_context,value=allowed))
        batch=replace(batch,activities=(replace(activity,economic_references=(reference,)),))
        result=self.outcome(context,encode_domain_v1(batch))
        self.assertEqual((result.status,result.ingestible),('VALID_SHAPE',False))
        self.assertNotIn(reference.selector,tuple(x.source for x in allowed.facts))

    def test_valid_native_date_only_and_legacy_tokens_roundtrip_unchanged(self):
        _,context,_=direct_case()
        legacy=c.LegacyDateTimeV1('2024-01-31T22:00:00+00:00',c.LegacyRecordRefV1('a'*64,'evidence',None,'context.evidence_at'))
        for at in (c.InstantV1('2024-01-31T17:00:00-05:00','America/Toronto',0),c.DateOnlyV1('2024-01-31',None),legacy):
            provenance=replace(context.expected_provenance,evidence_at=at,canonical_sha256='a'*64 if at is legacy else None)
            changed=replace(context,expected_provenance=provenance)
            self.assertEqual(s.decode_context(s.context_bytes(changed)),changed)
            self.assertEqual(s.primitive(changed.expected_provenance)['evidence_at']['token'],at.token)
