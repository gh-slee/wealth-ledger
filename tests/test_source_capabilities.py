"""Independent pre-implementation vectors and inert source metadata regressions."""
from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from wealth_ledger.data_sources.contract_v1 import (ContractError, MAX_COUNTER, adapter_input,
    canonical, context_bytes, decode_context, fingerprint, installation_id, primitive)
from wealth_ledger.data_sources.catalog_v1 import decode_catalog, validate_transition
from wealth_ledger.data_sources.lifecycle_v1 import effective_status

FIXTURES = Path(__file__).parent / "fixtures" / "source_capabilities"


def context_vector(name="parser2_availability1"):
    return next(x for x in json.loads((FIXTURES / "oracle.json").read_text())["contexts"] if x["name"] == name)


class SourceCapabilitiesTests(unittest.TestCase):
    def test_fixed_context_bytes_and_hashes_and_minimal_child(self):
        vectors = json.loads((FIXTURES / "oracle.json").read_text())["contexts"]
        for vector in vectors:
            with self.subTest(vector=vector["name"]):
                context = decode_context(vector["canonical_utf8"].encode())
                self.assertEqual(context_bytes(context), vector["canonical_utf8"].encode())
                self.assertEqual(hashlib.sha256(context_bytes(context)).hexdigest(), vector["sha256"])
                self.assertEqual(fingerprint(context), vector["fingerprint"])
                child = adapter_input(context)
                self.assertEqual(set(child), {"context_version", "payload_kind", "context"} |
                                 ({"expected_provenance"} if context.parse_context is None else set()))
                self.assertNotIn("synthetic_db", canonical(child).decode())
                self.assertNotIn("127.0.0.1", canonical(child).decode())

    def test_aware_offset_is_preserved_and_changes_context_hash(self):
        vector = context_vector()
        original = decode_context(vector["canonical_utf8"].encode())
        value = copy.deepcopy(vector["primitive"])
        value["parse_context"]["value"]["evidence_at"] = "2024-03-01T07:00:00-05:00"
        changed = decode_context(canonical(value))
        self.assertNotEqual(context_bytes(original), context_bytes(changed))
        self.assertEqual(changed.parse_context.value.evidence_at.isoformat(), "2024-03-01T07:00:00-05:00")

    def test_context_rejects_extra_missing_cross_scope_and_inconsistent_graph(self):
        vector = context_vector("domain1_reference_correction")["primitive"]
        variants = []
        value = copy.deepcopy(vector);value["unexpected"] = "secret";variants.append(value)
        value = copy.deepcopy(vector);del value["binding_context"]["value"]["reference_graph"];variants.append(value)
        value = copy.deepcopy(vector);value["tenant_id"] = "99999999-9999-4999-8999-999999999999";variants.append(value)
        value = copy.deepcopy(vector);value["binding_context"]["value"]["reference_graph"]["activities"][0]["legs"] = [];variants.append(value)
        value = copy.deepcopy(vector);value["availability_generation"] = True;variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ContractError):
                decode_context(canonical(value))

    def test_catalog_discovery_never_loads_factories_and_is_canonical(self):
        with patch("wealth_ledger.source_registry.build_registry", side_effect=AssertionError("No dispatch")):
            catalog = decode_catalog((FIXTURES / "catalog.json").read_bytes())
        self.assertEqual(len(catalog.definitions), 1)
        self.assertEqual(len(catalog.installations), 2)
        with self.assertRaises(ContractError):
            decode_catalog(json.dumps(primitive(catalog)).encode())
        duplicate = (FIXTURES / "catalog.json").read_bytes().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        with self.assertRaises(ContractError):
            decode_catalog(duplicate)

    def test_availability_aba_preserves_immutable_installation_and_never_resets(self):
        catalog = decode_catalog((FIXTURES / "catalog.json").read_bytes())
        retired = replace(catalog, catalog_revision="2", availability=tuple(replace(x,status="RETIRED",availability_generation="2") for x in catalog.availability))
        active = replace(retired, catalog_revision="3", availability=tuple(replace(x,status="ACTIVE",availability_generation="3") for x in retired.availability))
        self.assertTrue(validate_transition(catalog, retired))
        self.assertTrue(validate_transition(retired, active))
        self.assertEqual(catalog.installations, active.installations)
        self.assertFalse(validate_transition(active, active))
        reset = replace(active, availability=tuple(replace(x,availability_generation="1") for x in active.availability))
        with self.assertRaises(ContractError):
            validate_transition(retired, reset)
        exhausted = replace(catalog, availability=tuple(replace(x,availability_generation=str(MAX_COUNTER)) for x in catalog.availability))
        with self.assertRaises(ContractError):
            validate_transition(exhausted, replace(exhausted,catalog_revision="2",availability=retired.availability))

    def test_cosmetic_catalog_update_does_not_change_availability_or_installation(self):
        catalog = decode_catalog((FIXTURES / "catalog.json").read_bytes())
        edited = replace(catalog,catalog_revision="2",definitions=(replace(catalog.definitions[0],display_name="New display"),))
        self.assertTrue(validate_transition(catalog,edited))
        self.assertEqual(catalog.availability,edited.availability)
        self.assertEqual(tuple(map(installation_id,catalog.installations)),tuple(map(installation_id,edited.installations)))

    def test_status_priority_and_unactivatable_api(self):
        common = dict(capability="FILE_IMPORT",enabled=True,installation_id="old",parent_installation_id="old",active_installation_id="new",connection=True)
        self.assertEqual(effective_status(**common),("CONFIRMATION_REQUIRED",None))
        self.assertEqual(effective_status(**(common | {"enabled":False,"parent_enabled":False})),("DISABLED",None))
        self.assertEqual(effective_status(**(common | {"parent_enabled":False})),("SOURCE_DISABLED",None))
        self.assertEqual(effective_status(**(common | {"availability_generation":str(MAX_COUNTER)})),("UNAVAILABLE","source_counter_exhausted"))
        self.assertEqual(effective_status(**(common | {"capability":"PULL_API","enabled":False})),("UNAVAILABLE","source_capability_unavailable"))


    def test_selected_withdrawal_and_counter_priority_preserve_retirement_upgrade(self):
        for connection in (False,True):
            common=dict(capability='FILE_IMPORT',enabled=True,installation_id='old',parent_installation_id='old',active_installation_id='new',connection=connection)
            self.assertEqual(effective_status(**common,availability_status='RETIRED'),('CONFIRMATION_REQUIRED',None))
            self.assertEqual(effective_status(**common,availability_status='REVOKED'),('UNAVAILABLE','source_unavailable'))
            for status in ('RETIRED','REVOKED'):
                self.assertEqual(effective_status(**common,availability_status=status,selected_availability_generation=str(MAX_COUNTER)),('UNAVAILABLE','source_counter_exhausted'))
            self.assertEqual(effective_status(**(common|{'enabled':False}),availability_status='REVOKED'),('DISABLED',None))
            if connection:self.assertEqual(effective_status(**common,parent_enabled=False,availability_status='REVOKED'),('SOURCE_DISABLED',None))
