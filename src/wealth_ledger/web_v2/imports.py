"""Memory-only ASGI upload primitives for the explicit ingestion profile.

Routes must complete host, origin, session and CSRF validation and acquire the
database-backed shared reservation before calling receive_raw. These helpers do
not install routes, authenticate a user, reserve capacity or grant acceptance.
"""
from __future__ import annotations

import asyncio
import re
import time

from wealth_ledger.ingestion.contracts import IngestionError, MAX_RAW


def upload_length(headers):
    """Inspect original ASGI headers without losing duplicate length fields."""
    values = {}
    for name, value in headers:
        if type(name) is not bytes or type(value) is not bytes:
            raise IngestionError('invalid_headers')
        values.setdefault(name.lower(), []).append(value)
    lengths = values.get(b'content-length', [])
    if len(lengths) > 1 or (lengths and b'transfer-encoding' in values):
        raise IngestionError('invalid_length')
    if not lengths:
        raise IngestionError('length_required')
    token = lengths[0]
    if re.fullmatch(rb'[0-9]{1,10}', token) is None or int(token) == 0:
        raise IngestionError('invalid_length')
    if int(token) > MAX_RAW:
        raise IngestionError('import_limit')
    types = values.get(b'content-type', [])
    if (len(types) != 1 or types[0].lower() != b'application/octet-stream'
            or b'content-encoding' in values or b'transfer-encoding' in values
            or b'expect' in values):
        raise IngestionError('unsupported_media_type')
    return int(token)


async def receive_raw(receive, headers, *, entered=None, total_seconds=30.0, idle_seconds=5.0):
    """Read exact bytes under fixed deadlines, with no framework body spool.

    Call only after live authorization and a scoped database reservation. Optional
    timing parameters may shorten the contract budgets for deterministic tests;
    they cannot lengthen them. The caller owns and must release a successful buffer.
    """
    size = upload_length(headers)
    if (type(total_seconds) not in (int, float) or type(idle_seconds) not in (int, float)
            or not 0 < total_seconds <= 30 or not 0 < idle_seconds <= 5):
        raise IngestionError('invalid_input')
    now = time.monotonic()
    entered = now if entered is None else entered
    if type(entered) not in (int, float) or not 0 <= entered <= now:
        raise IngestionError('invalid_input')
    deadline, progress_at = entered + total_seconds, now
    buffer = bytearray()
    try:
        while True:
            now = time.monotonic()
            remaining = min(deadline - now, progress_at + idle_seconds - now)
            if remaining <= 0:
                raise IngestionError('request_timeout')
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError:
                raise IngestionError('request_timeout') from None
            if type(message) is not dict or message.get('type') != 'http.request':
                raise IngestionError('invalid_length')
            body = message.get('body', b'')
            more = message.get('more_body', False)
            if type(body) is not bytes or type(more) is not bool or len(body) > size - len(buffer):
                raise IngestionError('invalid_length')
            if body:
                buffer.extend(body)
                progress_at = time.monotonic()
            if not more:
                if len(buffer) != size:
                    raise IngestionError('invalid_length')
                if time.monotonic() > deadline:
                    raise IngestionError('request_timeout')
                return bytes(buffer)
    finally:
        buffer.clear()
