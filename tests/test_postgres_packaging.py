"""Source-only optional-foundation packaging/guard boundaries use synthetic data."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_publication import path_allowed,content_issues
from docker_context import FIXED


class PostgresPackagingTests(unittest.TestCase):
    def test_exact_public_additions_do_not_allow_private_siblings(self):
        for name in ['requirements-pg.lock','requirements-pg-test.lock','compose.pg-foundation.yaml','docs/postgres-foundation.md','tests/fixtures/postgres_foundation/golden.json','tests/fixtures/postgres_foundation/oracles.json']:
            self.assertTrue(path_allowed(name),name)
        for name in ['docs/AGENTS.override.md','tests/fixtures/postgres_foundation/personal.csv','tests/fixtures/postgres_foundation/ledger.db','work/approval.json','docs/specs/wealth-ledger-v2/PLANNING_STATE.md']:
            self.assertFalse(path_allowed(name),name)
        for name in ['golden.json','oracles.json']:
            path=ROOT/'tests/fixtures/postgres_foundation'/name
            self.assertEqual(content_issues(path.read_bytes(),path.relative_to(ROOT).as_posix()),[])

    def test_optional_image_and_source_package_remain_explicit(self):
        self.assertIn('requirements-pg.lock',FIXED)
        self.assertNotIn('requirements-pg-test.lock',FIXED)
        self.assertNotIn('scripts/postgres.py',FIXED)
        text=(ROOT/'Dockerfile').read_text();self.assertIn('ARG WEALTH_LEDGER_POSTGRES=0',text)
        self.assertIn('ENTRYPOINT ["python", "/app/scripts/web.py"]',text)
        source=(ROOT/'src/wealth_ledger/persistence/__init__.py').read_text();self.assertEqual(len(ast.parse(source).body),1)
        compose=(ROOT/'compose.pg-foundation.yaml').read_text();self.assertNotIn('ports:',compose);self.assertNotIn('/data',compose)


from test_postgres_config import PostgresCase
import os


@unittest.skipUnless(os.environ.get('WEALTH_LEDGER_PG_RUNTIME_IMAGE'),'Explicit optional PG runtime image acceptance')
class RuntimeImageTests(PostgresCase):
    def test_nonroot_optional_image_uses_only_runtime_role_and_exact_candidate(self):
        import subprocess
        from psycopg.conninfo import make_conninfo
        payload={'conninfo':make_conninfo(Path(self.settings['runtime_secret_file']).read_text(),host=self.settings['container'],port=5432),
                 'candidate':self.raw.decode(),'batch_id':self.batch_id}
        program="""import importlib.util,json,sys
from wealth_ledger.domain.validation_v1 import decode_domain_v1,encode_domain_v1
from wealth_ledger.persistence.config import PostgresConfig
from wealth_ledger.persistence.context import Database,TenantContext
from wealth_ledger.persistence.repositories import Candidates
assert importlib.util.find_spec('alembic') is None
payload=json.load(sys.stdin);raw=payload['candidate'].encode();batch=decode_domain_v1(raw)
database=Database(PostgresConfig(payload['conninfo']));context=TenantContext(batch.tenant_id,batch.portfolio_id)
try:
 repository=Candidates(database);repository.put(context,payload['batch_id'],batch,expected_generation=0,idempotency_key='runtime-image-probe')
 assert encode_domain_v1(repository.read(context,payload['batch_id']))==raw
finally:database.close()
print('optional_pg_runtime_roundtrip_ok')
"""
        result=subprocess.run(['docker','run','--rm','-i','--network',self.settings['network'],'--entrypoint','python',os.environ['WEALTH_LEDGER_PG_RUNTIME_IMAGE'],'-c',program],input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr.decode()[-2000:])
        self.assertEqual(result.stdout.strip(),b'optional_pg_runtime_roundtrip_ok')
