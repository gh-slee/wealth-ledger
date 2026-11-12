"""Signed, scope-bound page cursors for V2 import reads.

A cursor is a canonical JSON payload and an HMAC over those exact bytes, both
unpadded base64url and joined by a dot. It is signed, not encrypted, and holds
only opaque IDs, fixed filters, a position and an expiry: never financial values.
A valid MAC grants nothing by itself. The SQL read function rechecks the
principal, portfolio, realm, filter, resource revision and expiry against live
authentication before using the position.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re

from .codec import IngestionError, _load, encode

PURPOSE = b'wealth-ledger/ingestion-cursor-v1'
MAX_TOKEN = 1024
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.ASCII)
_HASH = re.compile(r'[0-9a-f]{64}', re.ASCII)
_COUNTER = re.compile(r'(0|[1-9][0-9]{0,18})', re.ASCII)
_AFTER = re.compile(r'[0-9a-f:-]{1,128}', re.ASCII)
_INSTANT = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00:00', re.ASCII)
_B64 = re.compile(r'[A-Za-z0-9_-]+', re.ASCII)
STATES = ('RECEIVING', 'NORMALIZING', 'RECONCILING', 'NEEDS_MAPPING', 'CONFLICT', 'READY',
          'COMMITTED', 'REJECTED', 'CANCELLED', 'EXPIRED')
FIELDS = ('after_key', 'expires_at', 'filter', 'portfolio_id', 'realm_digest', 'resource_id',
          'resource_revision', 'review_digest', 'user_id', 'version')


def derive_key(secret):
    """The dedicated cursor key; the instance secret itself never signs a cursor."""
    if type(secret) is not bytes or len(secret) < 32:
        raise ValueError('Cursor secret required')
    return hmac.new(secret, PURPOSE, hashlib.sha256).digest()


def _check(payload):
    def exact(name, pattern, nullable=False):
        value = payload[name]
        if value is None and nullable:
            return
        if type(value) is not str or not pattern.fullmatch(value):
            raise IngestionError('import_invalid')
    if type(payload) is not dict or sorted(payload) != list(FIELDS) or payload['version'] != 1 or \
            type(payload['version']) is not int:
        raise IngestionError('import_invalid')
    exact('user_id', _UUID)
    exact('portfolio_id', _UUID)
    exact('realm_digest', _HASH)
    exact('resource_id', _UUID, True)
    exact('resource_revision', _COUNTER, True)
    exact('review_digest', _HASH, True)
    exact('after_key', _AFTER)
    exact('expires_at', _INSTANT)
    if payload['filter'] is not None and payload['filter'] not in STATES:
        raise IngestionError('import_invalid')
    if (payload['resource_id'] is None) != (payload['resource_revision'] is None) or \
            (payload['resource_id'] is None) != (payload['review_digest'] is None):
        raise IngestionError('import_invalid')
    return payload


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _unb64(text):
    if not _B64.fullmatch(text) or len(text) % 4 == 1:
        raise IngestionError('import_invalid')
    data = base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    # Reject alternative spellings of the same bytes (nonzero padding bits).
    if _b64(data) != text:
        raise IngestionError('import_invalid')
    return data


def sign(key, payload):
    """Sign a SQL-produced next-page payload after checking its closed shape."""
    data = encode(_check(payload))
    token = _b64(data) + '.' + _b64(hmac.new(key, data, hashlib.sha256).digest())
    if len(token) > MAX_TOKEN:
        raise IngestionError('import_limit')
    return token


def verify(key, token):
    """Return the payload of an authentic canonical token; the MAC is checked first."""
    if type(token) is not str or not 1 <= len(token) <= MAX_TOKEN or token.count('.') != 1:
        raise IngestionError('import_invalid')
    body, mac = token.split('.')
    data, supplied = _unb64(body), _unb64(mac)
    if not hmac.compare_digest(hmac.new(key, data, hashlib.sha256).digest(), supplied):
        raise IngestionError('import_invalid')
    return _check(_load(data, MAX_TOKEN))
