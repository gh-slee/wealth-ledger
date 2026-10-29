"""Opt-in identity API, isolated from legacy routes, workspaces and static files."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import re
import time
from urllib.parse import parse_qsl
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from starlette.responses import JSONResponse

from .auth import Auth, RequestError, TOKEN, HEX, digest
from . import schemas as s
from wealth_ledger.persistence.identity import IdentityError
from wealth_ledger.data_sources.lifecycle_v1 import SourceError
from wealth_ledger.domain.canonical_v1 import DomainBatchV1

SECURITY_HEADERS = {'Cache-Control':'no-store, private', 'Pragma':'no-cache',
 'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer',
 'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'", 'X-Frame-Options':'DENY'}
ROUTES = {
 '/healthz':('GET',), '/readyz':('GET',), '/api/v2/auth/csrf':('GET',),
 '/api/v2/auth/setup':('POST',), '/api/v2/auth/register':('POST',),
 '/api/v2/auth/login':('POST',), '/api/v2/me':('GET',),
 '/api/v2/auth/activity':('POST',), '/api/v2/auth/logout':('POST',),
 '/api/v2/auth/password':('POST',), '/api/v2/openapi.json':('GET',),
 '/api/v2/admin/invitations':('GET','POST'),
}
DYNAMIC = ((re.compile(r'/api/v2/(candidate-batches|jobs)/[^/]+\Z'),('GET',)),
           (re.compile(r'/api/v2/admin/invitations/[^/]+/revoke\Z'),('POST',)))
SOURCE_ROUTES = {'/api/v2/sources':('GET',),'/api/v2/source-connections':('GET','POST')}
SOURCE_DYNAMIC = ((re.compile(r'/api/v2/sources/[^/]+/capabilities/[^/]+\Z'),('PUT',)),
                  (re.compile(r'/api/v2/source-connections/[^/]+\Z'),('GET','PUT')))
ANONYMOUS = {'/api/v2/auth/login','/api/v2/auth/register','/api/v2/auth/setup'}


def set_cookie(response, settings, token=None, *, authenticated=False):
    response.set_cookie(settings.cookie_name, token or '', max_age=(43200 if authenticated else 600) if token else 0,
                        path='/', secure=settings.secure, httponly=True, samesite='lax')


def error_response(error, request_id, settings, *, language='en-CA'):
    # These generic product translations deliberately share one stable wire code.
    messages = {'en-CA':'Request could not be completed.',
                'zh-TW':'\u7121\u6cd5\u5b8c\u6210\u8acb\u6c42\u3002',
                'zh-CN':'\u65e0\u6cd5\u5b8c\u6210\u8bf7\u6c42\u3002'}
    code = error.code if error.code in s.ERROR_CODES else 'instance_not_ready'
    if code=='invalid_credentials':
        messages={'en-CA':'Invalid credentials','zh-TW':'\u767b\u5165\u8cc7\u6599\u7121\u6548','zh-CN':'\u767b\u5f55\u4fe1\u606f\u65e0\u6548'}
    response = JSONResponse({'error':{'code':code,'message':messages.get(language,messages['en-CA']),
                                     'request_id':request_id}}, status_code=error.status)
    if getattr(error,'clear_cookie',False):
        set_cookie(response,settings)
    return response


def unique_object(pairs):
    value = {}
    for key,item in pairs:
        if key in value:
            raise ValueError()
        value[key] = item
    return value


def query(scope):
    try:
        raw = scope.get('query_string', b'').decode('ascii')
        if re.search(r'%(?![0-9A-Fa-f]{2})',raw):
            raise ValueError()
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, encoding='utf-8', errors='strict')
        if len(pairs) != len(dict(pairs)):
            raise ValueError()
        return dict(pairs)
    except Exception:
        raise RequestError('invalid_input',422) from None


class Boundary:
    """Bound admitted work even when an ASGI caller cancels a blocking operation."""
    def __init__(self, app, *, settings, auth):
        self.app, self.settings, self.auth = app, settings, auth
        self.active = 0
        self.ready_task = None
        self.tasks = set()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope,receive,send)
        entered = time.monotonic()
        request_id = uuid.uuid4().hex
        language = 'en-CA'
        values = [v.decode('latin1') for k,v in scope['headers'] if k.lower()==b'accept-language']
        if len(values)==1:
            first = values[0].split(',')[0].split(';')[0].strip()
            if first in {'zh-TW','zh-CN'}:
                language=first

        scope['identity_language']=language

        async def protected_send(message):
            if message['type']=='http.response.start':
                headers=[(k,v) for k,v in message.get('headers',[]) if k.lower() not in {n.lower().encode() for n in SECURITY_HEADERS}]
                headers.extend((k.encode(),v.encode()) for k,v in SECURITY_HEADERS.items())
                message={**message,'headers':headers}
            await send(message)

        async def run():
            try:
                await self.request(scope,receive,protected_send,entered,request_id)
            except (RequestError,IdentityError,SourceError) as error:
                await error_response(error,request_id,self.settings,language=language)(scope,receive,protected_send)
            except Exception:
                await error_response(RequestError('internal_error',500),request_id,self.settings,language=language)(scope,receive,protected_send)

        if scope.get('path') in {'/healthz','/readyz'}:
            return await run()
        if self.active>=8:
            return await error_response(RequestError('authentication_busy',429),request_id,self.settings)(scope,receive,protected_send)
        self.active+=1
        task=asyncio.create_task(run())
        self.tasks.add(task)
        def finished(done):
            self.active-=1
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        await asyncio.shield(task)

    async def request(self,scope,receive,send,entered,request_id):
        headers={}
        for key,value in scope['headers']:
            headers.setdefault(key.lower(),[]).append(value.decode('latin1'))
        for name in [b'host',b'origin',b'x-csrf-token',b'cookie']:
            if len(headers.get(name,[]))>1:
                raise RequestError('invalid_headers',400)
        host=headers.get(b'host',[''])[0]
        if host.lower()!=self.settings.host:
            raise RequestError('invalid_host',400)
        lengths=headers.get(b'content-length',[])
        if (len(lengths)>1 or lengths and (not re.fullmatch(r'[0-9]{1,10}',lengths[0]) or b'transfer-encoding' in headers)):
            raise RequestError('invalid_length',400)
        cookies=[]
        for segment in headers.get(b'cookie',[''])[0].split(';'):
            name,separator,value=segment.strip().partition('=')
            if name==self.settings.cookie_name and separator:
                cookies.append(value)
        if len(cookies)>1:
            raise RequestError('invalid_headers',400)
        path,method=scope['path'],scope['method']
        methods=ROUTES.get(path)
        if methods is None:
            methods=next((m for pattern,m in DYNAMIC if pattern.fullmatch(path)),None)
        source_request=False
        if methods is None and getattr(self.settings,'schema_profile','identity')=='sources':
            methods=SOURCE_ROUTES.get(path)
            if methods is None:
                methods=next((m for pattern,m in SOURCE_DYNAMIC if pattern.fullmatch(path)),None)
            source_request=methods is not None
        if methods is None:
            raise RequestError('not_found',404)
        if method not in methods:
            response=error_response(RequestError('method_not_allowed',405),request_id,self.settings)
            response.headers['Allow']=', '.join(methods)
            return await response(scope,receive,send)
        if path=='/healthz':
            if query(scope):
                raise RequestError('invalid_input',422)
            return await JSONResponse({'alive':True})(scope,receive,send)
        if path=='/readyz':
            if query(scope):
                raise RequestError('invalid_input',422)
            if self.ready_task is not None and not self.ready_task.done():
                return await JSONResponse({'ready':False},status_code=503)(scope,receive,send)
            self.ready_task=asyncio.create_task(asyncio.to_thread(self.auth.ready))
            # Retrieve late failures even after timeout, cancellation or replacement.
            def consume_probe(done):
                if not done.cancelled():done.exception()
            self.ready_task.add_done_callback(consume_probe)
            try:
                await asyncio.wait_for(asyncio.shield(self.ready_task),15)
                ready=True
            except Exception:
                ready=False
            return await JSONResponse({'ready':ready},status_code=200 if ready else 503)(scope,receive,send)
        unsafe=method not in {'GET','HEAD','OPTIONS'}
        if unsafe and headers.get(b'origin') != [self.settings.origin]:
            raise RequestError('origin_rejected',403)
        token=cookies[0] if cookies else None
        principal=None
        if path=='/api/v2/auth/csrf' and token is None:
            if query(scope):
                raise RequestError('invalid_input',422)
            peer=scope.get('client',('unknown',0))[0]
            token=await asyncio.to_thread(self.auth.anonymous,peer)
            response=JSONResponse({'csrf_token':self.auth.csrf(token),'authenticated':False})
            set_cookie(response,self.settings,token)
            return await response(scope,receive,send)
        principal=await asyncio.to_thread(self.auth.resolve,token)
        if unsafe:
            supplied=headers.get(b'x-csrf-token',[''])[0]
            if not HEX.fullmatch(supplied) or not hmac.compare_digest(supplied,self.auth.csrf(token)):
                raise RequestError('csrf_rejected',403)
        if path in ANONYMOUS:
            if principal is not None:
                raise RequestError('anonymous_session_required',403)
        elif path!='/api/v2/auth/csrf' and principal is None:
            raise RequestError('authentication_required',401,clear_cookie=True)
        if path.startswith('/api/v2/admin/'):
            self.auth.admin(principal)
        if source_request:
            await asyncio.to_thread(self.auth.budget,'source_write' if unsafe else 'source_read',
                                    scope.get('client',('unknown',0))[0],principal.user_id)
        params=query(scope)
        source_list=source_request and method=='GET' and path in SOURCE_ROUTES
        if not source_list and path!='/api/v2/admin/invitations' or method!='GET':
            if params:
                raise RequestError('invalid_input',422)
        scope.setdefault('state',{}).update(request_id=request_id,token=token,principal=principal,
                                             peer=scope.get('client',('unknown',0))[0],query=params,language=scope.get('identity_language','en-CA'),
                                             source_request=source_request,source_deadline=entered+20)
        if unsafe:
            content_types=headers.get(b'content-type',[])
            if len(content_types)!=1 or not re.fullmatch(r'application/json(?:\s*;\s*charset=utf-8)?',content_types[0],re.I):
                raise RequestError('unsupported_media_type',415)
            if lengths and int(lengths[0])>16384:
                raise RequestError('body_too_large',413)
            raw=bytearray()
            while True:
                remaining=10-(time.monotonic()-entered)
                if remaining<=0:
                    raise RequestError('request_timeout',408)
                try:
                    message=await asyncio.wait_for(receive(),remaining)
                except TimeoutError:
                    raise RequestError('request_timeout',408) from None
                if message['type']!='http.request':
                    raise RequestError('invalid_input',422)
                raw.extend(message.get('body',b''))
                if len(raw)>16384:
                    raise RequestError('body_too_large',413)
                if not message.get('more_body',False):
                    break
            try:
                value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_object,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if type(value) is not dict:
                    raise ValueError()
            except Exception:
                raise RequestError('invalid_input',422) from None
            async def body_receive():
                return {'type':'http.request','body':bytes(raw),'more_body':False}
            receive=body_receive
        await self.app(scope,receive,send)


def checked_uuid(value):
    try:
        return s.canonical_uuid(value)
    except Exception:
        raise RequestError('invalid_input',422) from None


def create_app(settings):
    auth=Auth(settings)
    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(auth.close)
    app=FastAPI(title='Wealth Ledger V2 identity API',version='2',docs_url=None,redoc_url=None,
                openapi_url=None,lifespan=lifespan,redirect_slashes=False)
    app.state.auth=auth
    app.add_middleware(Boundary,settings=settings,auth=auth)
    errors={status:{'model':s.Error} for status in [400,401,403,404,405,408,409,413,415,422,429,500,503]}

    @app.exception_handler(RequestValidationError)
    async def validation(request,error):
        return error_response(RequestError('invalid_input',422),request.state.request_id,settings,language=getattr(request.state,'language','en-CA'))

    @app.exception_handler(ResponseValidationError)
    async def invalid_response(request,error):
        return error_response(RequestError('internal_error',500) if getattr(request.state,'source_request',False) else IdentityError(),request.state.request_id,settings,language=getattr(request.state,'language','en-CA'))

    @app.exception_handler(RequestError)
    @app.exception_handler(IdentityError)
    @app.exception_handler(SourceError)
    async def bounded_error(request,error):
        return error_response(error,request.state.request_id,settings,language=getattr(request.state,'language','en-CA'))

    @app.exception_handler(Exception)
    async def unexpected_error(request,error):
        return error_response(RequestError('internal_error',500),request.state.request_id,settings,language=getattr(request.state,'language','en-CA'))

    # Health routes are intercepted by the boundary, and registered for typed OpenAPI.
    @app.get('/healthz',response_model=s.Alive)
    def health():return {'alive':True}

    @app.get('/readyz',response_model=s.Ready,responses={503:{'model':s.Ready}})
    def ready():return {'ready':True}

    @app.get('/api/v2/auth/csrf',response_model=s.Csrf,responses=errors)
    def csrf(request:Request):
        return {'csrf_token':auth.csrf(request.state.token),'authenticated':request.state.principal is not None}

    @app.post('/api/v2/auth/setup',response_model=s.Initialized,status_code=201,responses=errors)
    def setup(body:s.Setup,request:Request,response:Response):
        value=auth.provision(request.state.token,body,request.state.peer,setup=True)
        set_cookie(response,settings)
        return value

    @app.post('/api/v2/auth/register',response_model=s.Registered,status_code=201,responses=errors)
    def register(body:s.Register,request:Request,response:Response):
        value=auth.provision(request.state.token,body,request.state.peer)
        set_cookie(response,settings)
        return value

    @app.post('/api/v2/auth/login',response_model=s.LoggedIn,responses=errors)
    def login(body:s.Login,request:Request,response:Response):
        token=auth.login(request.state.token,body,request.state.peer)
        set_cookie(response,settings,token,authenticated=True)
        return {'authenticated':True,'csrf_token':auth.csrf(token)}

    @app.get('/api/v2/me',response_model=s.Me,responses=errors)
    def me(request:Request):
        p=request.state.principal
        return {'authenticated':True,'user':{'id':p.user_id,'username':p.username,
                'role':'instance_admin' if p.is_instance_admin else 'member'},'portfolio':{'id':p.portfolio_id}}

    @app.post('/api/v2/auth/activity',status_code=204,responses=errors)
    def activity(body:s.Empty,request:Request):
        auth.store.call('touch_session_v1',digest(request.state.token))
        return Response(status_code=204)

    @app.post('/api/v2/auth/logout',status_code=204,responses=errors)
    def logout(body:s.Empty,request:Request):
        auth.store.call('logout_session_v1',digest(request.state.token))
        response=Response(status_code=204)
        set_cookie(response,settings)
        return response

    @app.post('/api/v2/auth/password',status_code=204,responses=errors)
    def password(body:s.ChangePassword,request:Request):
        auth.password(request.state.token,request.state.principal,body,request.state.peer)
        response=Response(status_code=204)
        set_cookie(response,settings)
        return response

    @app.get('/api/v2/candidate-batches/{record_id}',responses=errors,response_class=Response,response_model=DomainBatchV1)
    def candidate(record_id:str,request:Request):
        return Response(auth.candidate(request.state.principal,checked_uuid(record_id)),media_type='application/json')

    @app.get('/api/v2/jobs/{record_id}',response_model=s.Job,responses=errors)
    def job(record_id:str,request:Request):
        return auth.job(request.state.principal,checked_uuid(record_id))

    @app.post('/api/v2/admin/invitations',response_model=s.InvitationIssued,status_code=201,responses=errors)
    def issue(body:s.InviteIssue,request:Request):
        return auth.issue_invite(request.state.principal,body.issue_request_id,request.state.peer)

    @app.get('/api/v2/admin/invitations',response_model=s.Invitations,responses=errors)
    def invitations(request:Request):
        params=request.state.query
        if not set(params)<={'issue_request_id','after','limit'} or 'issue_request_id' in params and len(params)!=1:
            raise RequestError('invalid_input',422)
        request_id=checked_uuid(params['issue_request_id']) if 'issue_request_id' in params else None
        after=checked_uuid(params['after']) if 'after' in params else None
        limit=params.get('limit','50')
        if not re.fullmatch(r'[1-9][0-9]{0,2}',limit) or not 1<=int(limit)<=100:
            raise RequestError('invalid_input',422)
        return auth.read_invites(request.state.principal,request.state.peer,request_id=request_id,after=after,limit=int(limit))

    @app.post('/api/v2/admin/invitations/{record_id}/revoke',status_code=204,responses=errors)
    def revoke(record_id:str,body:s.Empty,request:Request):
        auth.revoke_invite(request.state.principal,checked_uuid(record_id),request.state.peer)
        return Response(status_code=204)

    if getattr(settings,'schema_profile','identity')=='sources':
        def source_result(request,name,payload):
            return auth.source(request.state.principal,name,payload,deadline=request.state.source_deadline)

        def source_query(request,*,connections=False):
            from wealth_ledger.data_sources.contract_v1 import counter,NAMESPACE
            params=request.state.query
            if not set(params)<={'limit','after','catalog_revision','state_revision','incarnation','restore_epoch'}:
                raise RequestError('invalid_input',422)
            limit=params.get('limit','50')
            if not re.fullmatch(r'[1-9][0-9]{0,2}',limit) or not 1<=int(limit)<=100:
                raise RequestError('invalid_input',422)
            after=params.get('after')
            tokens={'catalog_revision','state_revision','incarnation','restore_epoch'}
            if after is None and set(params)&tokens or after is not None and not tokens<=set(params):
                raise RequestError('invalid_input',422)
            realm=None
            try:
                if after is not None:
                    if connections:
                        checked_uuid(after)
                    elif not NAMESPACE.fullmatch(after):
                        raise ValueError()
                    realm={'incarnation':checked_uuid(params['incarnation']),'restore_epoch':counter(params['restore_epoch'])}
                    counter(params['catalog_revision']);counter(params['state_revision'])
            except ValueError:
                raise RequestError('invalid_input',422) from None
            return {'after':after,'limit':int(limit),'catalog_revision':params.get('catalog_revision'),
                    'state_revision':params.get('state_revision'),'expected_realm':realm}

        @app.get('/api/v2/sources',response_model=s.SourceCatalogPage,responses=errors)
        def source_catalog(request:Request):
            return source_result(request,'sources_catalog_v1',source_query(request))

        @app.get('/api/v2/source-connections',response_model=s.SourceConnectionPage,responses=errors)
        def source_connections(request:Request):
            return source_result(request,'sources_connections_v1',source_query(request,connections=True))

        @app.get('/api/v2/source-connections/{record_id}',response_model=s.SourceConnectionRead,responses=errors)
        def source_connection(record_id:str,request:Request):
            return source_result(request,'sources_connection_v1',{'connection_id':checked_uuid(record_id)})

        @app.put('/api/v2/sources/{plugin_id}/capabilities/{capability}',response_model=s.SourceEnableMutation,responses=errors)
        def source_enable(plugin_id:str,capability:str,body:s.SourceEnableRequest,request:Request):
            if not re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}',plugin_id) or capability not in {'FILE_IMPORT','PULL_API'}:
                raise RequestError('invalid_input',422)
            return source_result(request,'set_source_enablement_v1',body.model_dump()|{'plugin_id':plugin_id,'capability':capability})

        @app.post('/api/v2/source-connections',response_model=s.SourceConnectionMutation,status_code=201,responses=errors)
        def source_create(body:s.SourceCreateRequest,request:Request,response:Response):
            value=source_result(request,'create_source_connection_v1',body.model_dump())
            if value.get('replayed') is True:
                response.status_code=200
            return value

        @app.put('/api/v2/source-connections/{record_id}',response_model=s.SourceConnectionMutation,responses=errors)
        def source_update(record_id:str,body:s.SourceUpdateRequest,request:Request):
            return source_result(request,'update_source_connection_v1',body.model_dump()|{'connection_id':checked_uuid(record_id)})

    @app.get('/api/v2/openapi.json',responses=errors)
    def openapi():return app.openapi()
    return app
