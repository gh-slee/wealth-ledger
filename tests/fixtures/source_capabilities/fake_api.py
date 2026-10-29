"""Invented offline API/file adapter; never installed in a production catalog."""
from wealth_ledger.data_sources import contract_v1 as s
from wealth_ledger.domain import canonical_v1 as c
from wealth_ledger.domain.validation_v1 import encode_domain_v1


def normalize(raw, adapter_context, *, transport):
    """Same literal payment/acquisition semantics over two explicit transports."""
    if transport not in {'FILE_IMPORT', 'PULL_API'}:
        raise ValueError('Invalid test transport')
    response=s.load_json(raw,limit=s.MAX_RAW)
    if response!={'cad_paid':'700.00','btc_received':'0.01000000'}:
        raise ValueError('Only the invented response is supported')
    if set(adapter_context)!={'context_version','payload_kind','context','expected_provenance'} or adapter_context['context_version']!=1 or adapter_context['payload_kind']!='domain_v1':
        raise ValueError('Invalid minimal direct context')
    binding=s.decode(s.DomainBinding,adapter_context['context'])
    provenance=s.decode(c.ProvenanceV1,adapter_context['expected_provenance'])
    allowed=binding.value
    if allowed.connection.kind!=transport or len(allowed.reference_graph.activities)!=1 or len(allowed.reference_graph.coverage)!=1:
        raise ValueError('Invalid invented scope')
    graph=allowed.reference_graph.activities[0];scope=allowed.reference_graph.coverage[0]
    if graph.identity.change!='original' or len(graph.legs)!=2 or tuple(x.role for x in graph.legs)!=('PAYMENT','ACQUISITION'):
        raise ValueError('Invalid invented activity')
    identity=c.FactIdentityV1(graph.identity.id,graph.identity.source,'original',None,None,allowed.evidence_reference)
    at=provenance.source_effective_at
    event=c.ActivityEventV1(identity,at,'BUY','purchase','completed','completed',
        (c.ActivityLegV1(graph.legs[0].account,graph.legs[0].instrument,c.DecimalTokenV1('-700.00'),'PAYMENT'),
         c.ActivityLegV1(graph.legs[1].account,graph.legs[1].instrument,c.DecimalTokenV1('0.01000000'),'ACQUISITION')),
        None,c.MoneyV1(c.DecimalTokenV1('0.00'),'CAD'),(),(),None,None,None,c.SupportV1('supported_shape'))
    coverage=c.CoverageV1(scope.connection,scope.source_account_key,scope.account,scope.kind,scope.scope_id,scope.revision,
        scope.parent,c.PointV1(at),scope.instrument_scope,'complete','Explicit invented offline response',scope.observation_id)
    return encode_domain_v1(c.DomainBatchV1(1,c.DECIMAL_PROFILE,allowed.tenant_id,allowed.portfolio_id,allowed.mapping_revision,
        allowed.evidence_reference,provenance,allowed.accounts,(allowed.connection,),allowed.aliases,allowed.instruments,allowed.issuers,(coverage,),(),(event,)))
