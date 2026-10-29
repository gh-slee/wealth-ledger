"""Linux native HTTP/process races in the explicit source-only optional runtime image."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import unittest

from test_identity_support import IdentityCase
from wealth_ledger.web_v2.auth import digest

# Test-only wrappers coordinate real hashing BEFORE SQL acquisition. No production
# route/header/environment bypass, forged forwarded peer or host alias is used.
PROGRAM=r'''
import concurrent.futures,hashlib,http.client,json,multiprocessing as mp,os,queue,socket,sys,time
from http.cookies import SimpleCookie
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.web_v2.config import Settings
from wealth_ledger.web_v2.api import create_app
import uvicorn
payload=json.load(sys.stdin)
context=mp.get_context('fork');results=context.Queue();barrier=context.Barrier(16);hash_slots=context.BoundedSemaphore(2)
def server(index,listener):
 try:
  port=listener.getsockname()[1];origin='http://127.0.0.1:'+str(port)
  settings=Settings(PostgresConfig(payload['identity'],1),PostgresConfig(payload['financial'],1),bytes.fromhex(payload['key']),origin)
  app=create_app(settings);auth=app.state.auth
  if payload['mode']!='users':
   original_hash=auth.passwords.hash
   def hashed(value):
    with hash_slots:return original_hash(value)
   auth.passwords.hash=hashed
   original_call=auth.store.call
   def call(name,*args,**kwargs):
    if name in {'register_commit_v1','bootstrap_commit_v1'}:barrier.wait(timeout=90)
    return original_call(name,*args,**kwargs)
   auth.store.call=call
   original_provision=auth.provision
   def provision(token,body,peer,**kwargs):
    results.put({'transport_peer':peer,'pid':os.getpid()})
    return original_provision(token,body,peer,**kwargs)
   auth.provision=provision
  results.put({'ready':index,'pid':os.getpid(),'port':port})
  uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,proxy_headers=False,access_log=False,log_level='critical')).run(sockets=[listener])
 except BaseException:
  results.put({'startup_failed':index});raise
count=1 if payload['mode']=='users' else 16
children=[];ports=[];records=[]
try:
 # Bound startup hashing as well; each child signals only after actual activation.
 for index in range(count):
  listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
  ports.append(listener.getsockname()[1]);process=context.Process(target=server,args=(index,listener));process.start();children.append(process);listener.close()
  record=results.get(timeout=30);records.append(record)
  if 'ready' not in record:raise RuntimeError('Synthetic native startup failed')
 def exchange(index,mode,username=None):
  port=ports[index if mode!='users' else 0];peer='127.0.0.'+str(index+2);origin='http://127.0.0.1:'+str(port)
  cookie=None
  def request(method,path,body=None,csrf=None):
   nonlocal cookie
   connection=http.client.HTTPConnection('127.0.0.1',port,timeout=120,source_address=(peer,0))
   headers={}
   if cookie:headers['Cookie']=cookie
   raw=None
   if body is not None:
    raw=json.dumps(body).encode();headers.update({'Content-Type':'application/json','Origin':origin,'X-CSRF-Token':csrf})
   connection.request(method,path,body=raw,headers=headers)
   response=connection.getresponse();data=response.read()
   for key,value in response.getheaders():
    if key.lower()=='set-cookie':
     parsed=SimpleCookie();parsed.load(value)
     if 'wealth_v2_session' in parsed:cookie='wealth_v2_session='+parsed['wealth_v2_session'].value
   status=response.status;connection.close()
   return status,json.loads(data) if data else None
  # Server socket readiness is bounded separately from application activation.
  deadline=time.monotonic()+10
  while True:
   try:status,csrf=request('GET','/api/v2/auth/csrf');break
   except OSError:
    if time.monotonic()>=deadline:raise
    time.sleep(.02)
  if status!=200:raise RuntimeError('Synthetic CSRF failed')
  if mode=='users':
   status,value=request('POST','/api/v2/auth/login',{'username':username,'password':payload['password']},csrf['csrf_token'])
   if status!=200:raise RuntimeError('Synthetic login failed')
   status,me=request('GET','/api/v2/me')
   own,own_value=request('GET','/api/v2/candidate-batches/'+payload['shared_id'])
   foreign,foreign_value=request('GET','/api/v2/candidate-batches/'+payload['foreign_id'])
   return {'login':True,'me_status':status,'user_id':me['user']['id'],'own_status':own,
           'own_digest':hashlib.sha256(json.dumps(own_value,separators=(',',':'),sort_keys=True).encode()).hexdigest(),
           'foreign_status':foreign}
  key='setup_token' if mode=='setup' else 'invite_token'
  status,value=request('POST','/api/v2/auth/'+('setup' if mode=='setup' else 'register'),
                       {key:payload['code'],'username':'NativeRace'+str(index),'password':payload['password']},csrf['csrf_token'])
  return {'status':status,'code':value.get('error',{}).get('code')}
 if payload['mode']=='users':
  responses=[exchange(i,'users',name) for i,name in enumerate(payload['users'])]
 else:
  with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
   responses=list(pool.map(lambda i:exchange(i,payload['mode']),range(16)))
  for _ in range(16):records.append(results.get(timeout=5))
 print(json.dumps({'responses':responses,'records':records,'processes':len(children),'linux':sys.platform=='linux','nonroot':os.getuid()!=0}))
finally:
 for child in children:
  child.terminate();child.join(timeout=5)
  if child.is_alive():child.kill();child.join(timeout=5)
'''


@unittest.skipUnless(os.environ.get('WEALTH_LEDGER_IDENTITY_RUNTIME_IMAGE'),'Explicit optional identity runtime image acceptance')
class IdentityNativeImage(IdentityCase):
    def image(self,payload):
        from psycopg.conninfo import make_conninfo
        base={'identity':make_conninfo(self.configs['identity'].conninfo,host=self.config['container'],port=5432),
              'financial':make_conninfo(self.configs['runtime'].conninfo,host=self.config['container'],port=5432),
              'key':self.key.hex(),'password':self.password,**payload}
        result=subprocess.run(['docker','run','--rm','-i','--network',self.config['network'],'--entrypoint','python',
                               os.environ['WEALTH_LEDGER_IDENTITY_RUNTIME_IMAGE'],'-c',PROGRAM],
                              input=json.dumps(base).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
        # Do not publish tracebacks that could contain synthetic credential payloads.
        self.assertEqual(result.returncode,0,'Native identity image failed; inspect private bounded logs')
        value=json.loads(result.stdout);self.assertTrue(value['linux']);self.assertTrue(value['nonroot'])
        return value

    def race(self,setup):
        code=secrets.token_urlsafe(32)
        if not setup:self.bootstrap()
        self.operator.call('arm_setup_v1' if setup else 'issue_invite_v1',digest(code))
        value=self.image({'mode':'setup' if setup else 'register','code':code})
        statuses=[r['status'] for r in value['responses']]
        self.assertEqual(statuses.count(201),1,value['responses'])
        self.assertEqual(statuses.count(409 if setup else 400),15,value['responses'])
        codes=[r['code'] for r in value['responses'] if r['status']!=201]
        self.assertEqual(codes,['setup_closed' if setup else 'registration_rejected']*15)
        peers=[r['transport_peer'] for r in value['records'] if 'transport_peer' in r]
        self.assertEqual(set(peers),{'127.0.0.'+str(i) for i in range(2,18)})
        self.assertEqual(len({r['pid'] for r in value['records']}),16)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_identity.users'),1 if setup else 2)

    def test_native_sixteen_first_setup_http_race(self):self.race(True)
    def test_native_sixteen_invitation_http_race(self):self.race(False)

    def test_optional_nonroot_two_user_http_financial_isolation(self):
        import hashlib
        import uuid
        from wealth_ledger.domain.validation_v1 import decode_domain_v1
        from wealth_ledger.persistence.repositories import Candidates
        _,a=self.bootstrap();_,b=self.member();shared=str(uuid.uuid4());foreign=str(uuid.uuid4())
        original=(Path(__file__).parent/'fixtures/postgres_foundation/golden.json').read_bytes();template=decode_domain_v1(original)
        expected={}
        for user in [a,b]:
            raw=original.replace(template.tenant_id.encode(),user.user_id.encode()).replace(template.portfolio_id.encode(),user.portfolio_id.encode())
            expected[user.user_id]=hashlib.sha256(json.dumps(json.loads(raw),separators=(',',':'),sort_keys=True).encode()).hexdigest()
            Candidates(self.financial).put(user.context,shared,decode_domain_v1(raw),expected_generation=0,idempotency_key='native-shared-candidate')
            if user==b:Candidates(self.financial).put(user.context,foreign,decode_domain_v1(raw),expected_generation=1,idempotency_key='native-foreign-candidate')
        value=self.image({'mode':'users','users':['AdminExample','MemberExample'],'shared_id':shared,'foreign_id':foreign})
        self.assertEqual({r['user_id'] for r in value['responses']},{a.user_id,b.user_id})
        for result in value['responses']:
            self.assertEqual(result['me_status'],200);self.assertEqual(result['own_status'],200)
            self.assertEqual(result['own_digest'],expected[result['user_id']])
            self.assertEqual(result['foreign_status'],404 if result['user_id']==a.user_id else 200)


# Two independent, real ASGI processes share only the checked SQL budget state.
# No patched budget helper, forwarded peer or production route/header is used.
SOURCE_PROGRAM=r'''
import http.client,json,multiprocessing as mp,os,socket,sys,time
import uvicorn
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.web_v2.config import Settings
from wealth_ledger.web_v2.api import create_app
from wealth_ledger.data_sources.catalog_v1 import decode_catalog
from wealth_ledger.data_sources.contract_v1 import canonical
payload=json.load(sys.stdin);context=mp.get_context('fork');children=[];ports=[];ready=context.Queue()
def server(listener):
 port=listener.getsockname()[1]
 app=create_app(Settings(PostgresConfig(payload['identity'],1),PostgresConfig(payload['financial'],1),bytes.fromhex(payload['key']),
     'http://127.0.0.1:'+str(port),schema_profile='sources',source_catalog=decode_catalog(canonical(payload['catalog']))))
 ready.put(os.getpid())
 uvicorn.Server(uvicorn.Config(app,proxy_headers=False,access_log=False,log_level='critical')).run(sockets=[listener])
try:
 pids=[]
 for _ in range(2):
  listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128);ports.append(listener.getsockname()[1])
  child=context.Process(target=server,args=(listener,));child.start();children.append(child);listener.close();pids.append(ready.get(timeout=30))
 def request(index,path):
  connection=http.client.HTTPConnection('127.0.0.1',ports[index],timeout=10)
  try:
   connection.request('GET',path,headers={'Cookie':'wealth_v2_session='+payload['token']})
   response=connection.getresponse();raw=response.read();return response.status,json.loads(raw)
  finally:connection.close()
 for index in range(2):
  deadline=time.monotonic()+10
  while True:
   try:
    status,_=request(index,'/api/v2/me')
    if status!=200:raise RuntimeError('Synthetic login failed')
    break
   except OSError:
    if time.monotonic()>=deadline:raise
    time.sleep(.02)
 statuses=[]
 for index in range(61):
  status,value=request(index%2,'/api/v2/sources');statuses.append(status)
 print(json.dumps({'statuses':statuses,'last_code':value.get('error',{}).get('code'),'process_count':len(set(pids)),
                   'linux':sys.platform=='linux','nonroot':os.getuid()==10001}))
finally:
 for child in children:
  child.terminate();child.join(timeout=5)
  if child.is_alive():child.kill();child.join(timeout=5)
'''


from test_source_lifecycle import ConfiguredSourceCase,CONTENT_ENABLED


@unittest.skipUnless(CONTENT_ENABLED and os.environ.get('WEALTH_LEDGER_SOURCE_HARNESS_BASE_IMAGE'),
                     'Explicit native source image and content proofs required')
class SourceNativeImage(ConfiguredSourceCase):
    def test_two_native_http_processes_share_actual_database_source_read_budget(self):
        from psycopg.conninfo import make_conninfo
        from wealth_ledger.data_sources.contract_v1 import primitive
        import re
        token,principal=self.bootstrap()
        image=os.environ['WEALTH_LEDGER_SOURCE_HARNESS_BASE_IMAGE']
        self.assertRegex(image,r'^sha256:[0-9a-f]{64}$')
        payload={'identity':make_conninfo(self.configs['identity'].conninfo,host=self.config['container'],port=5432),
            'financial':make_conninfo(self.configs['runtime'].conninfo,host=self.config['container'],port=5432),
            'key':self.key.hex(),'token':token,'catalog':primitive(self.catalog)}
        name='wealth-ledger-source-http-'+__import__('uuid').uuid4().hex
        process=None;owned=False
        try:
            # This integration container intentionally joins ONLY the separately
            # marked synthetic PG network. It is not the network-none parser child.
            created=subprocess.run(['docker','create','--name',name,'--label','wealth-ledger.test=source-http','-i',
                '--network',self.config['network'],'--user','10001:10001','--read-only','--cap-drop','ALL',
                '--security-opt','no-new-privileges','--entrypoint','python',image,'-c',SOURCE_PROGRAM],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            self.assertEqual(created.returncode,0,'Synthetic native source container creation failed');owned=True
            process=subprocess.Popen(['docker','start','--attach','--interactive',name],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            stdout,stderr=process.communicate(json.dumps(payload).encode(),timeout=90)
            Path('work').mkdir(exist_ok=True)
            # Diagnostics stay ignored/private and bounded; stdout contains only
            # counts/status codes, never the input's generated credentials.
            diagnostic=Path('work')/(name+'.stderr')
            descriptor=os.open(diagnostic,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'wb') as stream:stream.write(stderr[:65536])
            self.assertEqual(process.returncode,0,'Native source HTTP failed; inspect private bounded stderr')
            value=json.loads(stdout);self.assertTrue(value['linux']);self.assertTrue(value['nonroot'])
            self.assertEqual(value['process_count'],2);self.assertEqual(value['statuses'],[200]*60+[429])
            self.assertEqual(value['last_code'],'rate_limited')
        finally:
            if owned:subprocess.run(['docker','rm','--force',name],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=10)
            if process and process.poll() is None:process.kill();process.wait(timeout=5)
