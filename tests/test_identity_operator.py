"""Host secret-file fault recovery and real SIGKILL around COMMIT."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from test_identity_support import IdentityCase
from wealth_ledger.web_v2.operator import export_secret,OperatorError


class IdentityOperator(IdentityCase):
    def test_existing_and_symlink_targets_never_issue_or_overwrite(self):
        self.bootstrap()
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'existing';target.write_bytes(b'original')
            link=Path(folder)/'link';link.symlink_to(target)
            before=self.scalar('SELECT count(*) FROM wl_identity.invites')
            for path in [target,link]:
                with self.assertRaises(OperatorError):export_secret(self.operator,'invite',path)
            self.assertEqual(target.read_bytes(),b'original')
            self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.invites'),before)

    def test_postcommit_fsync_failure_revokes_exact_invite(self):
        self.bootstrap()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'invitation'
            original=os.fsync
            calls=[]
            def fail_after_commit(fd):
                calls.append(fd)
                if len(calls)==4:raise OSError('Synthetic export interruption')
                return original(fd)
            with patch('wealth_ledger.web_v2.operator.os.fsync',side_effect=fail_after_commit):
                with self.assertRaises(OperatorError) as caught:export_secret(self.operator,'invite',path)
            record=caught.exception.record_id
            self.assertTrue(record);self.assertTrue(caught.exception.resolved)
            self.assertFalse(path.exists())
            self.assertEqual(self.scalar('SELECT status FROM wl_identity.invites WHERE id=:id',id=record),'revoked')
            receipt=json.loads(path.with_name(path.name+'.receipt.json').read_text())
            self.assertEqual(receipt['record_id'],record)
            self.assertNotIn('token',receipt)

    def kill_export(self,after_commit):
        self.bootstrap()
        from psycopg.conninfo import make_conninfo
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);secret=folder/'operator.conninfo';secret.write_text(self.configs['migration'].conninfo);secret.chmod(0o600)
            target=folder/'invite';marker=folder/'barrier'
            program=r'''
import os,sys,time
from pathlib import Path
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.persistence.identity import IdentityStore
from wealth_ledger.web_v2.operator import export_secret
secret,target,marker,stage=sys.argv[1:]
store=IdentityStore(PostgresConfig.from_secret_file(secret))
original=store.call
def wait():
 Path(marker).write_text('barrier')
 while True:time.sleep(.1)
def call(name,*args,**kwargs):
 if name=='issue_invite_v1':
  if stage=='before':
   journal=kwargs['before_commit']
   def pending(value):journal(value);wait()
   kwargs['before_commit']=pending
  value=original(name,*args,**kwargs)
  if stage=='after':wait()
  return value
 return original(name,*args,**kwargs)
store.call=call
export_secret(store,'invite',target)
'''
            child=subprocess.Popen([sys.executable,'-c',program,str(secret),str(target),str(marker),'after' if after_commit else 'before'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.addCleanup(lambda:child.kill() if child.poll() is None else None)
            deadline=time.monotonic()+10
            while not marker.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(marker.exists())
            receipt=json.loads(target.with_name(target.name+'.receipt.json').read_text());record=receipt['record_id']
            self.assertTrue(receipt['needs_reconciliation'])
            observed=self.scalar('SELECT count(*) FROM wl_identity.invites WHERE id=:id',id=record)
            self.assertEqual(observed,1 if after_commit else 0)
            os.kill(child.pid,signal.SIGKILL);out,err=child.communicate(timeout=5)
            self.assertEqual(child.returncode,-signal.SIGKILL);self.assertEqual(out,b'');self.assertEqual(err,b'')
            if after_commit:
                self.operator.call('revoke_invite_v1',record)
                self.assertEqual(self.scalar('SELECT status FROM wl_identity.invites WHERE id=:id',id=record),'revoked')
            else:
                self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.invites WHERE id=:id',id=record),0)
            self.assertEqual(target.read_bytes(),b'')

    def test_native_kill_before_commit_rolls_back(self):self.kill_export(False)
    def test_native_kill_after_commit_keeps_exact_recovery_id(self):self.kill_export(True)
