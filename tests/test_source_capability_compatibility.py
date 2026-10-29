"""Source framing preserves accepted literal Wealthsimple/Bull parser archives."""
from dataclasses import replace
import base64
import unittest

from wealth_ledger import source_v2 as old
from wealth_ledger.domain.legacy_bridge_v1 import bridge_parser_v2
from wealth_ledger.data_sources import contract_v1 as s
from wealth_ledger.data_sources.compatibility_v1 import builtin_descriptors
from wealth_ledger.data_sources.transport_v1 import make_envelope, validate_transport
from test_domain_bridge_v1 import (WS_RAW,WS_ARCHIVE,BULL_RAW,BULL_ARCHIVE,context_for)


class SourceCapabilityCompatibilityTests(unittest.TestCase):
    def test_both_existing_immutable_archives_bridge_without_reparse_or_booking(self):
        for raw,archive in ((WS_RAW,WS_ARCHIVE),(BULL_RAW,BULL_ARCHIVE)):
            original=old.decode_batch(archive,raw);binding=context_for(original)
            accepted=bridge_parser_v2(raw,archive,binding)
            self.assertEqual(accepted.blockers,())
            descriptor=s.Descriptor(1,original.adapter.provider_id,original.adapter.provider_id,original.adapter.adapter_id,
                "wealth-ledger","1.0.0",original.adapter.adapter_id,"wealth_ledger.source_builtin:registrations",
                "a"*64,"b"*64,1,1,2,"parser_v2",("FILE_IMPORT",),original.adapter.export_versions,
                ("CASH","CRYPTO","SECURITY"),"required" if original.adapter.provider_id=="bullbitcoin" else "forbidden","reviewed-file-v1")
            context=s.SourceContextV1(1,s.InternalRealm("synthetic_db","101",None,None,"44444444-4444-4444-8444-444444444444","0"),
                binding.tenant_id,binding.portfolio_id,binding.connections[0],s.digest(s.primitive(binding.connections[0])),
                "0","1","1",descriptor,s.installation_id(descriptor),"FILE_IMPORT",original.export_version,
                binding.mapping_revision,binding.evidence_reference,s.ParserBinding("parser2_context_v1",original.evidence.context),
                s.BridgeBinding("bridge_context_v1",binding),accepted.candidate.provenance)
            result=validate_transport(raw,s.context_bytes(context),make_envelope(archive,context))
            self.assertEqual((result.status,result.ingestible),("VALID_SHAPE",False))
            self.assertEqual(base64.b64decode(result.candidate_domain_base64),accepted.candidate_bytes)
            self.assertEqual(accepted.original_canonical,archive)
            self.assertEqual(old.decode_batch(archive,raw),original)
            missing=replace(context,binding_context=s.BridgeBinding("bridge_context_v1",replace(binding,facts=())))
            result=validate_transport(raw,s.context_bytes(missing),make_envelope(archive,missing))
            self.assertEqual((result.status,result.diagnostics[0].code),("BLOCKED","bridge_mapping_required"))
            self.assertIsNone(result.candidate_domain_base64)
            absent_aliases=replace(context,binding_context=s.BridgeBinding("bridge_context_v1",replace(binding,aliases=())))
            result=validate_transport(raw,s.context_bytes(absent_aliases),make_envelope(archive,absent_aliases))
            self.assertEqual((result.status,result.diagnostics[0].code),("BLOCKED","bridge_mapping_required"))
            wrong=replace(missing,expected_provenance=replace(missing.expected_provenance,adapter_version="wrong-version"))
            result=validate_transport(raw,s.context_bytes(wrong),make_envelope(archive,wrong))
            self.assertEqual((result.status,result.diagnostics[0].code),("BLOCKED","source_reference_mismatch"))

    def test_builtin_metadata_uses_implemented_grammar_and_explicit_content_binding(self):
        descriptors=builtin_descriptors(package_distribution="wealth-ledger",package_version="1.0.0",artifact_sha256="a"*64,
            execution_image_digest="b"*64,entry_point_target="wealth_ledger.source_builtin:registrations")
        self.assertEqual([(x.provider_id,x.adapter_id,x.parser_api_version,x.format_versions,x.alias_policy) for x in descriptors],
            [("wealthsimple","wealthsimple.holdings",2,("wealthsimple-holdings-footer-v1",),"forbidden"),
             ("bullbitcoin","bullbitcoin.orders",2,("bullbitcoin-orders-utc-v1",),"required")])
        for descriptor in descriptors:
            self.assertEqual(descriptor.artifact_sha256,"a"*64)
            self.assertEqual(descriptor.execution_image_digest,"b"*64)
            self.assertEqual(descriptor.capabilities,("FILE_IMPORT",))
