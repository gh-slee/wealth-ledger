"""Actual ASGI HTTP contracts on private synthetic PostgreSQL targets."""
import asyncio
import json
from pathlib import Path
import secrets
import time
from unittest.mock import patch
import uuid

from test_identity_support import IdentityCase
from wealth_ledger.web_v2.auth import digest
from wealth_ledger.persistence.identity import IdentityError


class IdentityHttp(IdentityCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from wealth_ledger.web_v2.api import create_app
        from wealth_ledger.web_v2.config import Settings
        self.app=create_app(Settings(self.configs['identity'],self.configs['runtime'],self.key,'http://localhost'))
        self.client=TestClient(self.app,base_url='http://localhost')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)

    def csrf(self,client=None):
        client=client or self.client
        response=client.get('/api/v2/auth/csrf')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['csrf_token']

    def post(self,path,body,csrf=None,**kwargs):
        return self.client.post(path,json=body,headers={'Origin':'http://localhost','X-CSRF-Token':csrf or self.csrf()},**kwargs)

    def logged_in(self):
        self.bootstrap()
        response=self.post('/api/v2/auth/login',{'username':'AdminExample','password':self.password})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['csrf_token']

    def test_http_setup_no_auto_login_and_admin_member_scope(self):
        code=secrets.token_urlsafe(32);self.operator.call('arm_setup_v1',digest(code))
        response=self.post('/api/v2/auth/setup',{'setup_token':code,'username':'ChosenAdmin','password':self.password})
        self.assertEqual(response.status_code,201,response.text);self.assertEqual(response.json(),{'initialized':True})
        self.assertEqual(self.client.get('/api/v2/me').status_code,401)
        login=self.post('/api/v2/auth/login',{'username':'ChosenAdmin','password':self.password})
        self.assertEqual(login.status_code,200,login.text)
        me=self.client.get('/api/v2/me').json();self.assertEqual(me['user']['role'],'instance_admin')
        self.assertEqual(set(me),{'authenticated','user','portfolio'})
        issue_request=str(uuid.uuid4())
        issued=self.post('/api/v2/admin/invitations',{'issue_request_id':issue_request},login.json()['csrf_token'])
        self.assertEqual(issued.status_code,201,issued.text)
        token=issued.json()['invite_token'];self.assertEqual(len(token),43)
        listed=self.client.get('/api/v2/admin/invitations',params={'issue_request_id':issue_request})
        self.assertEqual(listed.status_code,200,listed.text);self.assertNotIn(token,listed.text)
        repeat=self.post('/api/v2/admin/invitations',{'issue_request_id':issue_request},login.json()['csrf_token'])
        self.assertEqual(repeat.status_code,409);self.assertNotIn(token,repeat.text)
        from fastapi.testclient import TestClient
        with TestClient(self.app,base_url='http://localhost',client=('127.0.0.2',1234)) as member:
            csrf=self.csrf(member)
            response=member.post('/api/v2/auth/register',json={'invite_token':token,'username':'NewMember','password':self.password},headers={'Origin':'http://localhost','X-CSRF-Token':csrf})
            self.assertEqual(response.status_code,201,response.text)
            self.assertEqual(member.get('/api/v2/me').status_code,401)
            csrf=self.csrf(member)
            login=member.post('/api/v2/auth/login',json={'username':'newmember','password':self.password},headers={'Origin':'http://localhost','X-CSRF-Token':csrf})
            self.assertEqual(login.status_code,200,login.text)
            self.assertEqual(member.get('/api/v2/admin/invitations?unknown=1').status_code,403)
            self.assertEqual(member.get('/api/v2/me').json()['user']['role'],'member')

    def test_wrong_unknown_disabled_quarantined_passwords_are_uniform_one_verify(self):
        token,principal=self.bootstrap()
        checks=[]
        original=self.app.state.auth.passwords.verify
        def verify(encoded,password):
            checks.append(1)
            return original(encoded,password)
        def request(username,password):
            response=self.post('/api/v2/auth/login',{'username':username,'password':password})
            self.assertEqual(response.status_code,401,response.text)
            value=response.json();value['error']['request_id']='normalized'
            return value
        with patch.object(self.app.state.auth.passwords,'verify',side_effect=verify):
            expected=request('AdminExample','wrong')
            self.assertEqual(request('NotAUser','wrong'),expected)
            self.operator.call('set_user_enabled_v1',principal.user_id,False)
            self.assertEqual(request('AdminExample',self.password),expected)
            self.operator.call('set_user_enabled_v1',principal.user_id,True)
            self.sql('UPDATE wl_identity.users SET credential_epoch=credential_epoch+1 WHERE id=:id',id=principal.user_id)
            self.assertEqual(request('AdminExample',self.password),expected)
        self.assertEqual(len(checks),4)
        self.assertEqual(expected['error']['message'],'Invalid credentials')
        self.assertEqual(self.scalar("SELECT count(*) FROM wl_identity.sessions WHERE kind='authenticated'"),1)

    def test_origin_csrf_headers_json_and_unknown_route_precedence(self):
        csrf=self.csrf()
        body={'username':'Unknown','password':'x'}
        wrong=self.client.post('/api/v2/auth/login',json=body,headers={'Origin':'http://other.test','X-CSRF-Token':csrf})
        self.assertEqual(wrong.status_code,403);self.assertEqual(wrong.json()['error']['code'],'origin_rejected')
        wrong=self.post('/api/v2/auth/login',body,'a'*64)
        self.assertEqual(wrong.status_code,403);self.assertEqual(wrong.json()['error']['code'],'csrf_rejected')
        self.assertIn('wealth_v2_session',self.client.cookies)
        for path,status in [('/api/v1/me',404),('/docs',404),('/openapi.json',404),('/api/v2/auth/login',405)]:
            self.assertEqual(self.client.get(path).status_code,status)
        headers={'Origin':'http://localhost','X-CSRF-Token':csrf,'Content-Type':'application/json'}
        for raw in [b'{"username":"x","username":"y","password":"x"}',b'[]',b'{"x":NaN}',b'\xff',b'{}']:
            response=self.client.post('/api/v2/auth/login',content=raw,headers=headers)
            self.assertEqual(response.status_code,422,response.text)
            self.assertNotIn(raw.decode('latin1'),response.text) if len(raw)>10 else None
        response=self.client.post('/api/v2/auth/login',content=b' ' *16385,headers=headers)
        self.assertEqual(response.status_code,413)
        self.assertEqual(self.client.post('/api/v2/auth/login',content='{}',headers={**headers,'Content-Type':'text/plain'}).status_code,415)
        self.assertEqual(self.client.get('/api/v2/me',headers=[('Host','localhost'),('Host','localhost')]).status_code,400)
        self.assertEqual(self.client.get('/api/v2/me',headers={'Cookie':'wealth_v2_session=a; wealth_v2_session=b'}).status_code,400)
        self.assertEqual(self.client.get('/api/v2/me',headers={'Host':'other.test'}).status_code,400)

    def test_candidate_and_job_own_shared_foreign_and_missing(self):
        from wealth_ledger.domain.validation_v1 import decode_domain_v1
        from wealth_ledger.persistence.repositories import Candidates
        from wealth_ledger.persistence.jobs import Jobs
        token,a=self.bootstrap();_,b=self.member()
        original=(Path(__file__).parent/'fixtures/postgres_foundation/golden.json').read_bytes()
        base=decode_domain_v1(original);shared=str(uuid.uuid4());foreign=str(uuid.uuid4())
        expected={}
        for principal in [a,b]:
            raw=original.replace(base.tenant_id.encode(),principal.user_id.encode()).replace(base.portfolio_id.encode(),principal.portfolio_id.encode())
            expected[principal.user_id]=raw
            Candidates(self.financial).put(principal.context,shared,decode_domain_v1(raw),expected_generation=0,idempotency_key='shared-example')
        Candidates(self.financial).put(b.context,foreign,decode_domain_v1(expected[b.user_id]),expected_generation=1,idempotency_key='foreign-example')
        job=Jobs(self.financial).enqueue(a.context,'own-job-example',{'resource_id':shared,'version':'1'},expected_generation=1)
        self.client.cookies.set('wealth_v2_session',token)
        response=self.client.get('/api/v2/candidate-batches/'+shared,headers={'X-Tenant':b.user_id,'X-Portfolio':b.portfolio_id})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.content,expected[a.user_id])
        errors=[]
        for record in [foreign,str(uuid.uuid4())]:
            r=self.client.get('/api/v2/candidate-batches/'+record);self.assertEqual(r.status_code,404,r.text)
            value=r.json();value['error']['request_id']='normalized';errors.append(value)
        self.assertEqual(*errors)
        response=self.client.get('/api/v2/jobs/'+job)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(set(response.json()),{'id','kind','status','attempt','error_code'})
        self.assertEqual(self.client.get('/api/v2/jobs/'+job+'?tenant_id='+b.user_id).status_code,422)
        self.assertEqual(self.client.get('/api/v2/jobs/BAD').status_code,422)
        schema=self.client.get('/api/v2/openapi.json')
        self.assertEqual(schema.status_code,200)
        self.assertIn('Login',schema.json()['components']['schemas'])

    def test_password_wrong_current_no_replacement_hash_and_logout_zero_body(self):
        csrf=self.logged_in()
        with patch.object(self.app.state.auth.passwords,'hash',wraps=self.app.state.auth.passwords.hash) as hashed:
            response=self.post('/api/v2/auth/password',{'current_password':'wrong','new_password':'New synthetic password 123'},csrf)
            self.assertEqual(response.status_code,401,response.text);hashed.assert_not_called()
        response=self.post('/api/v2/auth/activity',{},csrf)
        self.assertEqual(response.status_code,204);self.assertEqual(response.content,b'')
        response=self.post('/api/v2/auth/logout',{},csrf)
        self.assertEqual(response.status_code,204);self.assertEqual(response.content,b'')
        self.assertEqual(self.client.get('/api/v2/me').status_code,401)

    def test_eight_first_body_stalls_release_admission_and_health_lives(self):
        token,a=self.bootstrap();csrf=self.app.state.auth.csrf(token)
        async def run():
            async def invoke(path,method='GET',stall=False):
                messages=[]
                scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'',
                       'method':method,'headers':[(b'host',b'localhost'),(b'origin',b'http://localhost'),(b'cookie',('wealth_v2_session='+token).encode()),
                       (b'x-csrf-token',csrf.encode()),(b'content-type',b'application/json')],'server':('localhost',80),'client':('127.0.0.1',1234)}
                async def receive():
                    if stall:await asyncio.Event().wait()
                    return {'type':'http.request','body':b'{}','more_body':False}
                async def send(message):messages.append(message)
                await self.app(scope,receive,send)
                return next(m['status'] for m in messages if m['type']=='http.response.start')
            tasks=[asyncio.create_task(invoke('/api/v2/auth/activity','POST',True)) for _ in range(8)]
            await asyncio.sleep(.25)
            start=time.monotonic();self.assertEqual(await invoke('/healthz'),200)
            self.assertLess(time.monotonic()-start,1)
            self.assertEqual(await invoke('/api/v2/me'),429)
            self.assertEqual(await asyncio.wait_for(asyncio.gather(*tasks),13),[408]*8)
            await asyncio.sleep(0)
            self.assertEqual(await invoke('/api/v2/me'),200)
        asyncio.run(run())
        self.assertEqual(self.scalar("SELECT count(*) FROM wl_identity.auth_audit WHERE action='password_changed'"),0)
