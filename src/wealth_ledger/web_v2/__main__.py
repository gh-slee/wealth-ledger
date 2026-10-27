"""Explicit opt-in V2 operator and API entry; help needs no Web/PG extras."""
import argparse
import json
import sys
from pathlib import Path


def parser():
    root=argparse.ArgumentParser(description=__doc__)
    commands=root.add_subparsers(dest='action',required=True)
    key=commands.add_parser('instance-key').add_subparsers(dest='operation',required=True).add_parser('create')
    key.add_argument('--output',required=True,type=Path)
    serve=commands.add_parser('serve')
    for name in ['identity-file','financial-file','key-file']:
        serve.add_argument('--'+name,required=True,type=Path)
    serve.add_argument('--origin',required=True)
    serve.add_argument('--host',required=True)
    serve.add_argument('--port',required=True,type=int)
    serve.add_argument('--tls-cert-file',type=Path)
    serve.add_argument('--tls-key-file',type=Path)
    for action,operations in [('operator',['migrate-identity']),('identity',['status','finalize-restore']),
                               ('setup',['arm','revoke']),('invite',['issue','revoke']),
                               ('account',['reset-password','disable','enable'])]:
        group=commands.add_parser(action).add_subparsers(dest='operation',required=True)
        for operation in operations:
            item=group.add_parser(operation)
            item.add_argument('--secret-file',required=True,type=Path)
            if operation in {'migrate-identity','finalize-restore'}:
                item.add_argument('--runtime-role',required=True)
                item.add_argument('--identity-role',required=True)
                item.add_argument('--key-file',required=True,type=Path)
            if operation=='finalize-restore':
                item.add_argument('--replace-missing-key',action='store_true',help='Only for an isolated restored copy: rebind a newly created private key and quarantine all credentials')
            if operation in {'arm','issue'}:item.add_argument('--output',required=True,type=Path)
            if operation=='revoke':item.add_argument('--record-id',required=True)
            if action=='account':item.add_argument('--user-id',required=True)
            if operation=='reset-password':item.add_argument('--password-stdin',action='store_true')
    return root


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.action=='serve':
            if not 1<=args.port<=65535:raise ValueError()
            from .config import Settings
            from .api import create_app
            import uvicorn
            settings=Settings.from_files(args.identity_file,args.financial_file,args.key_file,args.origin)
            import ipaddress
            import ssl
            bind='127.0.0.1' if args.host=='localhost' else args.host
            try:loopback=ipaddress.ip_address(bind).is_loopback
            except ValueError:loopback=False
            tls=args.tls_cert_file is not None or args.tls_key_file is not None
            if (not bind or any(c.isspace() for c in bind) or
                    tls and (not settings.secure or args.tls_cert_file is None or args.tls_key_file is None)
                    or not loopback and not tls):
                raise ValueError()
            options={}
            if tls:
                from .config import private_bytes
                private_bytes(args.tls_key_file,65536)
                private_bytes(args.tls_cert_file,65536)
                context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(args.tls_cert_file,args.tls_key_file)
                options.update(ssl_certfile=str(args.tls_cert_file),ssl_keyfile=str(args.tls_key_file))
            app=create_app(settings)
            uvicorn.run(app,host=bind,port=args.port,proxy_headers=False,access_log=False,log_level='warning',**options)
            return 0
        from .operator import execute_command
        print(json.dumps(execute_command(args)))
        return 0
    except Exception as error:
        from .operator import OperatorError
        # Diagnostics intentionally exclude exception strings/DSNs/paths/passwords.
        code=getattr(error,'code','operation_failed')
        permitted={'operation_failed','invalid_config','invalid_input','private_export_failed',
                   'password_input_required','password_confirmation_failed','migration_target_invalid',
                   'migration_role_required','schema_unsupported','restore_required','counter_exhausted',
                   'setup_closed','setup_already_armed','setup_not_active','operator_not_found',
                   'invite_not_active','setup_required','instance_not_ready'}
        result={'error':code if code in permitted else 'operation_failed'}
        if isinstance(error,OperatorError) and error.record_id:
            result.update(record_id=error.record_id,revoked=error.resolved,needs_reconciliation=not error.resolved)
        print(json.dumps(result),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
