"""Opt-in native Linux containment of reviewed code, never a production runner."""
import base64
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from wealth_ledger.data_sources import contract_v1 as s
from wealth_ledger.data_sources.catalog_v1 import verify_installation
from wealth_ledger.data_sources.compatibility_v1 import builtin_descriptors
from wealth_ledger.data_sources.transport_v1 import make_envelope,validate_transport

FIXTURES=Path(__file__).parent/'fixtures/source_capabilities'
ROOT=Path(__file__).resolve().parents[1]
EXPECTED_ENV={'PATH':'/usr/local/bin:/usr/bin:/bin','PYTHONPATH':'/app/src','PYTHONDONTWRITEBYTECODE':'1',
    'PYTHONUNBUFFERED':'1','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TZ':'UTC','HOME':'/nonexistent'}
PROFILE=['--user','10001:10001','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
    '--network','none','--ipc','none','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=33554432,uid=10001,gid=10001',
    '--memory','268435456','--memory-swap','268435456','--cpus','1','--pids-limit','16',
    '--ulimit','cpu=2:2','--ulimit','nofile=64:64','--ulimit','core=0:0']


def docker(*args,timeout=30,input=None):
    result=subprocess.run(['docker',*args],input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if result.returncode:raise RuntimeError('Synthetic Docker operation failed (private diagnostics retained by Docker)')
    return result.stdout


def inspect_container(name):
    return json.loads(docker('inspect',name))[0]


class Harness:
    """One exact owned cgroup; streaming caps precede all output interpretation."""
    def __init__(self,image,evidence):self.image,self.evidence=image,evidence

    def run(self,value,*,cancel_after=None):
        frame=value if type(value) is bytes else s.canonical(value)
        if len(frame)>16*1024*1024:raise ValueError('Synthetic input exceeds limit')
        name='wealth-ledger-source-child-'+uuid.uuid4().hex
        setup_started=time.monotonic();owned=False;process=None;readers=[];writer=None
        output=[bytearray(),bytearray()];limits=[8*1024*1024,64*1024];overflow=threading.Event()
        outcome=None;started=None;kill_at=None;reap_at=None;state=None
        try:
            docker('create','--name',name,'--label','wealth-ledger.test=source-harness','-i',*PROFILE,self.image)
            owned=True;configuration=inspect_container(name)
            process=subprocess.Popen(['docker','start','--attach','--interactive',name],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            def collect(index,stream):
                try:
                    while True:
                        chunk=stream.read(4096)
                        if not chunk:break
                        room=limits[index]-len(output[index])
                        output[index].extend(chunk[:room])
                        if len(chunk)>room:overflow.set()
                finally:stream.close()
            for index,stream in enumerate((process.stdout,process.stderr)):
                thread=threading.Thread(target=collect,args=(index,stream),daemon=True);thread.start();readers.append(thread)
            def feed():
                try:process.stdin.write(frame);process.stdin.flush()
                except (BrokenPipeError,OSError):pass
                finally:process.stdin.close()
            writer=threading.Thread(target=feed,daemon=True);writer.start()
            # Docker's actual StartedAt, rather than image creation/build time,
            # anchors the execution wall clock. Setup has a separate30s bound.
            while started is None:
                state=inspect_container(name)['State']
                if not state['StartedAt'].startswith('0001-'):
                    at=datetime.fromisoformat(state['StartedAt'].replace('Z','+00:00'))
                    started=time.monotonic()-max(0,(datetime.now(timezone.utc)-at).total_seconds())
                elif time.monotonic()-setup_started>30:raise RuntimeError('Synthetic child startup deadline')
                else:time.sleep(.01)
            while process.poll() is None:
                elapsed=time.monotonic()-started
                if overflow.is_set():outcome='output_limit';break
                if cancel_after is not None and elapsed>=cancel_after:outcome='cancelled';break
                if elapsed>=10:outcome='wall_limit';break
                time.sleep(.01)
            if outcome is not None:
                kill_at=time.monotonic();docker('kill',name)
            process.wait(timeout=5);reap_at=time.monotonic()
            for thread in readers:thread.join(timeout=2)
            writer.join(timeout=2)
            if any(t.is_alive() for t in [*readers,writer]):raise RuntimeError('Synthetic stream cleanup deadline')
            state=inspect_container(name)['State']
            # A stream may exceed its cap just as the child exits. Never decode
            # even a valid JSON prefix from any over-limit stream.
            if overflow.is_set():outcome='output_limit'
            if outcome is None:
                if state['OOMKilled']:outcome='resource_exit'
                elif state['ExitCode']!=0:outcome='resource_exit' if state['ExitCode']>=128 else 'child_error'
                else:
                    try:
                        result=s.load_json(bytes(output[0]),limit=limits[0])
                        if s.canonical(result)!=bytes(output[0]) or type(result) is not dict or type(result.get('ok')) is not bool:raise ValueError()
                        if result['ok'] and set(result) not in ({'ok','value'},{'ok','payload_base64'}):raise ValueError()
                        if not result['ok'] and result!={'ok':False,'code':'test_frame_invalid'}:raise ValueError()
                        outcome='ok' if result['ok'] else 'frame_rejected'
                    except (ValueError,s.ContractError):outcome='malformed_output';result=None
            record={'name':name,'outcome':outcome,'setup_seconds':started-setup_started,'execution_seconds':reap_at-started,
                'started_monotonic':started,'kill_monotonic':kill_at,'reaped_monotonic':reap_at,'exit_code':state['ExitCode'],
                'oom_killed':state['OOMKilled'],'stdout_bytes_retained':len(output[0]),'stderr_bytes_retained':len(output[1])}
            return_value={'outcome':outcome,'result':result if outcome in {'ok','frame_rejected'} else None,
                'configuration':configuration,'record':record}
        finally:
            if owned:
                # Remove only the ID/name created by this invocation. force also
                # kills descendants after exceptional host-side control failure.
                docker('rm','--force',name)
            if process is not None and process.poll() is None:
                process.kill();process.wait(timeout=5)
            if process is not None:
                for thread in readers:thread.join(timeout=2)
                if writer:writer.join(timeout=2)
        # Observe disappearance after cgroup cleanup; no descendant can retain
        # this container's namespace/resources. This is not host-wide process IO.
        check=subprocess.run(['docker','inspect',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
        if check.returncode==0:raise RuntimeError('Owned synthetic container survived removal')
        time.sleep(.05)
        record['removed_observed']=True
        (self.evidence/(name+'.json')).write_text(json.dumps(record,indent=2)+'\n')
        return return_value


ENABLED=os.environ.get('WEALTH_LEDGER_SOURCE_HARNESS_TEST')=='1'


@unittest.skipUnless(ENABLED,'Explicit native source harness acceptance required')
class SourceHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=os.environ['WEALTH_LEDGER_SOURCE_HARNESS_BASE_IMAGE']
        if not re.fullmatch('sha256:[0-9a-f]{64}',cls.base):raise RuntimeError('Exact immutable source image required')
        manifest=json.loads(Path(os.environ['WEALTH_LEDGER_SOURCE_HARNESS_CONTEXT']).read_bytes())
        files={name[4:]:digest for name,digest in manifest['files'].items() if name.startswith('src/')}
        if not files:raise RuntimeError('Source context manifest required')
        for name,digest in files.items():
            if hashlib.sha256((ROOT/'src'/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Source image context is stale')
        artifact=s.canonical({'format':'source-content-v1','package_distribution':'wealth-ledger','package_version':'0.1.0',
            'entry_points':[{'name':'wealthsimple.holdings','target':'wealth_ledger.source_builtin:registrations'},
                            {'name':'bullbitcoin.orders','target':'wealth_ledger.source_builtin:registrations'}],
            'files':[{'path':name,'sha256':digest} for name,digest in sorted(files.items())]})
        descriptor=builtin_descriptors(package_distribution='wealth-ledger',package_version='0.1.0',artifact_sha256=hashlib.sha256(artifact).hexdigest(),
            execution_image_digest=cls.base[7:],entry_point_target='wealth_ledger.source_builtin:registrations')[0]
        verify_installation(descriptor,artifact,image_root='/app/src')
        suffix=uuid.uuid4().hex;cls.directory=ROOT/'work'/('source-harness-'+suffix);cls.directory.mkdir(mode=0o700,parents=True)
        context=cls.directory/'context';context.mkdir()
        hashes={}
        for name in ('Dockerfile','worker.py','fake_api.py'):
            path=FIXTURES/name
            if path.is_symlink():raise RuntimeError('Static test fixture required')
            raw=path.read_bytes();hashes[name]=hashlib.sha256(raw).hexdigest();(context/name).write_bytes(raw)
        tag='wealth-ledger-source-base-'+suffix+':test'
        # Removing the sole tag can delete an otherwise untagged candidate ID.
        # Retain a separate owned alias before creating/removing the temporary
        # FROM alias; neither candidate nor evidence images are pruned here.
        retention='wealth-ledger-source-retained-'+suffix+':test'
        docker('tag',cls.base,retention);docker('tag',cls.base,tag)
        try:
            if json.loads(docker('image','inspect',tag))[0]['Id']!=cls.base:raise RuntimeError('Base tag identity changed')
            iid=cls.directory/'image-id'
            docker('build','--network','none','--build-arg','SOURCE_BASE='+tag,'--iidfile',str(iid),str(context),timeout=120)
            cls.image=iid.read_text().strip()
            base=json.loads(docker('image','inspect',cls.base))[0];child=json.loads(docker('image','inspect',cls.image))[0]
            if child['RootFS']['Layers'][:len(base['RootFS']['Layers'])]!=base['RootFS']['Layers']:raise RuntimeError('Child base layers differ')
            if json.loads(docker('image','inspect',tag))[0]['Id']!=cls.base:raise RuntimeError('Base tag identity changed')
            receipt={'scope':'TEST_ONLY_UNREVIEWED_DEVELOPER_IMAGE','base_image':cls.base,'child_image':cls.image,
                'retained_base_tag':retention,'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'fixture_sha256':hashes,
                'source_sha256':files,'linux_architecture':child['Architecture'],'os':child['Os'],'test_host_architecture':platform.machine()}
            if child['Os']!='linux':raise RuntimeError('Linux container evidence required')
            (cls.directory/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        finally:docker('image','rm',tag)
        cls.harness=Harness(cls.image,cls.directory)

    def run_child(self,value,**kwargs):return self.harness.run(value,**kwargs)

    def test_effective_environment_runtime_settings_and_host_canaries(self):
        # These invented canaries exist on the test host, never in image/input.
        with tempfile.TemporaryDirectory(prefix='wealth-ledger-source-host-') as temporary:
            canary=Path(temporary)/'source-host-canary';canary.write_text('invented canary only')
            sock=socket.socket(socket.AF_UNIX);sock.bind(str(Path(temporary)/'source-host.sock'));self.addCleanup(sock.close)
            with patch.dict(os.environ,{'SOURCE_TEST_HOST_SECRET':'invented host marker'}):
                value=self.run_child({'operation':'inspect'})
            self.assertEqual(value['outcome'],'ok');info=value['result']['value'];config=value['configuration'];host=config['HostConfig']
            self.assertEqual((info['uid'],info['gid']),(10001,10001));self.assertEqual(info['environment'],EXPECTED_ENV)
            self.assertEqual((info['cpu'],info['nofile'],info['core']),([2,2],[64,64],[0,0]));self.assertFalse(info['sockets_present'])
            self.assertEqual(host['NetworkMode'],'none');self.assertEqual(host['IpcMode'],'none');self.assertTrue(host['ReadonlyRootfs'])
            self.assertFalse(host['Privileged']);self.assertEqual(host['CapDrop'],['ALL']);self.assertIn('no-new-privileges',host['SecurityOpt'])
            self.assertEqual((host['Memory'],host['MemorySwap'],host['NanoCpus'],host['PidsLimit']),(268435456,268435456,1000000000,16))
            self.assertFalse(config['Mounts']);self.assertFalse(host.get('Binds'));self.assertFalse(host.get('VolumesFrom'))
            self.assertEqual(host['Tmpfs'],{'/tmp':'rw,noexec,nosuid,nodev,size=33554432,uid=10001,gid=10001'})
            for probe in ('files','network','readonly','pids'):
                with self.subTest(probe=probe):
                    frame={'operation':'probe','probe':probe}
                    if probe=='files':frame['paths']=[str(canary),str(Path(temporary)/'source-host.sock')]
                    value=self.run_child(frame);self.assertEqual(value['outcome'],'ok');result=value['result']['value']
                    if probe=='files':self.assertEqual(result,{'host_denied':[True,True],'absent':[True]*4,'data_entries':[]})
                    elif probe=='network':self.assertEqual(result['denied'],[True,True]);self.assertIn([1,'lo'],result['interfaces']);self.assertEqual(result['ipv4_routes'],[])
                    elif probe=='readonly':self.assertEqual(result,{'blocked':[True]*3,'tmp_writable':True})
                    else:self.assertTrue(result['limited']);self.assertLess(result['children'],16)

    def test_bounded_resource_exits_output_precedence_and_cleanup(self):
        for probe,expected in (('memory','resource_exit'),('cpu','resource_exit'),('stdout','output_limit'),('stderr','output_limit'),('sleep','wall_limit'),('descendant','cancelled')):
            with self.subTest(probe=probe):
                value=self.run_child({'operation':'probe','probe':probe},cancel_after=.2 if probe=='descendant' else None)
                self.assertEqual(value['outcome'],expected);record=value['record'];self.assertTrue(record['removed_observed'])
                self.assertLess(record['execution_seconds'],13);self.assertLessEqual(record['stdout_bytes_retained'],8*1024*1024);self.assertLessEqual(record['stderr_bytes_retained'],64*1024)
                if expected in {'wall_limit','cancelled','output_limit'}:self.assertIsNotNone(record['kill_monotonic'])

    def test_closed_framing_and_malformed_output(self):
        for value in (b'{',{'operation':'unreviewed'},{'operation':'inspect','extra':'x'},
            {'operation':'normalize','provider':'wealthsimple','format_version':'x','context_base64':'!!!!','raw_base64':'eA=='}):
            self.assertEqual(self.run_child(value)['outcome'],'frame_rejected')
        self.assertEqual(self.run_child({'operation':'malformed_output'})['outcome'],'malformed_output')
        with self.assertRaises(ValueError):self.run_child(b'x'*(16*1024*1024+1))

    def test_actual_builtin_normalization_preserves_frozen_archive_bytes(self):
        from test_domain_bridge_v1 import WS_RAW,WS_ARCHIVE,BULL_RAW,BULL_ARCHIVE
        from wealth_ledger import source_v2
        for raw,archive in ((WS_RAW,WS_ARCHIVE),(BULL_RAW,BULL_ARCHIVE)):
            batch=source_v2.decode_batch(archive,raw)
            context={'context_version':1,'payload_kind':'parser_v2','context':s.primitive(s.ParserBinding('parser2_context_v1',batch.evidence.context))}
            frame={'operation':'normalize','provider':batch.adapter.provider_id,'format_version':batch.export_version,
                'raw_base64':base64.b64encode(raw).decode(),'context_base64':base64.b64encode(s.canonical(context)).decode()}
            result=self.run_child(frame);self.assertEqual(result['outcome'],'ok')
            self.assertEqual(base64.b64decode(result['result']['payload_base64']),archive)
            self.assertNotIn('realm',context);self.assertNotIn('fingerprint',context)

    def test_offline_file_and_api_semantic_parity_and_nonbooking_admission(self):
        from test_source_transport import direct_case
        from wealth_ledger.domain.validation_v1 import decode_domain_v1
        raw=b'{"btc_received":"0.01000000","cad_paid":"700.00"}'
        _,original,_=direct_case();outputs=[]
        for transport,operation in (('FILE_IMPORT','fake_file'),('PULL_API','fake_api')):
            connection=replace(original.connection,kind=transport)
            descriptor=replace(original.installation_descriptor,capabilities=(transport,),execution_profile='reviewed-file-v1' if transport=='FILE_IMPORT' else 'contract-api-v1')
            context=replace(original,connection=connection,connection_version=s.digest(s.primitive(connection)),transport=transport,
                installation_descriptor=descriptor,installation_id=s.installation_id(descriptor),
                binding_context=replace(original.binding_context,value=replace(original.binding_context.value,connection=connection)),
                expected_provenance=replace(original.expected_provenance,raw_sha256=hashlib.sha256(raw).hexdigest()))
            result=self.run_child({'operation':operation,'raw_base64':base64.b64encode(raw).decode(),
                'context_base64':base64.b64encode(s.canonical(s.adapter_input(context))).decode()})
            self.assertEqual(result['outcome'],'ok');payload=base64.b64decode(result['result']['payload_base64'])
            batch=decode_domain_v1(payload);outputs.append(batch)
            admission=validate_transport(raw,s.context_bytes(context),make_envelope(payload,context))
            self.assertEqual((admission.status,admission.ingestible),('VALID_SHAPE',False))
            self.assertEqual(batch.connections[0].kind,transport)
        self.assertEqual(outputs[0].activities,outputs[1].activities);self.assertEqual(outputs[0].coverage,outputs[1].coverage)
        self.assertEqual(tuple(x.quantity.token for x in outputs[0].activities[0].legs),('-700.00','0.01000000'))
