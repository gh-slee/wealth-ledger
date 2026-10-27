"""Core-only inert imports plus closed optional password/config/DTO grammars."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class InertTests(unittest.TestCase):
    def test_help_and_import_need_no_optional_packages_or_files(self):
        script="""import sys,importlib.abc
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'sqlalchemy','psycopg','fastapi','pwdlib','uvicorn','alembic'}: raise ImportError('Optional import denied')
sys.meta_path.insert(0,Deny())
import wealth_ledger.web_v2
import wealth_ledger.web_v2.__main__ as entry
import wealth_ledger.persistence.identity
entry.main(['--help'])
"""
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('migrate',subprocess.check_output([sys.executable,'-m','wealth_ledger.web_v2','operator','--help'],text=True))

    def test_password_stdin_preserves_interior_newlines_and_rejects_oversize(self):
        import io
        from wealth_ledger.web_v2.operator import read_password,OperatorError
        value='synthetic interior\nnewline password'
        stream=io.TextIOWrapper(io.BytesIO(value.encode()+b'\n'))
        with patch('sys.stdin',stream):self.assertEqual(read_password(stdin=True),value)
        stream=io.TextIOWrapper(io.BytesIO(b'x'*1026))
        with patch('sys.stdin',stream):
            with self.assertRaises(OperatorError):read_password(stdin=True)

    def test_private_export_does_not_replace_files_or_links(self):
        from wealth_ledger.web_v2.operator import new_private,OperatorError
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'key'
            new_private(path,b'synthetic')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(OperatorError):new_private(path,b'changed')
            link=Path(folder)/'link';link.symlink_to(path)
            with self.assertRaises(OperatorError):new_private(link,b'changed')
            self.assertEqual(path.read_bytes(),b'synthetic')


@unittest.skipUnless(importlib.util.find_spec('fastapi'),'Optional typed Web schemas')
class GrammarTests(unittest.TestCase):
    def test_passwords_preserve_spaces_unicode_and_literal_forms(self):
        from wealth_ledger.web_v2.schemas import Login,Setup,ChangePassword
        code='x'*43
        for value in [' '*15,'a'*256,'e\u0301'*8,'\u00e9'*15]:
            model=Setup(setup_token=code,username='A.b-_',password=value)
            self.assertEqual(model.password.get_secret_value(),value)
            self.assertNotIn(value,repr(model))
        for value in ['', 'a'*14,'a'*257,'a'*15+'\x00','a'*15+'\ud800']:
            with self.assertRaises(Exception):Setup(setup_token=code,username='valid',password=value)
        self.assertEqual(Login(username='valid',password='x').password.get_secret_value(),'x')
        with self.assertRaises(Exception):ChangePassword(current_password='',new_password='a'*15)
        for name in ['x\n','\u00e9',' padded','x'*65]:
            with self.assertRaises(Exception):Login(username=name,password='x')
        with self.assertRaises(Exception):Login(username='valid',password='x',tenant_id='forged')

    def test_uuid_is_canonical_nonzero_and_query_rejects_duplicates(self):
        from wealth_ledger.web_v2.schemas import InviteIssue
        from wealth_ledger.web_v2.api import query
        for value in ['00000000-0000-0000-0000-000000000000','ABCDEFAB-1234-4321-8888-abcdefabcdef','123']:
            with self.assertRaises(Exception):InviteIssue(issue_request_id=value)
        for value in [b'a=1&a=2',b'x=%GG',b'x=%FF',b'bare']:
            with self.assertRaises(Exception):query({'query_string':value})

    @unittest.skipUnless(importlib.util.find_spec('psycopg'),'Optional explicit PG config')
    def test_configuration_refuses_implicit_or_mismatched_targets(self):
        from wealth_ledger.persistence.config import PostgresConfig
        from wealth_ledger.web_v2.config import Settings
        base='host=127.0.0.1 port=5432 dbname=synthetic user=synthetic_gateway password=synthetic_example sslmode=disable'
        a=PostgresConfig(base);b=PostgresConfig(base.replace('synthetic_gateway','synthetic_finance'))
        with patch.dict('os.environ',{},clear=True):
            self.assertEqual(Settings(a,b,b'x'*32,'http://localhost').cookie_name,'wealth_v2_session')
            self.assertEqual(Settings(a,b,b'x'*32,'https://example.test').cookie_name,'__Host-wealth_v2_session')
            for config in [PostgresConfig(base+' service=example'),PostgresConfig(base.replace('5432','5433')),a]:
                with self.assertRaises(ValueError):Settings(a,config,b'x'*32,'http://localhost')
            for origin in ['http://example.test','http://localhost/','http:'+ '/'*2 + 'u:p@localhost','https://example.test?x=1']:
                with self.assertRaises(ValueError):Settings(a,b,b'x'*32,origin)
        with patch.dict('os.environ',{'PGPASSWORD':'synthetic_example'}):
            with self.assertRaises(ValueError):Settings(a,b,b'x'*32,'http://localhost')
