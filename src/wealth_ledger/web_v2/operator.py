"""Foreground-only operator actions. Importing never opens a database or reads files."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys


class OperatorError(Exception):
    def __init__(self, code='operation_failed', *, record_id=None, resolved=False):
        self.code, self.record_id, self.resolved = code, record_id, resolved
        super().__init__(code)


def new_private(path, raw):
    """Never replace an existing destination, including dangling symlinks."""
    path=Path(path)
    fd=None
    created=False
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        created=True
        with os.fdopen(fd,'wb') as stream:
            fd=None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    except Exception:
        if fd is not None:os.close(fd)
        if created:
            try:path.unlink()
            except OSError:pass
        raise OperatorError('private_export_failed') from None


def export_secret(store, kind, output):
    """Journal an opaque ID before COMMIT; hard termination leaves a recovery handle."""
    from wealth_ledger.persistence.identity import IdentityError
    from .auth import digest
    output=Path(output)
    receipt=output.with_name(output.name+'.receipt.json')
    # Both files must be new. The durable receipt contains no bearer/digest.
    new_private(receipt,b'{"state":"prepared","record_id":null}\n')
    descriptor=None
    created=False
    record_id=None
    try:
        descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        created=True
        token=secrets.token_urlsafe(32)
        key='setup_id' if kind=='setup' else 'invite_id'
        def journal(value):
            nonlocal record_id
            from wealth_ledger.persistence.context import identifier
            record_id=identifier(value[key])
            # The receipt is owned by this invocation; never follow a replaced link.
            fd=os.open(receipt,os.O_WRONLY|os.O_NOFOLLOW)
            try:
                os.ftruncate(fd,0)
                payload=json.dumps({'state':'commit_pending','record_id':record_id,'kind':kind,'needs_reconciliation':True}).encode()+b'\n'
                with os.fdopen(fd,'wb',closefd=False) as stream:
                    stream.write(payload);stream.flush();os.fsync(fd)
            finally:os.close(fd)
        value=store.call('arm_setup_v1' if kind=='setup' else 'issue_invite_v1',digest(token),before_commit=journal)
        with os.fdopen(descriptor,'wb') as stream:
            descriptor=None
            stream.write(token.encode('ascii')+b'\n')
            stream.flush();os.fsync(stream.fileno())
        directory=os.open(output.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return {key:record_id,'expires_at':value['expires_at'],'secret_exported':True,
                'receipt_retained':True}
    except Exception as error:
        if isinstance(error,IdentityError) and error.record_id:
            record_id=error.record_id
        resolved=False
        if record_id:
            try:
                store.call('revoke_setup_v1' if kind=='setup' else 'revoke_invite_v1',record_id)
                resolved=True
            except Exception:
                pass
        if descriptor is not None:
            try:os.close(descriptor)
            except OSError:pass
        if created:
            try:output.unlink()
            except OSError:pass
        if isinstance(error,IdentityError) and not error.uncertain and record_id is None:
            raise error
        # A durable ID is retained even if the command dies before writing a token.
        raise OperatorError('private_export_failed',record_id=record_id,resolved=resolved) from None


def read_password(*,stdin=False):
    if stdin:
        raw=sys.stdin.buffer.read(1026)
        if len(raw)>1025:
            raise OperatorError('invalid_input')
        value=raw.removesuffix(b'\n').decode('utf-8')
    else:
        if not sys.stdin.isatty():
            raise OperatorError('password_input_required')
        value=getpass.getpass('New password: ')
        if value!=getpass.getpass('Confirm password: '):
            raise OperatorError('password_confirmation_failed')
    if not 15<=len(value)<=256 or '\x00' in value or any(0xD800<=ord(c)<=0xDFFF for c in value):
        raise OperatorError('invalid_input')
    return value


def execute_command(args):
    if args.action=='instance-key':
        new_private(args.output,secrets.token_bytes(32))
        return {'key_created':True}
    from wealth_ledger.persistence.config import PostgresConfig
    from wealth_ledger.persistence.identity import IdentityStore
    from wealth_ledger.persistence.migration import migrate_identity, finalize_identity_restore
    from .config import private_bytes
    store=IdentityStore(PostgresConfig.from_secret_file(args.secret_file))
    try:
        if args.action=='operator':
            key=private_bytes(args.key_file,32)
            if len(key)!=32:raise OperatorError('invalid_config')
            return migrate_identity(store.database,args.runtime_role,args.identity_role,hashlib.sha256(key).hexdigest())
        if args.action=='identity':
            if args.operation=='status':
                # Do not print database names, role names, keys or admin UUIDs.
                state=store.status()
                return {'ready':True,'schema_revision':state['schema_revision'],'bootstrap_closed':state['bootstrap_closed']}
            key=private_bytes(args.key_file,32)
            if len(key)!=32:raise OperatorError('invalid_config')
            return finalize_identity_restore(store.database,args.runtime_role,args.identity_role,hashlib.sha256(key).hexdigest(),
                                             replace_missing_key=args.replace_missing_key)
        if args.action in {'setup','invite'}:
            if args.operation in {'arm','issue'}:
                return export_secret(store,args.action,args.output)
            from wealth_ledger.persistence.context import identifier
            store.call('revoke_setup_v1' if args.action=='setup' else 'revoke_invite_v1',identifier(args.record_id))
            return {'revoked':True}
        from wealth_ledger.persistence.context import identifier
        user_id=identifier(args.user_id)
        if args.operation=='reset-password':
            value=read_password(stdin=args.password_stdin)
            from .auth import Passwords
            passwords=Passwords()
            with passwords.admitted():encoded=passwords.hash(value)
            store.call('reset_user_v1',user_id,encoded)
            return {'password_reset':True}
        store.call('set_user_enabled_v1',user_id,args.operation=='enable')
        return {'enabled':args.operation=='enable'}
    finally:store.close()
