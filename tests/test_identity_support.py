"""Explicit disposable identity test targets; never discover an operator workspace."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import unittest
import uuid

EXTRAS=all(importlib.util.find_spec(name) is not None for name in ['sqlalchemy','psycopg','fastapi','pwdlib'])
ENABLED=EXTRAS and os.environ.get('WEALTH_LEDGER_IDENTITY_TEST')=='1' and bool(os.environ.get('WEALTH_LEDGER_IDENTITY_TEST_CONFIG'))


@unittest.skipUnless(ENABLED,'Opt-in isolated PostgreSQL identity acceptance')
class IdentityCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from psycopg.conninfo import conninfo_to_dict
        cls.config=json.loads(Path(os.environ['WEALTH_LEDGER_IDENTITY_TEST_CONFIG']).read_text())
        if cls.config.get('format')!='wealth-ledger-synthetic-identity-tests':
            raise RuntimeError('Explicit synthetic identity marker required')
        options=conninfo_to_dict(Path(cls.config['migration_secret_file']).read_text())
        if not options.get('dbname','').startswith('wl_test_') or not cls.config['container'].startswith('wealth-ledger-pg-test-'):
            raise RuntimeError('Synthetic resource names required')
        label=subprocess.check_output(['docker','inspect','--format','{{index .Config.Labels "wealth-ledger.test"}}',cls.config['container']],text=True).strip()
        if label!='pg-foundation':raise RuntimeError('Synthetic Docker label required')
        cls.key=Path(cls.config['key_file']).read_bytes()
        from pwdlib import PasswordHash
        cls.password='Synthetic ledger password 123'
        cls.encoded=PasswordHash.recommended().hash(cls.password)

    def target(self, *, migrate=True):
        from psycopg.conninfo import make_conninfo
        from wealth_ledger.persistence.config import PostgresConfig
        from wealth_ledger.persistence.identity import IdentityStore
        from wealth_ledger.persistence.context import Database
        from wealth_ledger.persistence.migration import migrate_identity
        name='wl_test_identity_'+uuid.uuid4().hex[:16]
        statement='CREATE DATABASE "'+name+'" OWNER "'+self.config['migration_role']+'"'
        subprocess.run(['docker','exec',self.config['container'],'psql','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-c',statement],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        configs={kind:PostgresConfig(make_conninfo(Path(self.config[kind+'_secret_file']).read_text(),dbname=name),pool_size=1)
                 for kind in ['migration','runtime','identity']}
        operator=IdentityStore(configs['migration']);gateway=IdentityStore(configs['identity'])
        financial=Database(configs['runtime'],schema_mode='identity')
        for resource in [operator,gateway,financial]:self.addCleanup(resource.close)
        if migrate:migrate_identity(operator.database,self.config['runtime_role'],self.config['identity_role'],hashlib.sha256(self.key).hexdigest())
        return name,configs,operator,gateway,financial

    def setUp(self):
        self.name,self.configs,self.operator,self.gateway,self.financial=self.target()

    def scalar(self,sql,**parameters):
        from wealth_ledger.persistence.context import execute
        with self.operator.database.engine.begin() as connection:
            return execute(connection,sql,**parameters).scalar_one()

    def sql(self,sql,**parameters):
        from wealth_ledger.persistence.context import execute
        with self.operator.database.engine.begin() as connection:
            return execute(connection,sql,**parameters).all() if sql.lstrip().upper().startswith('SELECT') else execute(connection,sql,**parameters)

    def anonymous(self):
        from wealth_ledger.web_v2.auth import digest
        token=secrets.token_urlsafe(32)
        self.gateway.call('issue_anonymous_v1',digest(token))
        return token

    def bootstrap(self,username='AdminExample'):
        from wealth_ledger.web_v2.auth import digest
        code=secrets.token_urlsafe(32)
        self.operator.call('arm_setup_v1',digest(code))
        self.gateway.call('bootstrap_commit_v1',digest(code),username,self.encoded,digest(self.anonymous()))
        return self.login(username)

    def login(self,username):
        from wealth_ledger.web_v2.auth import digest
        from wealth_ledger.persistence.identity import Principal
        target=self.gateway.call('login_target_v1',username.lower())
        replacement=secrets.token_urlsafe(32)
        value=self.gateway.call('login_commit_v1',target['user_id'],target['credential_version'],digest(self.anonymous()),digest(replacement))
        return replacement,Principal.from_value(value['principal'])

    def member(self,username='MemberExample'):
        from wealth_ledger.web_v2.auth import digest
        code=secrets.token_urlsafe(32)
        self.operator.call('issue_invite_v1',digest(code))
        self.gateway.call('register_commit_v1',digest(code),username,self.encoded,digest(self.anonymous()))
        return self.login(username)

    def clock(self,instant):
        from wealth_ledger.persistence.context import execute
        # Operator-only test seam on a marked target; never a runtime flag/GUC.
        if not self.name.startswith('wl_test_identity_'):raise RuntimeError()
        import datetime
        datetime.datetime.fromisoformat(instant)
        with self.operator.database.engine.begin() as conn:
            execute(conn,"CREATE OR REPLACE FUNCTION wl_identity._clock_timestamp_v1() RETURNS timestamptz LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS 'SELECT ''"+instant+"''::pg_catalog.timestamptz'")
        self.addCleanup(self.restore_clock)

    def restore_clock(self):
        from wealth_ledger.persistence.context import execute
        with self.operator.database.engine.begin() as conn:
            execute(conn,"CREATE OR REPLACE FUNCTION wl_identity._clock_timestamp_v1() RETURNS timestamptz LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS 'SELECT pg_catalog.clock_timestamp()'")
