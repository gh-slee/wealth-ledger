"""Optional PG configuration and shared explicitly synthetic integration setup."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from wealth_ledger.domain.validation_v1 import decode_domain_v1
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.persistence.context import Database,TenantContext,execute
from wealth_ledger.persistence.migration import seed_tenant
from wealth_ledger.persistence.errors import PersistenceError

EXTRAS=importlib.util.find_spec('sqlalchemy') is not None and importlib.util.find_spec('psycopg') is not None
CONFIG=os.environ.get('WEALTH_LEDGER_PG_TEST_CONFIG')
FIXTURES=Path(__file__).parent/'fixtures/postgres_foundation'


@unittest.skipUnless(EXTRAS,'Optional PostgreSQL dependencies not installed')
class ConfigurationTests(unittest.TestCase):
    def test_secret_file_permissions_bounds_and_no_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'connection'
            path.write_text('dbname=synthetic user=synthetic');path.chmod(0o600)
            config=PostgresConfig.from_secret_file(path,pool_size=1)
            self.assertNotIn('dbname',repr(config))
            for mode in [0o644,0o660]:
                path.chmod(mode)
                with self.assertRaisesRegex(PersistenceError,'invalid_config'):PostgresConfig.from_secret_file(path)
            path.chmod(0o600);link=Path(folder)/'link';link.symlink_to(path)
            with self.assertRaises(PersistenceError):PostgresConfig.from_secret_file(link)
            path.write_text('x'*16385)
            with self.assertRaises(PersistenceError):PostgresConfig.from_secret_file(path)

    def test_context_and_config_reject_missing_defaults(self):
        for t,p in [('',str(uuid.uuid4())),('00000000-0000-0000-0000-000000000000',str(uuid.uuid4())),(str(uuid.uuid4()),'wrong')]:
            with self.assertRaises(PersistenceError):TenantContext(t,p)
        for pool in [0,6,True]:
            with self.assertRaises(PersistenceError):PostgresConfig('dbname=synthetic user=synthetic',pool)


@unittest.skipUnless(EXTRAS and CONFIG and os.environ.get('WEALTH_LEDGER_PG_TEST')=='1','Opt-in isolated real PostgreSQL acceptance')
class PostgresCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings=json.loads(Path(CONFIG).read_text())
        if cls.settings.get('format')!='wealth-ledger-synthetic-pg-tests':raise RuntimeError('Synthetic test config required')
        from psycopg.conninfo import conninfo_to_dict
        options=conninfo_to_dict(Path(cls.settings['migration_secret_file']).read_text())
        if not options.get('dbname','').startswith(('wl_test_','wl004_')):raise RuntimeError('Synthetic database name required')
        cls.operator=Database(PostgresConfig.from_secret_file(cls.settings['migration_secret_file'],pool_size=1))
        cls.runtime=Database(PostgresConfig.from_secret_file(cls.settings['runtime_secret_file'],pool_size=1))
        cls.addClassCleanup(cls.operator.close);cls.addClassCleanup(cls.runtime.close)

    def setUp(self):
        original=(FIXTURES/'golden.json').read_bytes();template=decode_domain_v1(original)
        self.context=TenantContext(str(uuid.uuid4()),str(uuid.uuid4()))
        raw=original.replace(template.tenant_id.encode(),self.context.tenant_id.encode()).replace(template.portfolio_id.encode(),self.context.portfolio_id.encode())
        self.batch=decode_domain_v1(raw);self.raw=raw;self.batch_id=str(uuid.uuid4())
        seed_tenant(self.operator,self.context)

    def scalar(self,sql,**kwargs):
        with self.operator.engine.begin() as conn:
            return execute(conn,sql,t=self.context.tenant_id,p=self.context.portfolio_id,**kwargs).scalar_one()
