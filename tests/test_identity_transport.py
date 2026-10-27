"""Transport policy rejects public plaintext before activation; real loopback TLS."""
from contextlib import redirect_stderr
import io
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import urllib.error
import urllib.request
from unittest.mock import patch

from test_identity_support import IdentityCase


class IdentityTransport(IdentityCase):
    def test_cli_bind_origin_tls_matrix_before_database_activation(self):
        from wealth_ledger.web_v2.__main__ import main
        base=['serve','--identity-file','identity.conninfo','--financial-file','finance.conninfo',
              '--key-file','instance.key','--port','54321']
        for secure,bind,tls,accepted in [(False,'0.0.0.0',False,False),(True,'0.0.0.0',False,False),
                  (False,'127.0.0.1',False,True),(False,'localhost',False,True),
                  (True,'0.0.0.0',True,True),(False,'127.0.0.1',True,False)]:
            args=base+['--origin',('https' if secure else 'http')+'://localhost','--host',bind]
            if tls:args+=['--tls-cert-file','certificate.pem','--tls-key-file','transport.key']
            with patch('wealth_ledger.web_v2.config.Settings.from_files',return_value=SimpleNamespace(secure=secure)), \
                 patch('wealth_ledger.web_v2.config.private_bytes',return_value=b'synthetic'), \
                 patch('ssl.SSLContext'),patch('wealth_ledger.web_v2.api.create_app') as app, \
                 patch('uvicorn.run') as run,redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),0 if accepted else 2,(secure,bind,tls))
                self.assertEqual(run.called,accepted)
                self.assertEqual(app.called,accepted)
                if accepted and tls:
                    self.assertEqual(run.call_args.kwargs['ssl_keyfile'],'transport.key')
                    self.assertEqual(run.call_args.kwargs['ssl_certfile'],'certificate.pem')
                if accepted and bind=='localhost':self.assertEqual(run.call_args.kwargs['host'],'127.0.0.1')

    def test_real_cli_loopback_tls_handshake_and_secure_cookie(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);cert=folder/'certificate.pem';tls_key=folder/'transport.key'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                            '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost',
                            '-keyout',str(tls_key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for path in [cert,tls_key]:path.chmod(0o600)
            files={}
            for name,value in [('identity',self.configs['identity'].conninfo.encode()),('finance',self.configs['runtime'].conninfo.encode()),('key',self.key)]:
                path=folder/name;path.write_bytes(value);path.chmod(0o600);files[name]=path
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            origin='https://localhost:'+str(port)
            child=subprocess.Popen([sys.executable,'-m','wealth_ledger.web_v2','serve','--identity-file',str(files['identity']),
                    '--financial-file',str(files['finance']),'--key-file',str(files['key']),'--origin',origin,
                    '--host','127.0.0.1','--port',str(port),'--tls-cert-file',str(cert),'--tls-key-file',str(tls_key)],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            def stop():
                if child.poll() is None:child.terminate()
                try:child.communicate(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.communicate(timeout=5)
            self.addCleanup(stop)
            context=ssl.create_default_context(cafile=str(cert));deadline=time.monotonic()+10
            while True:
                try:
                    with urllib.request.urlopen(origin+'/healthz',context=context,timeout=1) as response:
                        self.assertEqual(response.status,200)
                    break
                except (OSError,urllib.error.URLError):
                    if child.poll() is not None or time.monotonic()>=deadline:self.fail('Synthetic TLS service did not activate')
                    time.sleep(.05)
            with urllib.request.urlopen(origin+'/api/v2/auth/csrf',context=context,timeout=3) as response:
                cookie=response.headers['Set-Cookie']
                self.assertTrue(cookie.startswith('__Host-wealth_v2_session='))
                self.assertIn('; Secure',cookie);self.assertIn('; HttpOnly',cookie)
            stop()
