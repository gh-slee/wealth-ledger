"""Trusted identity orchestration; credentials never cross into finance repositories."""
from contextlib import contextmanager
import hashlib
import hmac
import re
import secrets
import threading

from wealth_ledger.persistence.context import Database, RequestDatabase, REALM_SNAPSHOT, execute
from wealth_ledger.persistence.errors import PersistenceError
from wealth_ledger.persistence.identity import IdentityError, IdentityStore, Principal, REALM_KEYS, role_inventory
from wealth_ledger.persistence.identity_schema import HASH_PATTERN

TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')


class RequestError(Exception):
    def __init__(self, code, status, *, clear_cookie=False):
        self.code, self.status, self.clear_cookie = code, status, clear_cookie
        super().__init__(code)


def digest(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


class Passwords:
    """Two nonqueued hashing slots; dummy and real hashes use one pinned profile."""
    def __init__(self):
        from pwdlib import PasswordHash
        self.engine = PasswordHash.recommended()
        self.slots = threading.BoundedSemaphore(2)
        self.dummy = self.engine.hash(secrets.token_urlsafe(32))

    @contextmanager
    def admitted(self):
        if not self.slots.acquire(blocking=False):
            raise RequestError('authentication_busy', 429)
        try:
            yield
        finally:
            self.slots.release()

    def verify(self, encoded, password):
        if not re.fullmatch(HASH_PATTERN, encoded or ''):
            raise IdentityError()
        try:
            return self.engine.verify(password, encoded)
        except Exception:
            raise IdentityError() from None

    def hash(self, password):
        return self.engine.hash(password)


class Auth:
    def __init__(self, settings):
        self.settings = settings
        self.store = IdentityStore(settings.identity)
        self.financial = Database(settings.financial, schema_mode='identity')
        self.passwords = Passwords()
        try:
            self.ready()
        except Exception:
            self.close()
            raise IdentityError() from None

    def close(self):
        self.store.close()
        self.financial.close()

    def instance(self):
        state = self.store.status()
        if not hmac.compare_digest(state['key_digest'], hashlib.sha256(self.settings.key).hexdigest()):
            raise IdentityError()
        return state

    def ready(self):
        try:
            left = self.instance()
            if role_inventory(self.store.database, gateway=True) == role_inventory(self.financial, gateway=False):
                raise IdentityError()
            with self.financial.engine.begin() as conn:
                right = execute(conn, REALM_SNAPSHOT).mappings().one()
            if (any(left[k] != right[k] for k in REALM_KEYS) or right['revision'] != '0002_identity'
                    or right['ready'] is not True):
                raise IdentityError()
            return True
        except Exception:
            raise IdentityError() from None

    def keyed(self, purpose, value):
        return hmac.new(self.settings.key, (purpose+'\0'+value).encode('utf-8'), hashlib.sha256).hexdigest()

    def csrf(self, token):
        return self.keyed('csrf-v2', token)

    def budget(self, operation, peer, subject=None):
        self.store.call('consume_budget_v1', operation, self.keyed('peer', peer),
                        self.keyed('subject', subject) if subject is not None else None)

    def resolve(self, token, kind='any'):
        self.instance()
        if type(token) is not str or not TOKEN.fullmatch(token):
            raise RequestError('authentication_required', 401, clear_cookie=True)
        try:
            return self.store.session(digest(token), kind)
        except IdentityError as error:
            if error.code == 'authentication_required':
                raise RequestError(error.code, 401, clear_cookie=True) from None
            raise

    def anonymous(self, peer):
        self.instance()
        self.budget('anonymous', peer)
        token = secrets.token_urlsafe(32)
        self.store.call('issue_anonymous_v1', digest(token))
        return token

    def login(self, token, body, peer):
        self.budget('login', peer, body.username.lower())
        with self.passwords.admitted():
            target = self.store.call('login_target_v1', body.username.lower())
            usable = target.get('usable') is True
            if set(target) != ({'usable','user_id','argon_hash','credential_version'} if usable else {'usable'}):
                raise IdentityError()
            valid = self.passwords.verify(target['argon_hash'] if usable else self.passwords.dummy, body.password.get_secret_value())
            if not valid or not usable:
                raise RequestError('invalid_credentials', 401)
        replacement = secrets.token_urlsafe(32)
        result = self.store.call('login_commit_v1', target['user_id'], target['credential_version'], digest(token), digest(replacement))
        principal = Principal.from_value(result['principal'])
        if principal.session_digest != digest(replacement):
            raise IdentityError()
        return replacement

    def provision(self, token, body, peer, *, setup=False):
        self.budget('setup' if setup else 'register', peer)
        with self.passwords.admitted():
            encoded = self.passwords.hash(body.password.get_secret_value())
        code = body.setup_token if setup else body.invite_token
        return self.store.call('bootstrap_commit_v1' if setup else 'register_commit_v1',
                               digest(code), body.username, encoded, digest(token))

    def password(self, token, principal, body, peer):
        self.budget('password_change', peer, principal.user_id)
        with self.passwords.admitted():
            target = self.store.call('password_target_v1', digest(token))
            if set(target) != {'user_id','argon_hash','credential_version'} or target['user_id'] != principal.user_id:
                raise IdentityError()
            if not self.passwords.verify(target['argon_hash'], body.current_password):
                raise RequestError('invalid_credentials', 401)
            encoded = self.passwords.hash(body.new_password)
        self.store.call('change_password_v1', principal.user_id, principal.credential_version, digest(token), encoded)

    def admin(self, principal):
        if principal is None:
            raise RequestError('authentication_required', 401)
        if not principal.is_instance_admin:
            raise RequestError('admin_required', 403)

    def issue_invite(self, principal, request_id, peer):
        self.admin(principal)
        self.budget('invite_issue', peer, principal.user_id)
        token = secrets.token_urlsafe(32)
        value = self.store.call('admin_issue_invite_v1', principal.session_digest, principal.user_id,
                                principal.credential_version, request_id, digest(token))
        if set(value) != {'id','issue_request_id','expires_at'}:
            raise IdentityError()
        return {**value, 'invite_token': token}

    def read_invites(self, principal, peer, *, request_id=None, after=None, limit=50):
        self.admin(principal)
        self.budget('invite_read', peer, principal.user_id)
        return self.store.call('admin_read_invites_v1', principal.session_digest, principal.user_id,
                               principal.credential_version, request_id, after, limit)

    def revoke_invite(self, principal, record_id, peer):
        self.admin(principal)
        self.budget('invite_revoke', peer, principal.user_id)
        self.store.call('admin_revoke_invite_v1', principal.session_digest, principal.user_id,
                        principal.credential_version, record_id)

    def candidate(self, principal, record_id):
        from wealth_ledger.persistence.repositories import Candidates
        from wealth_ledger.domain.validation_v1 import encode_domain_v1
        try:
            value = Candidates(RequestDatabase(self.financial, principal)).read(principal.context, record_id)
            if value is None:
                raise RequestError('not_found', 404)
            return encode_domain_v1(value)
        except PersistenceError as error:
            if error.code == 'parent_missing':
                raise RequestError('not_found', 404) from None
            raise IdentityError() from None

    def job(self, principal, record_id):
        from wealth_ledger.persistence.jobs import Jobs
        try:
            value = Jobs(RequestDatabase(self.financial, principal)).read(principal.context, record_id)
            if value is None:
                raise RequestError('not_found', 404)
            return value
        except PersistenceError:
            raise IdentityError() from None
