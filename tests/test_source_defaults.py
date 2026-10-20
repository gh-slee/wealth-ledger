"""Default preparation, explicit reusable context and correction acceptance."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_source_imports as entry
from test_source_builtin import ROOT, csv_change, CONTEXT
from test_source_legacy_projection import AT, FX
from wealth_ledger.source_profiles import source_profiles, resolve_profiles
from wealth_ledger.source_builtin import WealthsimpleHoldings, WS_FORMAT
from wealth_ledger import source_v2 as v2


class DefaultSourceTests(unittest.TestCase):
    setUp = entry.ImportEntryTests.setUp
    financial = entry.ImportEntryTests.financial
    preview = entry.ImportEntryTests.preview
    bind = entry.ImportEntryTests.bind
    approved = entry.ImportEntryTests.approved
    publish = entry.ImportEntryTests.publish

    def seed(self):
        result = self.approved();self.publish(result)
        return source_profiles(self.project)

    def test_profiles_exist_only_after_commit_and_are_explicitly_selected(self):
        self.assertEqual(source_profiles(self.project), [])
        self.assertEqual(list(self.project.iterdir()), [])
        result=self.approved()
        self.assertEqual(source_profiles(self.project), [])
        self.publish(result)
        profiles=source_profiles(self.project);self.assertEqual(len(profiles),2)
        before=self.financial()
        bull=next(row for row in profiles if row['adapter_id']=='bullbitcoin.orders')
        self.assertEqual(set(bull['options']),{'account_alias'})
        with self.assertRaises(ValueError):self.preview(paths=[self.paths[1]])
        ready=self.preview(paths=[self.paths[1]],context_options=[{'profile_id':bull['id']}],directory=self.root/'reused')
        self.assertEqual(ready['preview']['status'],'awaiting_confirmation')
        context=ready['preparation']['contexts'][0]
        self.assertEqual(context['account_alias'],bull['options']['account_alias'])
        self.assertEqual(context['revisions'],[]);self.assertEqual(context['scope_revisions'],[])
        self.assertEqual(self.financial(),before)

    def test_context_selection_rejects_override_adapter_mismatch_and_other_workspace(self):
        profiles=self.seed();profile=profiles[0]
        cases=[([{'profile_id':'f'*64}],{}),([{'profile_id':profile['id'],'account_alias':'another'}],{}),
               ([{'profile_id':profile['id']}],{'1':'different.adapter'}),([{'profile_id':{}}],{})]
        for choices,selections in cases:
            with self.subTest(choices=choices),self.assertRaises(ValueError):resolve_profiles(self.project,choices,1,selections)
        other=self.root/'other';other.mkdir()
        with self.assertRaises(ValueError):resolve_profiles(other,[{'profile_id':profile['id']}],1,{})
        self.assertEqual(list(other.iterdir()),[])

    def test_tampered_saved_evidence_is_not_a_profile_or_silently_reparsed(self):
        self.seed()
        canonical=next((self.project/'data/raw/source-v2').glob('*.json'))
        canonical.chmod(0o600);canonical.write_text(canonical.read_text()+' ')
        with patch('wealth_ledger.source_imports.parse_sources',side_effect=AssertionError('Never reparse')):
            with self.assertRaises(ValueError):source_profiles(self.project)

    def test_explicit_correction_parents_publish_and_are_not_saved_context_defaults(self):
        self.seed()
        original=WealthsimpleHoldings().normalize(self.paths[0].read_bytes(),export_version=WS_FORMAT,context=CONTEXT)
        revisions=[{'account':{'provider':r.key.account.provider,'account_id':r.key.account.account_id},
                    'kind':'holdings','source_id':r.key.source_id,'observation_id':r.observation_id,
                    'supersedes_revision':r.key.revision} for r in original.records]
        scopes=[{'kind':'snapshot','scope_id':r.source_id,'supersedes_revision':r.revision} for r in original.snapshots]
        scopes += [{'kind':'coverage','scope_id':r.scope_id,'account':{'provider':r.account.provider,'account_id':r.account.account_id},
                    'record_kind':r.kind,'observation_id':r.observation_id,'supersedes_revision':r.revision} for r in original.coverage]
        before_profiles=source_profiles(self.project)
        ws=next(p for p in before_profiles if p['adapter_id']=='wealthsimple.holdings')
        self.paths[0].write_bytes(csv_change(self.paths[0].read_bytes(),[(1,'Market Value','201')]))
        with self.assertRaises(ValueError):
            self.preview(paths=[self.paths[0]],directory=self.root/'unattributed-correction')
        ready=self.preview(paths=[self.paths[0]],context_options=[{'profile_id':ws['id'],'revisions':revisions,'scope_revisions':scopes}],directory=self.root/'correction')
        self.assertEqual(ready['preview']['status'],'awaiting_confirmation')
        from wealth_ledger.source_publication import confirm_source_report
        from test_source_publication import publisher_receipt
        with patch('wealth_ledger.lookthrough.attach_analysis'),patch('wealth_ledger.publishing.publish',side_effect=publisher_receipt):
            confirm_source_report(self.project,self.root/'correction',ready['preview']['approval_sha256'])
        self.assertEqual(source_profiles(self.project),before_profiles)
        resolved,_=resolve_profiles(self.project,[{'profile_id':ws['id']}],1,{})
        self.assertNotIn('revisions',resolved[0]);self.assertNotIn('scope_revisions',resolved[0])

    def test_default_cli_auto_plan_location_and_dry_run_never_commits(self):
        command=[sys.executable,str(ROOT/'scripts/update.py'),'--workspace',str(self.project)]
        fx=self.root/'fx.json';fx.write_text(json.dumps(FX))
        args=[str(self.paths[0]),'--fx-file',str(fx),'--valuation-as-of',AT]
        first=subprocess.run(command+args,capture_output=True,text=True,check=True,timeout=60)
        pending=json.loads(first.stdout);self.assertEqual(pending['preview']['status'],'mapping_required')
        self.assertTrue((self.project/'config/local.toml').is_file())
        bindings=self.root/'bindings.json';bindings.write_text(json.dumps({'schema_version':1,'bindings':[r['suggested_choice'] for r in pending['preview']['account_review']]}))
        args += ['--source-bindings',str(bindings)]
        ready=json.loads(subprocess.run(command+args,capture_output=True,text=True,check=True,timeout=60).stdout)
        self.assertEqual(ready['preview']['status'],'awaiting_confirmation')
        self.assertTrue(Path(ready['plan_directory']).is_relative_to(self.project/'work/source-previews'))
        self.assertFalse((self.project/'data/db/portfolio.sqlite3').exists())
        before=self.financial()
        dry=json.loads(subprocess.run(command+args+['--dry-run'],capture_output=True,text=True,check=True,timeout=60).stdout)
        self.assertTrue(dry['dry_run']);self.assertFalse(dry['confirmation_available'])
        self.assertNotIn('approval_sha256',dry['preview']);self.assertNotIn('plan_directory',dry)
        self.assertEqual(self.financial(),before)

    def test_cli_profiles_are_readonly_and_legacy_options_need_explicit_mode(self):
        command=[sys.executable,str(ROOT/'scripts/update.py'),'--workspace',str(self.project)]
        result=subprocess.run(command+['--list-source-profiles'],capture_output=True,text=True,check=True,timeout=30)
        self.assertEqual(json.loads(result.stdout),{'profiles':[]});self.assertEqual(list(self.project.iterdir()),[])
        result=subprocess.run(command+['--snapshot-id','1'],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,2)
        self.assertIn('--native-import',result.stderr)
        self.assertFalse((self.project/'data/db/portfolio.sqlite3').exists())
