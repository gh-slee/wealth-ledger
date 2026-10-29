"""Closed synthetic worker, accessible only from the opt-in native test image."""
import base64
import binascii
import json
import os
import resource
import socket
import sys
import time

from wealth_ledger.data_sources import contract_v1 as s

OPERATIONS=frozenset({'normalize','fake_file','fake_api','inspect','probe','malformed_output'})
PROBES=frozenset({'network','files','readonly','pids','memory','cpu','stdout','stderr','sleep','descendant'})


def emit(value):
    sys.stdout.buffer.write(s.canonical(value));sys.stdout.buffer.flush()


def unpack(value,limit):
    if type(value) is not str or len(value)>4*((limit+2)//3):raise ValueError('Invalid frame')
    raw=base64.b64decode(value,validate=True)
    if not raw or len(raw)>limit or base64.b64encode(raw).decode()!=value:raise ValueError('Invalid frame')
    return raw


def inspect():
    return {'uid':os.getuid(),'gid':os.getgid(),'environment':dict(os.environ),
        'cpu':list(resource.getrlimit(resource.RLIMIT_CPU)),'nofile':list(resource.getrlimit(resource.RLIMIT_NOFILE)),
        'core':list(resource.getrlimit(resource.RLIMIT_CORE)),
        'sockets_present':any(os.path.exists(p) for p in ('/var/run/docker.sock','/run/postgresql/.s.PGSQL.5432'))}


def probe(name,paths=None):
    if name not in PROBES:raise ValueError('Invalid probe')
    if name=='network':
        denied=[]
        for target in [('192.0.2.1',443),('127.0.0.1',5432)]:
            sock=socket.socket();sock.settimeout(.25)
            try:sock.connect(target);denied.append(False)
            except OSError:denied.append(True)
            finally:sock.close()
        return {'denied':denied,'interfaces':[list(value) for value in socket.if_nameindex()],
                'ipv4_routes':open('/proc/net/route').read().splitlines()[1:]}
    if name=='files':
        if type(paths) is not list or len(paths)!=2 or any(type(p) is not str or len(p)>1024 or 'wealth-ledger-source-host-' not in p for p in paths):raise ValueError('Invalid invented host paths')
        denied=[]
        try:
            with open(paths[0],'rb'):denied.append(False)
        except OSError:denied.append(True)
        sock=socket.socket(socket.AF_UNIX)
        try:sock.connect(paths[1]);denied.append(False)
        except OSError:denied.append(True)
        finally:sock.close()
        return {'host_denied':denied,'absent':[not os.path.exists(p) for p in ('/tmp/source-host-canary','/tmp/source-host.sock','/run/secrets/source-test','/var/run/docker.sock')],
                'data_entries':os.listdir('/data')}
    if name=='readonly':
        blocked=[]
        for name in ('/data/source-test','/app/source-test','/opt/source-test/source-test'):
            try:
                with open(name,'xb') as stream:stream.write(b'invented')
                blocked.append(False)
            except OSError:blocked.append(True)
        with open('/tmp/allowed','xb') as stream:stream.write(b'invented')
        return {'blocked':blocked,'tmp_writable':True}
    if name=='pids':
        children=[]
        try:
            for _ in range(64):
                pid=os.fork()
                if pid==0:time.sleep(30);os._exit(0)
                children.append(pid)
        except OSError:return {'limited':True,'children':len(children)}
        finally:
            for pid in children:
                os.kill(pid,9);os.waitpid(pid,0)
        return {'limited':False}
    if name=='memory':
        held=[]
        while True:held.append(bytearray(8*1024*1024))
    if name=='cpu':
        while True:pass
    if name in {'stdout','stderr'}:
        stream=sys.stdout.buffer if name=='stdout' else sys.stderr.buffer
        while True:stream.write(b'x'*8192);stream.flush()
    if name=='descendant':
        if os.fork()==0:
            time.sleep(30);os._exit(0)
    time.sleep(30)
    return {'unexpected_completion':True}


def main():
    raw=sys.stdin.buffer.read(16*1024*1024+1)
    if len(raw)>16*1024*1024:raise ValueError('Frame exceeds limit')
    value=s.load_json(raw,limit=16*1024*1024)
    if type(value) is not dict or value.get('operation') not in OPERATIONS or s.canonical(value)!=raw:
        raise ValueError('Invalid closed frame')
    operation=value['operation']
    if operation in {'inspect','malformed_output'}:
        if set(value)!={'operation'}:raise ValueError('Extra fields')
        if operation=='malformed_output':sys.stdout.buffer.write(b'not-json');return
        emit({'ok':True,'value':inspect()});return
    if operation=='probe':
        if set(value)!=({'operation','probe','paths'} if value.get('probe')=='files' else {'operation','probe'}):raise ValueError('Extra fields')
        emit({'ok':True,'value':probe(value['probe'],value.get('paths'))});return
    expected={'operation','raw_base64','context_base64'}|({'provider','format_version'} if operation=='normalize' else set())
    if set(value)!=expected:raise ValueError('Extra fields')
    source=unpack(value['raw_base64'],s.MAX_RAW)
    context=s.load_json(unpack(value['context_base64'],s.MAX_CONTEXT),limit=s.MAX_CONTEXT)
    if operation=='normalize':
        if set(context)!={'context_version','payload_kind','context'} or context['context_version']!=1 or context['payload_kind']!='parser_v2':raise ValueError('Invalid minimal parser context')
        binding=s.decode(s.ParserBinding,context['context'])
        from wealth_ledger.source_builtin import WealthsimpleHoldings,BullBitcoinOrders
        from wealth_ledger.source_v2 import canonical_json
        factories={'wealthsimple':WealthsimpleHoldings,'bullbitcoin':BullBitcoinOrders}
        if value['provider'] not in factories:raise ValueError('Unknown fixed provider')
        batch=factories[value['provider']]().normalize(source,export_version=value['format_version'],context=binding.value)
        payload=canonical_json(batch).encode()
    else:
        from fake_api import normalize
        payload=normalize(source,context,transport='FILE_IMPORT' if operation=='fake_file' else 'PULL_API')
    if len(payload)>s.MAX_PAYLOAD:raise ValueError('Payload exceeds limit')
    emit({'ok':True,'payload_base64':base64.b64encode(payload).decode()})


if __name__=='__main__':
    try:main()
    except (ValueError,TypeError,KeyError,binascii.Error):
        emit({'ok':False,'code':'test_frame_invalid'})
