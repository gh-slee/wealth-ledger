"""Closed frames and authenticated private-peer TLS for the ingestion boundary.

No caller command, image tag, host path or engine operation crosses this API.
Raw and result frames are memory-only. Framing does not certify containment;
the launcher must independently inspect and verify its actual Linux controls.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import ssl
import stat
import struct

from .codec import decode, encode, sha256, validate
from .contracts import (IngestionError, MAX_CHILD_HEADER, MAX_CONTEXT, MAX_CONTROL,
                        MAX_MINIMAL, MAX_RAW)


def _prefix(header, maximum):
    raw = encode(header)
    if not 0 < len(raw) <= maximum:
        raise IngestionError('import_limit')
    return struct.pack('!I', len(raw)) + raw


def pack_input(metadata, context, raw, *, schema='LaunchStart'):
    if schema not in {'LaunchStart', 'Handoff'}:
        raise IngestionError()
    metadata = validate(metadata, schema)
    if (type(context) is not bytes or type(raw) is not bytes
            or not 0 < len(context) <= MAX_CONTEXT or not 0 < len(raw) <= MAX_RAW):
        raise IngestionError('import_limit')
    if (len(context) != metadata['context_bytes'] or len(raw) != metadata['raw_bytes']
            or sha256(context) != metadata['context_sha256']
            or sha256(raw) != metadata['raw_sha256']):
        raise IngestionError()
    return _prefix(metadata, MAX_CONTROL) + context + raw


def _header(frame, schema, maximum):
    if type(frame) is not bytes or len(frame) < 4:
        raise IngestionError()
    size = struct.unpack('!I', frame[:4])[0]
    if not 0 < size <= maximum:
        raise IngestionError('import_limit')
    if len(frame) < 4 + size:
        raise IngestionError()
    return decode(frame[4:4 + size], schema, limit=maximum), 4 + size


def unpack_input(frame, *, schema='LaunchStart'):
    if schema not in {'LaunchStart', 'Handoff'}:
        raise IngestionError()
    if type(frame) is not bytes or len(frame) > 4 + MAX_CONTROL + MAX_CONTEXT + MAX_RAW:
        raise IngestionError('import_limit')
    metadata, offset = _header(frame, schema, MAX_CONTROL)
    context_end = offset + metadata['context_bytes']
    if context_end + metadata['raw_bytes'] != len(frame):
        raise IngestionError()
    context, raw = frame[offset:context_end], frame[context_end:]
    if sha256(context) != metadata['context_sha256'] or sha256(raw) != metadata['raw_sha256']:
        raise IngestionError()
    # The actual discriminator is read from closed JSON, never from executable code.
    from ..data_sources.contract_v1 import ContractError, load_json
    try:
        primitive = load_json(context, limit=MAX_CONTEXT)
        context_schema = {'parser_v2': 'ParserChildContext',
                          'native_discovery_v1': 'NativeChildContext'}[primitive['payload_kind']]
    except (ContractError, KeyError, TypeError):
        raise IngestionError() from None
    context_value = decode(context, context_schema, limit=MAX_CONTEXT)
    for key in ('job_id', 'member_id', 'fence', 'installation_id', 'image_digest',
                'wrapper_profile_digest', 'format_version'):
        if key in metadata and metadata[key] != context_value[key]:
            raise IngestionError()
    return metadata, context, raw


def pack_result(header, payload, *, child=False):
    header = validate(header, 'ChildResult' if child else 'LaunchResult')
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_MINIMAL:
        raise IngestionError('import_limit')
    if len(payload) != header['payload_bytes'] or sha256(payload) != header['payload_sha256']:
        raise IngestionError()
    return _prefix(header, MAX_CHILD_HEADER) + payload


def unpack_result(frame, expected, *, child=False, exit_code=0, overflow=False):
    """Check complete exit and byte/binding/hash bounds before payload admission."""
    if overflow or (type(frame) is bytes and len(frame) > 4 + MAX_CHILD_HEADER + MAX_MINIMAL):
        raise IngestionError('import_limit')
    if type(exit_code) is not int or exit_code != 0:
        raise IngestionError('import_runner_unavailable')
    header, offset = _header(frame, 'ChildResult' if child else 'LaunchResult', MAX_CHILD_HEADER)
    if len(frame) - offset != header['payload_bytes']:
        raise IngestionError()
    for name in ('job_id', 'member_id', 'fence', 'installation_id', 'image_digest',
                 'wrapper_profile_digest', 'raw_sha256', 'context_sha256', 'payload_kind'):
        if name not in expected or header[name] != expected[name]:
            raise IngestionError()
    if not child and ('handle' not in expected or header['handle'] != expected['handle']):
        raise IngestionError()
    payload = frame[offset:]
    if sha256(payload) != header['payload_sha256']:
        raise IngestionError()
    return header, payload


class ChildOutputCollector:
    """Bound stdout and drain stderr without storing or reporting stderr bytes."""

    def __init__(self):
        self._stdout = bytearray()
        self.stdout_overflow = False
        self.stderr_overflow = False
        self.stderr_bytes = 0

    def stdout(self, chunk):
        if type(chunk) is not bytes:
            raise IngestionError()
        capacity = 4 + MAX_CHILD_HEADER + MAX_MINIMAL - len(self._stdout)
        if len(chunk) > capacity:
            self.stdout_overflow = True
        self._stdout.extend(chunk[:capacity])

    def stderr(self, chunk):
        if type(chunk) is not bytes:
            raise IngestionError()
        self.stderr_bytes = min(65537, self.stderr_bytes + len(chunk))
        self.stderr_overflow = self.stderr_bytes > 65536

    def finish(self, expected, *, exit_code):
        try:
            return unpack_result(bytes(self._stdout), expected, child=True, exit_code=exit_code,
                                 overflow=self.stdout_overflow or self.stderr_overflow)
        finally:
            self._stdout.clear()


@dataclass(frozen=True, slots=True)
class PeerTLS:
    ca_file: Path
    cert_file: Path
    key_file: Path
    peer_dns: str
    instance_id: str
    peer_role: str

    def context(self, *, server=False):
        validate(self.instance_id, 'UUID')
        if self.peer_role not in {'api', 'worker', 'launcher'} or not self.peer_dns:
            raise IngestionError('import_runner_unavailable')
        try:
            key = self.key_file.lstat()
            if (not stat.S_ISREG(key.st_mode) or key.st_uid != os.getuid()
                    or key.st_mode & 0o077 or key.st_nlink != 1):
                raise ValueError()
            purpose = ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH
            context = ssl.create_default_context(purpose, cafile=str(self.ca_file))
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
            context.verify_mode = ssl.CERT_REQUIRED
            context.check_hostname = not server
            context.load_cert_chain(str(self.cert_file), str(self.key_file))
            return context
        except (OSError, ssl.SSLError, ValueError):
            raise IngestionError('import_runner_unavailable') from None

    def verify_peer(self, connection):
        """After the verified TLS handshake, require the exact DNS and URI peer."""
        # Kept from the pre-Kurafolio name: URI SAN in runner certificates operators have already issued.
        uri = f'urn:wealth-ledger:instance:{self.instance_id}:peer:{self.peer_role}'
        try:
            if connection.version() != 'TLSv1.3':
                raise ValueError()
            certificate = connection.getpeercert()
            sans = certificate.get('subjectAltName', ())
            dns = [value for kind, value in sans if kind == 'DNS']
            uris = [value for kind, value in sans if kind == 'URI']
            if dns != [self.peer_dns] or uris != [uri]:
                raise ValueError()
        except (AttributeError, ValueError, ssl.SSLError):
            raise IngestionError('import_runner_unavailable') from None
