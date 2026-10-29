"""Real SQL lifecycle CAS/replay and commit-ack recovery, independent connections."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import threading
import unittest
import uuid
from unittest.mock import patch

from test_source_lifecycle import ConfiguredSourceCase,CONTENT_ENABLED
from wealth_ledger.persistence.source_store import SourceStore
from wealth_ledger.persistence.identity import IdentityError
from wealth_ledger.data_sources.lifecycle_v1 import SourceError


@unittest.skipUnless(CONTENT_ENABLED,'Explicit immutable source image and artifact required')
class SourceRaceTests(ConfiguredSourceCase):
    def stores(self,count):
        result=[SourceStore(self.configs['identity'],self.catalog) for _ in range(count)]
        for store in result:self.addCleanup(store.close)
        return result

    def test_sixteen_same_key_creates_commit_once_and_match_independent_digest(self):
        _,principal=self.bootstrap();self.enable(principal)
        body=self.common(principal)|{'plugin_id':'wealthsimple','capability':'FILE_IMPORT','installation_id':self.installation(),
             'display_label':'Synthetic é export','parser_source_alias':None}
        stores=self.stores(16);barrier=threading.Barrier(16)
        def run(index):
            barrier.wait(timeout=10)
            return stores[index].call('create_source_connection_v1',principal,body)
        with ThreadPoolExecutor(max_workers=16) as pool:values=list(pool.map(run,range(16)))
        self.assertEqual(sum(not x['replayed'] for x in values),1)
        self.assertEqual(sum(x['replayed'] for x in values),15)
        self.assertEqual(len({x['resource']['id'] for x in values}),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.connection_lifecycle'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),2)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_audit'),2)
        self.assertEqual(self.scalar('SELECT revision FROM wl_sources.lifecycle_roots'),2)
        independent=hashlib.sha256(json.dumps({'operation_kind':'CREATE_CONNECTION','resource_path':'/api/v2/source-connections','body':body},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(self.scalar('SELECT request_digest FROM wl_sources.lifecycle_receipts WHERE operation_id=:id',id=body['operation_id']),independent)
        self.assertEqual(self.scalar('SELECT sum(fact_generation) FROM wl_pg.portfolios'),0)

    def test_distinct_enable_keys_same_cas_have_one_winner(self):
        _,principal=self.bootstrap();stores=self.stores(2);barrier=threading.Barrier(2)
        bodies=[self.common(principal)|{'plugin_id':'wealthsimple','capability':'FILE_IMPORT','enabled':True,'installation_id':self.installation()} for _ in range(2)]
        def run(index):
            barrier.wait(timeout=5)
            try:stores[index].call('set_source_enablement_v1',principal,bodies[index]);return 'committed'
            except SourceError as error:return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(run,range(2)))
        self.assertEqual(sorted(values),['committed','source_revision_conflict'])
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.enablements'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),1)

    def test_precommit_fault_rolls_back_and_real_lost_ack_replays_same_resource(self):
        _,principal=self.bootstrap();self.enable(principal)
        body=self.common(principal)|{'plugin_id':'wealthsimple','capability':'FILE_IMPORT','installation_id':self.installation(),
             'display_label':'Synthetic export','parser_source_alias':None}
        def fail(_):raise RuntimeError('Synthetic before-COMMIT interruption')
        with self.assertRaises(IdentityError):self.sources.call('create_source_connection_v1',principal,body,before_commit=fail)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.connection_lifecycle'),0)
        from sqlalchemy.engine.base import RootTransaction
        original=RootTransaction.commit;seen=[]
        def lost(transaction):
            own=transaction.connection.engine is self.sources.database.engine
            original(transaction)
            if own:raise ConnectionError('Synthetic loss after actual COMMIT')
        with patch.object(RootTransaction,'commit',lost):
            with self.assertRaisesRegex(SourceError,'source_commit_uncertain'):
                self.sources.call('create_source_connection_v1',principal,body,before_commit=lambda value:seen.append(value['resource']['id']))
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.connection_lifecycle'),1)
        refreshed=self.gateway.session(principal.session_digest)
        replay=self.sources.call('create_source_connection_v1',refreshed,body)
        self.assertEqual((replay['replayed'],replay['representation'],replay['resource']['id']),(True,'historical',seen[0]))
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_sources.lifecycle_receipts'),2)
        self.assertEqual(self.scalar('SELECT count(*) FROM wl_pg.outbox'),0)
