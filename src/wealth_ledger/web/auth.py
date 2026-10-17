"""Opaque server-side sessions with bounded lifetimes and persisted login budgets."""
from contextlib import closing, contextmanager
import hashlib
import hmac
import re
import secrets
from threading import BoundedSemaphore

from pwdlib import PasswordHash

from .storage import Store, WebError

IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 12 * 60 * 60
ANONYMOUS_SECONDS = 10 * 60
TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
PASSWORDS = PasswordHash.recommended()


def password_hash(value):
    if not isinstance(value, str) or not 14 <= len(value) <= 256:
        raise ValueError("Owner passwords must contain 14-256 characters")
    return PASSWORDS.hash(value)


def valid_username(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", value))


class Auth:
    def __init__(self, store: Store):
        self.store = store
        self.hash_slots = BoundedSemaphore(2)
        # An unknown account still pays password-verification work.
        self.dummy_hash = PASSWORDS.hash(secrets.token_urlsafe(32))

    @contextmanager
    def hash_slot(self):
        if not self.hash_slots.acquire(blocking=False):
            raise WebError(429, "authentication_busy", "Authentication capacity is busy; try again later")
        try:
            yield
        finally:
            self.hash_slots.release()

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def csrf(self, token):
        return hmac.new(self.store.csrf_key, b"csrf-v1:" + token.encode(), hashlib.sha256).hexdigest()

    def session(self, token, *, authenticated=True):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            return None
        with closing(self.store.connect()) as conn:
            row = conn.execute("""SELECT s.*,o.username,o.credential_version AS current_version
                FROM sessions s LEFT JOIN owner o ON o.id=s.owner_id WHERE token_hash=?""", (self.digest(token),)).fetchone()
        if not row:
            return None
        now = self.store.clock()
        if (now >= row["expires_at"] or now < row["created_at"]
                or row["kind"] == "authenticated" and
                (now - row["last_activity"] >= IDLE_SECONDS or row["credential_version"] != row["current_version"])):
            return None
        if authenticated and row["kind"] != "authenticated":
            return None
        return dict(row)

    def require_csrf(self, token, provided):
        session = self.session(token, authenticated=False)
        if not session or not isinstance(provided, str) or not re.fullmatch(r"[a-f0-9]{64}", provided) or not hmac.compare_digest(self.csrf(token), provided):
            raise WebError(403, "csrf_rejected", "Invalid CSRF token")
        return session

    def budget(self, bucket, limit, window):
        now = self.store.clock()
        with self.store.transaction() as conn:
            # Old budgets do not accumulate indefinitely.
            conn.execute("DELETE FROM throttle WHERE started_at<?", (now - 3600,))
            row = conn.execute("SELECT * FROM throttle WHERE bucket=?", (bucket,)).fetchone()
            if row and now - row["started_at"] < window:
                if row["attempts"] >= limit:
                    raise WebError(429, "rate_limited", "Too many attempts; try again later")
                conn.execute("UPDATE throttle SET attempts=attempts+1 WHERE bucket=?", (bucket,))
            else:
                conn.execute("INSERT OR REPLACE INTO throttle VALUES(?,?,1)", (bucket, now))

    def peer_key(self, peer):
        # Only the transport peer, never X-Forwarded-For/Forwarded supplied by a client.
        return hmac.new(self.store.csrf_key, b"peer:" + peer.encode(), hashlib.sha256).hexdigest()

    def issue_anonymous(self, peer):
        self.budget("bootstrap:" + self.peer_key(peer), 60, 300)
        token = secrets.token_urlsafe(32)
        now = self.store.clock()
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            conn.execute("INSERT INTO sessions VALUES(?,?,NULL,NULL,?,?,?)",
                         (self.digest(token), "anonymous", now, now, now + ANONYMOUS_SECONDS))
        return token

    def login(self, old_token, username, supplied, peer):
        peer_bucket = "login:" + self.peer_key(peer)
        self.budget(peer_bucket, 5, 900)
        self.budget("login:instance", 20, 900)
        owner = self.store.owner()
        target = owner["password_hash"] if owner and username == owner["username"] else self.dummy_hash
        with self.hash_slot():
            try:
                verified = PASSWORDS.verify(supplied, target)
            except Exception:
                verified = False
        if not verified or not owner or username != owner["username"]:
            raise WebError(401, "invalid_credentials", "Invalid credentials")
        token = secrets.token_urlsafe(32)
        now = self.store.clock()
        with self.store.transaction() as conn:
            latest = conn.execute("SELECT credential_version FROM owner WHERE id=1").fetchone()
            if latest[0] != owner["credential_version"] or not self.session(old_token, authenticated=False):
                raise WebError(401, "session_changed", "Session changed; obtain a new CSRF token")
            conn.execute("DELETE FROM sessions WHERE token_hash=? OR expires_at<=?", (self.digest(old_token), now))
            conn.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?)", (self.digest(token), "authenticated", 1,
                         owner["credential_version"], now, now, now + ABSOLUTE_SECONDS))
            conn.execute("DELETE FROM throttle WHERE bucket IN (?,?)", (peer_bucket, "login:instance"))
        return token

    def logout(self, token):
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (self.digest(token),))

    def touch(self, token):
        if not self.session(token):
            raise WebError(401, "authentication_required", "Authentication required")
        with self.store.transaction() as conn:
            conn.execute("UPDATE sessions SET last_activity=? WHERE token_hash=?", (self.store.clock(), self.digest(token)))

    def change_password(self, token, current, replacement):
        owner = self.store.owner()
        with self.hash_slot():
            try:
                valid = PASSWORDS.verify(current, owner["password_hash"])
            except Exception:
                valid = False
            if not valid:
                raise WebError(401, "invalid_credentials", "Invalid credentials")
            updated = password_hash(replacement)
        with self.store.transaction() as conn:
            if not self.session(token):
                raise WebError(401, "authentication_required", "Authentication required")
            latest = conn.execute("SELECT credential_version FROM owner WHERE id=1").fetchone()
            if latest[0] != owner["credential_version"]:
                raise WebError(409, "credentials_changed", "Credentials changed; sign in again")
            conn.execute("UPDATE owner SET password_hash=?,credential_version=credential_version+1 WHERE id=1", (updated,))
            conn.execute("DELETE FROM sessions")
