"""Synthetic frozen source/report confirmation, atomic failure and retry contracts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

import test_source_submission as submission_fixtures
from test_source_submission import CONTEXTS
from test_source_legacy_projection import FX, AT, START, quote
from test_source_projection import hashes
from wealth_ledger.application import ApplicationService
from wealth_ledger.workspace import resolve_workspace
from wealth_ledger import operations
from wealth_ledger.source_ingestion import read_facts, require_report_projection
from wealth_ledger.source_publication import (prepare_source_report, load_source_report, confirm_source_report,
    resume_source_report, frozen_report, verify_source_publications)
from wealth_ledger.source_submission import SubmissionError
from wealth_ledger.source_valuation import read_observations


def publisher_receipt(project,payload,result,*,frozen_analysis):
    """Small checksummed receipt double; actual three-format rendering is separate."""
    assert frozen_analysis is True
    from wealth_ledger.publishing import _set_latest
    folder=Path(project)/"reports"/payload["meta"]["as_of"][:10]/("r"+str(len(list((Path(project)/"reports").glob("*/r*/manifest.json")))+1).zfill(2))
    folder.mkdir(parents=True)
    for name in ("report.md","report.pdf","portfolio.ods"):(folder/name).write_bytes(b"Synthetic publisher receipt double")
    (folder/"data.json").write_text(json.dumps(payload))
    pointer=Path(project)/"reports/latest.json"
    manifest={"snapshot_id":None,"source_valuation_id":payload["meta"]["source_report_observation_id"],"report_model":"source-neutral-1",
        "import":result,"previous_latest":json.loads(pointer.read_text()) if pointer.exists() else None,"workbook_validation":{},
        "bundle_files":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}}
    manifest["data_sha256"]=manifest["bundle_files"]["data.json"]
    (folder/"manifest.json").write_text(json.dumps(manifest))
    _set_latest(project,folder,None)
    return {"output":str(folder),"snapshot_id":None,"workbook":{}}


class SourcePublicationTests(unittest.TestCase):
    setUp=submission_fixtures.SubmissionTests.setUp

    def inputs(self,**changes):
        return {"as_of":AT,"period_start":START,"generated_at":AT,"fx":FX,**changes}

    def prepare(self,**changes):
        return prepare_source_report(self.project,self.paths,contexts=CONTEXTS,bindings=changes.pop("bindings",self.bindings),
            valuation=changes.pop("valuation",self.inputs()),directory=changes.pop("directory",self.directory),**changes)

    def confirm(self,value=None,**kwargs):
        value=value or self.prepare()
        with patch("wealth_ledger.lookthrough.attach_analysis"):
            return confirm_source_report(self.project,self.directory,value["approval_sha256"],**kwargs)

    def saved(self,identifier):
        return operations.get(self.project,identifier)

    def test_preview_is_offline_and_does_not_change_live_financial_state(self):
        before=hashes(self.project)
        with patch("urllib.request.urlopen",side_effect=AssertionError("No network")):
            value=self.prepare()
        self.assertEqual(hashes(self.project),before)
        self.assertEqual(value["status"],"awaiting_confirmation")
        self.assertFalse(value["report_published"])
        self.assertEqual(len(value["account_review"]),5)
        self.assertIsNotNone(value["observed_totals"]["total_cad"])

    def test_missing_mapping_returns_review_without_saving_partial_bundle(self):
        value=self.prepare(bindings=())
        self.assertEqual(value["status"],"mapping_required")
        self.assertFalse(self.directory.exists());self.assertEqual(hashes(self.project),{})

    def test_exact_confirmation_commits_facts_valuation_and_frozen_report_together(self):
        value=self.prepare()
        with patch("wealth_ledger.publishing.publish",side_effect=publisher_receipt):result=self.confirm(value)
        self.assertEqual(result["status"],"published")
        saved=self.saved(value["operation_id"]);payload=frozen_report(self.project,saved)
        self.assertEqual(saved["status"],"published")
        self.assertTrue(read_facts(self.project)["records"])
        self.assertEqual(len(read_observations(self.project)),1)
        self.assertEqual(payload["source_projection"]["btc"]["actual_full_cost_cad"],None)
        self.assertEqual(payload["periods"],[])
        verify_source_publications(self.project)

    def test_original_csv_paths_and_parsers_are_not_used_by_confirmation(self):
        value=self.prepare()
        for path in self.paths:path.unlink()
        with patch("wealth_ledger.source_submission.parse_sources",side_effect=AssertionError("No parser")),patch("wealth_ledger.publishing.publish",side_effect=publisher_receipt):
            self.confirm(value)

    def test_changed_digest_and_extra_bundle_file_are_rejected_without_writes(self):
        value=self.prepare();before=hashes(self.project)
        with self.assertRaises(SubmissionError):confirm_source_report(self.project,self.directory,"0"*64)
        (self.directory/"extra.json").write_text("{}")
        with self.assertRaises(SubmissionError):self.confirm(value)
        self.assertEqual(hashes(self.project),before)

    def test_changed_raw_and_normalized_evidence_are_rejected(self):
        for name in ("0.csv","0.json","configuration.json","manifest.json"):
            with self.subTest(name=name):
                directory=self.root/("preview-"+name);value=self.prepare(directory=directory)
                path=directory/"ingestion"/name;path.chmod(0o600);path.write_bytes(path.read_bytes()+b" ")
                with self.assertRaises(SubmissionError):load_source_report(self.project,directory,value["approval_sha256"])
        self.assertEqual(hashes(self.project),{})

    def test_preview_cannot_be_applied_to_another_workspace(self):
        value=self.prepare();other=self.root/"other";other.mkdir()
        with self.assertRaisesRegex(SubmissionError,"workspace_mismatch"):
            confirm_source_report(other,self.directory,value["approval_sha256"])
        self.assertEqual(list(other.iterdir()),[])

    def test_configuration_change_stales_confirmation_before_mutation(self):
        config=self.root/"parsers.json";config.write_text('{"schema_version":1,"enabled":[],"bindings":[]}')
        value=self.prepare(config_path=config);config.write_text(config.read_text()+" ")
        with self.assertRaisesRegex(SubmissionError,"stale_configuration"):self.confirm(value,config_path=config)
        self.assertEqual(operations.list_operations(self.project),[])

    def test_engine_change_stales_confirmation_before_mutation(self):
        value=self.prepare()
        with patch("wealth_ledger.source_ingestion.environment_fingerprint",return_value="b"*64),self.assertRaisesRegex(SubmissionError,"stale_environment"):
            self.confirm(value)
        self.assertEqual(operations.list_operations(self.project),[])

    def test_financial_or_settings_change_stales_preview(self):
        value=self.prepare();(self.project/"config").mkdir();(self.project/"config/local.toml").write_text("[reporting]\nlocale='en-CA'\n")
        with self.assertRaisesRegex(SubmissionError,"stale_submission"):self.confirm(value)
        self.assertEqual(operations.list_operations(self.project),[])

    def test_failed_analysis_leaves_no_live_facts_or_valuation(self):
        value=self.prepare()
        with patch("wealth_ledger.lookthrough.attach_analysis",side_effect=RuntimeError("Synthetic interruption")),self.assertRaises(RuntimeError):
            confirm_source_report(self.project,self.directory,value["approval_sha256"])
        self.assertEqual(read_facts(self.project)["records"],[])
        self.assertEqual(read_observations(self.project),[])
        self.assertEqual(self.saved(value["operation_id"])["status"],"data_failed")
        self.assertFalse((self.project/"data/raw/source-publications").exists())

    def test_publish_failure_keeps_committed_inputs_and_resumes_without_parser_or_analysis(self):
        value=self.prepare()
        with patch("wealth_ledger.publishing.publish",side_effect=RuntimeError("Synthetic renderer interruption")),self.assertRaises(operations.ReportOperationError):self.confirm(value)
        original=frozen_report(self.project,self.saved(value["operation_id"]))
        count=len(read_facts(self.project)["records"])
        self.assertEqual(self.saved(value["operation_id"])["status"],"report_failed")
        shutil.rmtree(self.directory)
        with patch("wealth_ledger.source_publication.make_source_payload",side_effect=AssertionError("No revaluation")),patch("wealth_ledger.lookthrough.attach_analysis",side_effect=AssertionError("No ETF refresh")),patch("wealth_ledger.source_ingestion._apply",side_effect=AssertionError("No reimport")),patch("wealth_ledger.publishing.publish",side_effect=publisher_receipt):
            result=resume_source_report(self.project,value["operation_id"])
        self.assertEqual(result["status"],"published")
        self.assertEqual(frozen_report(self.project,self.saved(value["operation_id"])),original)
        self.assertEqual(len(read_facts(self.project)["records"]),count)

    def test_interruption_after_bundle_move_recovers_without_second_edition(self):
        value=self.prepare()
        def interrupted(*args,**kwargs):publisher_receipt(*args,**kwargs);raise RuntimeError("Delivery interrupted")
        with patch("wealth_ledger.publishing.publish",side_effect=interrupted),self.assertRaises(operations.ReportOperationError):self.confirm(value)
        with patch("wealth_ledger.publishing.publish",side_effect=AssertionError("No second report")):
            result=resume_source_report(self.project,value["operation_id"])
        self.assertEqual(result["status"],"published")
        self.assertEqual(len(list((self.project/"reports").glob("*/r*/manifest.json"))),1)

    def test_atomic_cleanup_interruption_is_not_downgraded_to_failed_data(self):
        value=self.prepare();original=operations.atomic_data
        def interrupted(*args,**kwargs):original(*args,**kwargs);raise RuntimeError("Cleanup interrupted")
        with patch.object(operations,"atomic_data",side_effect=interrupted),self.assertRaises(RuntimeError):self.confirm(value)
        self.assertEqual(self.saved(value["operation_id"])["status"],"data_committed")
        with patch("wealth_ledger.publishing.publish",side_effect=publisher_receipt):resume_source_report(self.project,value["operation_id"])

    def test_changed_financial_state_after_failure_blocks_retry(self):
        value=self.prepare()
        with patch("wealth_ledger.publishing.publish",side_effect=RuntimeError),self.assertRaises(operations.ReportOperationError):self.confirm(value)
        from wealth_ledger.wallet import add_balance
        add_balance(self.project,"0.008",AT,now=AT)
        with self.assertRaises(SubmissionError):resume_source_report(self.project,value["operation_id"])

    def test_corrupt_frozen_report_blocks_retry_and_verification(self):
        value=self.prepare()
        with patch("wealth_ledger.publishing.publish",side_effect=RuntimeError),self.assertRaises(operations.ReportOperationError):self.confirm(value)
        saved=self.saved(value["operation_id"]);path=self.project/saved["result"]["payload_path"]
        path.chmod(0o600);path.write_bytes(b"{}")
        with self.assertRaises(SubmissionError):resume_source_report(self.project,value["operation_id"])
        with self.assertRaises(SubmissionError):verify_source_publications(self.project)

    def test_published_retry_never_rolls_latest_back_and_works_after_workspace_copy(self):
        value=self.prepare()
        with patch("wealth_ledger.publishing.publish",side_effect=publisher_receipt):first=self.confirm(value)
        later=self.root/"later";inputs=self.inputs(as_of="2024-05-01T00:00:00Z",generated_at="2024-05-01T00:00:00Z")
        next_preview=prepare_source_report(self.project,valuation=inputs,directory=later)
        with patch("wealth_ledger.lookthrough.attach_analysis"),patch("wealth_ledger.publishing.publish",side_effect=publisher_receipt):
            confirm_source_report(self.project,later,next_preview["approval_sha256"])
        pointer=(self.project/"reports/latest.json").read_bytes()
        self.assertEqual(resume_source_report(self.project,value["operation_id"])["status"],"already_published")
        self.assertEqual((self.project/"reports/latest.json").read_bytes(),pointer)
        copied=self.root/"copied";shutil.copytree(self.project,copied)
        result=resume_source_report(copied,value["operation_id"])
        self.assertTrue(Path(result["output"]).is_relative_to(copied))
        self.assertEqual((copied/"reports/latest.json").read_bytes(),pointer)

    def test_saved_data_only_preview_and_application_service_use_same_workflow(self):
        service=ApplicationService(resolve_workspace(explicit=self.project))
        value=service.source_report_preview(valuation=self.inputs(),directory=self.directory)
        with patch("wealth_ledger.publishing.publish",side_effect=publisher_receipt):
            result=service.source_report_confirm(self.directory,value["approval_sha256"])
        self.assertEqual(result["status"],"published")
        self.assertIsNone(frozen_report(self.project,self.saved(value["operation_id"]))["totals"]["total_cad"])

    def test_native_daily_gate_remains_until_complete_cutover_acceptance(self):
        with patch("wealth_ledger.publishing.publish",side_effect=publisher_receipt):self.confirm()
        with self.assertRaisesRegex(ValueError,"report_projection_unavailable"):require_report_projection(self.project)

    def test_invalid_valuation_is_rejected_without_live_financial_writes(self):
        for change in ({"fx":None},{"as_of":"2024-03-01"},{"generated_at":START},{"unknown_option":True}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.prepare(valuation=self.inputs(**change))
        self.assertEqual(hashes(self.project),{})

    def test_actual_three_format_publication_in_all_locales_is_checksum_verified(self):
        from wealth_ledger.publishing import verify_bundle
        from wealth_ledger.report_checks import validate_report_presentation
        from wealth_ledger.validation import validate_formula_caches
        from wealth_ledger.lookthrough import attach_analysis
        from wealth_ledger.fund_sources import holding
        original=attach_analysis
        def synthetic_fund(fund_id,directory):
            return {"fund_id":fund_id,"status":"ok","as_of":"2024-01-31","retrieved_at":AT,"issuer":"SYNTHETIC","latest_checked":False,"evidence":[],
                "official_url":"https://example.test/synthetic-constituents","rows":[holding("Synthetic Company",100,ticker="SYN",country="CA",gics_sector="Industrials")]}
        def analysis(project,payload):return original(project,payload,fetcher=synthetic_fund)
        for locale in ("en-CA","zh-TW","zh-CN"):
            directory=self.root/("actual-"+locale)
            if locale=="en-CA":preview=self.prepare(directory=directory,valuation=self.inputs(report_locale=locale))
            else:preview=prepare_source_report(self.project,valuation=self.inputs(report_locale=locale),directory=directory)
            with patch("urllib.request.urlopen",side_effect=AssertionError("No network")),patch("wealth_ledger.lookthrough.attach_analysis",side_effect=analysis):
                result=confirm_source_report(self.project,directory,preview["approval_sha256"])
            output=Path(result["output"]);saved=self.saved(preview["operation_id"]);payload=frozen_report(self.project,saved)
            self.assertEqual(verify_bundle(self.project,output,preview["operation_id"])["source_valuation_id"],saved["result"]["source_valuation_id"])
            self.assertEqual(validate_report_presentation(payload,output,locale=locale)["status"],"passed")
            self.assertEqual(validate_formula_caches(output/"portfolio.ods")["cache_mismatches"],0)
            self.assertTrue((output/"company-exposure.csv").is_file())
            self.assertEqual(resume_source_report(self.project,preview["operation_id"])["status"],"already_published")

    def test_concurrent_ledger_settings_change_aborts_before_installing_facts(self):
        value=self.prepare()
        def changed(*args,**kwargs):
            (self.project/"config").mkdir(exist_ok=True)
            (self.project/"config/local.toml").write_text("[reporting]\nlocale='en-CA'\n")
        with patch("wealth_ledger.lookthrough.attach_analysis",side_effect=changed),self.assertRaisesRegex(SubmissionError,"stale_submission"):
            confirm_source_report(self.project,self.directory,value["approval_sha256"])
        self.assertEqual(read_facts(self.project)["records"],[])
        self.assertEqual(read_observations(self.project),[])

    def test_invalid_recovered_bundle_never_changes_latest_pointer(self):
        value=self.prepare()
        def interrupted(*args,**kwargs):publisher_receipt(*args,**kwargs);raise RuntimeError("Before handoff")
        with patch("wealth_ledger.publishing.publish",side_effect=interrupted),self.assertRaises(operations.ReportOperationError):self.confirm(value)
        (self.project/"reports/latest.json").unlink();(self.project/"reports/latest").unlink(missing_ok=True)
        path=next((self.project/"reports").glob("*/r*/data.json"))
        changed=json.loads(path.read_text());changed["meta"]["kind"]="baseline";path.write_text(json.dumps(changed))
        manifest=path.with_name("manifest.json");content=json.loads(manifest.read_text())
        content["data_sha256"]=content["bundle_files"]["data.json"]=hashlib.sha256(path.read_bytes()).hexdigest();manifest.write_text(json.dumps(content))
        with self.assertRaises(operations.ReportOperationError):resume_source_report(self.project,value["operation_id"])
        self.assertFalse((self.project/"reports/latest.json").exists())
