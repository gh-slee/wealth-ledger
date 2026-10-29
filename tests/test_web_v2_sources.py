"""Actual ASGI sources API contracts; no running user service or browser data."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch

from test_source_lifecycle import ConfiguredSourceCase,CONTENT_ENABLED


@unittest.skipUnless(CONTENT_ENABLED,'Explicit immutable source image and artifact required')
class SourceHttpTests(ConfiguredSourceCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from wealth_ledger.web_v2.api import create_app
        from wealth_ledger.web_v2.config import Settings
        self.app=create_app(Settings(self.configs['identity'],self.configs['runtime'],self.key,'http://localhost',schema_profile='sources',source_catalog=self.catalog))
        self.client=TestClient(self.app,base_url='http://localhost')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)

    def csrf(self,client=None):
        client=client or self.client
        value=client.get('/api/v2/auth/csrf')
        self.assertEqual(value.status_code,200,value.text)
        return value.json()['csrf_token']

    def login(self,username=None):
        if username is not None:return super().login(username)
        self.bootstrap()
        value=self.client.post('/api/v2/auth/login',json={'username':'AdminExample','password':self.password},headers={'Origin':'http://localhost','X-CSRF-Token':self.csrf()})
        self.assertEqual(value.status_code,200,value.text)
        self.headers={'Origin':'http://localhost','X-CSRF-Token':value.json()['csrf_token']}
        return self.client.get('/api/v2/sources').json()['realm']

    def body(self,realm,**extra):
        return {'operation_id':str(uuid.uuid4()),'expected_revision':'0','expected_realm':realm}|extra

    def enable_http(self,realm):
        body=self.body(realm,enabled=True,installation_id=self.installation())
        value=self.client.put('/api/v2/sources/wealthsimple/capabilities/FILE_IMPORT',json=body,headers=self.headers)
        self.assertEqual(value.status_code,200,value.text)
        return body,value.json()

    def create_http_body(self,realm):
        return self.body(realm,plugin_id='wealthsimple',capability='FILE_IMPORT',installation_id=self.installation(),display_label='Synthetic export',parser_source_alias=None)

    def test_authentication_closed_catalog_and_mutation_create_replay_status(self):
        self.assertEqual(self.client.get('/api/v2/sources').status_code,401)
        realm=self.login()
        with patch('wealth_ledger.source_registry.build_registry',side_effect=AssertionError('No parser dispatch')):
            catalog=self.client.get('/api/v2/sources')
        self.assertEqual(catalog.status_code,200,catalog.text)
        for forbidden in ('entry_point_target','descriptor_bytes','database_oid','server_address','artifact_sha256'):
            self.assertNotIn(forbidden,catalog.text)
        self.enable_http(realm)
        body=self.create_http_body(realm)
        created=self.client.post('/api/v2/source-connections',json=body,headers=self.headers)
        self.assertEqual(created.status_code,201,created.text)
        replay=self.client.post('/api/v2/source-connections',json=body,headers=self.headers)
        self.assertEqual(replay.status_code,200,replay.text)
        self.assertEqual((replay.json()['replayed'],replay.json()['representation']),(True,'historical'))
        self.assertEqual(created.json()['resource']['id'],replay.json()['resource']['id'])
        for response in (catalog,created,replay):
            self.assertEqual(response.headers['cache-control'],'no-store, private')
            self.assertEqual(response.headers['x-content-type-options'],'nosniff')
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.candidate_batches'),0)
        self.assertEqual(self.scalar('SELECT sum(fact_generation) FROM wl_pg.portfolios'),0)

    def test_strict_body_fields_and_routes_do_not_reflect_input(self):
        realm=self.login();body=self.create_http_body(realm)
        variants=[body|{'expected_revision':0},body|{'capability':'UNKNOWN'},body|{'tenant_id':str(uuid.uuid4())},body|{'display_label':'bad\u0085label'},body|{'display_label':'\u00a0label'},body|{'parser_source_alias':False}]
        for value in variants:
            response=self.client.post('/api/v2/source-connections',json=value,headers=self.headers)
            self.assertEqual(response.status_code,422,response.text)
            self.assertEqual(response.json()['error']['code'],'invalid_input')
            self.assertNotIn('bad',response.text)
        response=self.client.put('/api/v2/sources/UPPER/capabilities/FILE_IMPORT',json=self.body(realm,enabled=True,installation_id=self.installation()),headers=self.headers)
        self.assertEqual(response.status_code,422,response.text)
        response=self.client.put('/api/v2/sources/wealthsimple/capabilities/FILE_IMPORT',json=self.body(realm,enabled='true',installation_id=self.installation()),headers=self.headers)
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),0)

    def test_recognized_api_is409_and_unknown_capability_is422(self):
        realm=self.login()
        body=self.create_http_body(realm)|{'capability':'PULL_API','plugin_id':'unknown'}
        response=self.client.post('/api/v2/source-connections',json=body,headers=self.headers)
        self.assertEqual((response.status_code,response.json()['error']['code']),(409,'source_capability_unavailable'))
        body['capability']='UNKNOWN'
        self.assertEqual(self.client.post('/api/v2/source-connections',json=body,headers=self.headers).status_code,422)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.connection_lifecycle'),0)

    def test_pagination_and_foreign_missing_opaque_ids(self):
        realm=self.login()
        first=self.client.get('/api/v2/sources',params={'limit':'1'})
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['next_after'],'bullbitcoin')
        for query in ({'after':'bullbitcoin'},{'catalog_revision':'1'},{'limit':'01'},{'tenant_id':str(uuid.uuid4())}):
            self.assertEqual(self.client.get('/api/v2/sources',params=query).status_code,422)
        next_query={'after':'bullbitcoin','limit':'1','catalog_revision':first.json()['catalog_revision'],
                    'state_revision':first.json()['state_revision'],**first.json()['realm']}
        self.assertEqual(self.client.get('/api/v2/sources',params=next_query).status_code,200)
        self.enable_http(realm)
        self.assertEqual(self.client.get('/api/v2/sources',params=next_query).status_code,409)
        _,member=self.member();self.enable(member);_,created=self.create(member)
        for record_id in (created['resource']['id'],str(uuid.uuid4())):
            response=self.client.get('/api/v2/source-connections/'+record_id)
            self.assertEqual((response.status_code,response.json()['error']['code']),(404,'not_found'))
        self.assertEqual(self.client.get('/api/v2/source-connections/not-a-uuid').status_code,422)

    def test_invalid_admitted_requests_consume_persistent_source_budget(self):
        self.login()
        for _ in range(30):
            value=self.client.post('/api/v2/source-connections',json={},headers=self.headers)
            self.assertEqual(value.status_code,422,value.text)
        value=self.client.post('/api/v2/source-connections',json={},headers=self.headers)
        self.assertEqual((value.status_code,value.json()['error']['code']),(429,'rate_limited'))
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),0)

    def test_source_response_shape_failure_is_bounded500(self):
        self.login()
        with patch.object(self.app.state.auth,'source',return_value={'synthetic-sensitive-text':'never reflect'}):
            value=self.client.get('/api/v2/sources')
        self.assertEqual((value.status_code,value.json()['error']['code']),(500,'internal_error'))
        self.assertNotIn('synthetic-sensitive-text',value.text)

    def test_origin_csrf_and_closed_operation_surface(self):
        realm=self.login();body=self.create_http_body(realm)
        self.assertEqual(self.client.post('/api/v2/source-connections',json=body).status_code,403)
        self.assertEqual(self.client.post('/api/v2/source-connections',json=body,headers={'Origin':'http://localhost','X-CSRF-Token':'0'*64}).status_code,403)
        record_id=str(uuid.uuid4())
        self.assertEqual(self.client.delete('/api/v2/source-connections/'+record_id,headers=self.headers).status_code,405)
        self.assertEqual(self.client.post('/api/v2/source-connections/'+record_id+'/sync',json={},headers=self.headers).status_code,404)
        self.assertEqual(self.client.post('/api/v2/sources/install',json={},headers=self.headers).status_code,404)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.connection_lifecycle'),0)


    def test_update_alias_is_closed_and_public_cursor_realm_has_only_public_fields(self):
        realm=self.login();self.enable_http(realm)
        created=self.client.post('/api/v2/source-connections',json=self.create_http_body(realm),headers=self.headers)
        self.assertEqual(created.status_code,201);record=created.json()['resource']
        body=self.body(realm,expected_revision='1',enabled=True,installation_id=record['installation_id'],display_label=record['display_label'])
        response=self.client.put('/api/v2/source-connections/'+record['id'],json=body|{'parser_source_alias':'changed'},headers=self.headers)
        self.assertEqual((response.status_code,response.json()['error']['code']),(422,'invalid_input'))
        self.assertEqual(self.scalar('SELECT revision FROM wl_sources.connection_lifecycle'),1)
        page=self.client.get('/api/v2/sources?limit=1').json();self.assertEqual(set(page['realm']),{'incarnation','restore_epoch'})
        params={'limit':'1','after':page['next_after'],'catalog_revision':page['catalog_revision'],'state_revision':page['state_revision'],**page['realm']}
        self.assertEqual(self.client.get('/api/v2/sources',params=params).status_code,200)
        self.assertEqual(self.client.get('/api/v2/sources',params={'expected_realm':'not-a-query-field'}).status_code,422)
