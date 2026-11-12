"""Inert reviewed metadata; no entry-point imports, detection or network access."""
from __future__ import annotations

import hashlib
import os
import stat
from urllib.parse import urlsplit

from .contract_v1 import (Availability, CatalogSnapshot, ContractError, HASH, MAX_CONTEXT,
    MAX_COUNTER, NAMESPACE, canonical, counter, decode, digest, installation_id,
    load_json, primitive, validate_descriptor)


def _display(text):
    return (type(text) is str and 1 <= len(text) <= 100
            and not any(ord(ch) < 32 or ord(ch) == 127 for ch in text))


def validate_catalog(value):
    if type(value) is not CatalogSnapshot or decode(CatalogSnapshot, primitive(value)) != value:
        raise ContractError()
    counter(value.catalog_revision)
    if len(value.definitions) > 128 or len(value.installations) > 512:
        raise ContractError("source_transport_limit")
    ids = tuple(x.plugin_id for x in value.definitions)
    if ids != tuple(sorted(set(ids))):
        raise ContractError()
    definitions = {x.plugin_id: x for x in value.definitions}
    for definition in value.definitions:
        if (not NAMESPACE.fullmatch(definition.plugin_id) or not NAMESPACE.fullmatch(definition.provider_id)
                or not _display(definition.display_name) or not _display(definition.publisher_label)):
            raise ContractError()
        if definition.docs_url is not None:
            url = urlsplit(definition.docs_url)
            if (len(definition.docs_url) > 1024 or url.scheme != "https" or not url.netloc
                    or url.username is not None or url.password is not None
                    or any(ord(ch) < 33 or ord(ch) == 127 for ch in definition.docs_url)):
                raise ContractError()
    installations = {}
    for descriptor in value.installations:
        validate_descriptor(descriptor)
        definition = definitions.get(descriptor.plugin_id)
        if definition is None or definition.provider_id != descriptor.provider_id:
            raise ContractError()
        key = installation_id(descriptor)
        if key in installations:
            raise ContractError()
        installations[key] = descriptor
    if tuple(installations) != tuple(sorted(installations)):
        raise ContractError()
    if tuple(x.installation_id for x in value.availability) != tuple(sorted(installations)):
        raise ContractError()
    active = set()
    for entry in value.availability:
        counter(entry.availability_generation, minimum=1)
        if entry.status == "ACTIVE":
            descriptor = installations[entry.installation_id]
            for capability in descriptor.capabilities:
                key = (descriptor.plugin_id, capability)
                if key in active:
                    raise ContractError()
                active.add(key)
    if value.catalog_revision == "0" and (value.definitions or value.installations):
        raise ContractError()
    if len(canonical(primitive(value))) > MAX_CONTEXT:
        raise ContractError("source_transport_limit")
    return value


def decode_catalog(data):
    try:
        value = validate_catalog(decode(CatalogSnapshot, load_json(data)))
        if canonical(primitive(value)) != data:
            raise ContractError()
        return value
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise ContractError("source_context_invalid") from None


def catalog_digest(value):
    return digest(primitive(validate_catalog(value)))


def validate_transition(previous, proposed):
    """Operator snapshot rules: availability ABA cannot resurrect authorizations."""
    validate_catalog(previous); validate_catalog(proposed)
    if previous == proposed:
        return False
    if int(previous.catalog_revision) == MAX_COUNTER or int(proposed.catalog_revision) != int(previous.catalog_revision) + 1:
        raise ContractError()
    old_definitions = {x.plugin_id: x for x in previous.definitions}
    new_definitions = {x.plugin_id: x for x in proposed.definitions}
    for key, old in old_definitions.items():
        if key not in new_definitions or new_definitions[key].provider_id != old.provider_id:
            raise ContractError()
    old_descriptors = {installation_id(x): x for x in previous.installations}
    new_descriptors = {installation_id(x): x for x in proposed.installations}
    if any(new_descriptors.get(key) != value for key, value in old_descriptors.items()):
        raise ContractError()
    old_entries = {x.installation_id: x for x in previous.availability}
    for entry in proposed.availability:
        old = old_entries.get(entry.installation_id)
        expected = 1 if old is None else int(old.availability_generation) + (old.status != entry.status)
        if expected > MAX_COUNTER or int(entry.availability_generation) != expected:
            raise ContractError()
    return True


def active_installation(catalog, plugin_id, capability):
    availability = {x.installation_id: x for x in catalog.availability}
    for descriptor in catalog.installations:
        entry = availability[installation_id(descriptor)]
        if descriptor.plugin_id == plugin_id and capability in descriptor.capabilities and entry.status == "ACTIVE":
            return descriptor, entry
    return None


def read_catalog_file(path):
    """Explicit host operation only; a catalog is never read by module import."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_size > MAX_CONTEXT:
                raise ContractError()
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(MAX_CONTEXT + 1)
            return decode_catalog(data)
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError):
        raise ContractError("source_context_invalid") from None


def verify_content(descriptor, *, artifact_bytes, execution_image_digest):
    """The operator supplies actual reviewed bytes/immutable image proof, never a tag."""
    validate_descriptor(descriptor)
    if (type(artifact_bytes) is not bytes or not artifact_bytes
            or type(execution_image_digest) is not str
            or not HASH.fullmatch(execution_image_digest)
            or hashlib.sha256(artifact_bytes).hexdigest() != descriptor.artifact_sha256
            or execution_image_digest != descriptor.execution_image_digest):
        raise ContractError()
    return installation_id(descriptor)


# Proofs are host-only transient evidence. They never enter the source API,
# catalog descriptor, database credentials or a plugin's input context.
from dataclasses import dataclass, field
_PROOF_SEAL = object()


@dataclass(frozen=True, slots=True)
class ContentProof:
    installation_id: str
    artifact_sha256: str
    execution_image_digest: str
    files_sha256: str
    files_count: int
    _seal: object = field(default=None,repr=False,compare=False)


def proof_matches(descriptor, proof):
    return (type(proof) is ContentProof and proof._seal is _PROOF_SEAL
            and proof.installation_id==installation_id(descriptor)
            and proof.artifact_sha256==descriptor.artifact_sha256
            and proof.execution_image_digest==descriptor.execution_image_digest)


def verify_installation(descriptor, artifact_bytes, *, image_root):
    """Verify a canonical artifact manifest against a fresh STOPPED image copy.

    This explicit trusted-host operation needs Docker CLI; no container process
    or plugin is executed. All code/files below must already be operator-reviewed.
    It is content binding, not a malicious-code sandbox or publisher signature.
    """
    import io
    from pathlib import PurePosixPath
    import subprocess
    import tarfile
    import threading
    import time
    import uuid
    validate_descriptor(descriptor)
    if type(image_root) is not str or not image_root.startswith('/') or str(PurePosixPath(image_root))!=image_root or '..' in PurePosixPath(image_root).parts:
        raise ContractError()
    if len(image_root)>4096 or any(ord(ch)<32 or ord(ch)==127 for ch in image_root):
        raise ContractError()
    verify_content(descriptor,artifact_bytes=artifact_bytes,execution_image_digest=descriptor.execution_image_digest)
    manifest=load_json(artifact_bytes)
    if (type(manifest) is not dict or set(manifest)!={'format','package_distribution','package_version','entry_points','files'}
            or manifest['format']!='source-content-v1' or canonical(manifest)!=artifact_bytes
            or manifest['package_distribution']!=descriptor.package_distribution or manifest['package_version']!=descriptor.package_version
            or type(manifest['files']) is not list or not 1<=len(manifest['files'])<=10000
            or type(manifest['entry_points']) is not list):
        raise ContractError()
    point={'name':descriptor.entry_point_name,'target':descriptor.entry_point_target}
    if point not in manifest['entry_points'] or any(type(x) is not dict or set(x)!={'name','target'} for x in manifest['entry_points']):
        raise ContractError()
    expected={}
    for item in manifest['files']:
        if type(item) is not dict or set(item)!={'path','sha256'} or type(item['path']) is not str or type(item['sha256']) is not str or not HASH.fullmatch(item['sha256']):
            raise ContractError()
        path=PurePosixPath(item['path'])
        if (path.is_absolute() or not path.parts or str(path)!=item['path'] or '..' in path.parts
                or any(part in {'__pycache__','.'} for part in path.parts) or '\\' in item['path']
                or any(ord(ch)<32 or ord(ch)==127 for ch in item['path']) or item['path'] in expected):
            raise ContractError()
        expected[item['path']]=item['sha256']
    if list(expected)!=sorted(expected) or len({PurePosixPath(x).parts[0] for x in expected})>32:
        raise ContractError()
    module=descriptor.entry_point_target.split(':')[0].replace('.','/')
    if module+'.py' not in expected and module+'/__init__.py' not in expected:
        raise ContractError()
    image='sha256:'+descriptor.execution_image_digest
    name='wealth-ledger-source-proof-'+uuid.uuid4().hex
    created=False
    observed={}
    try:
        checked=subprocess.run(['docker','image','inspect','--format','{"id":{{json .Id}},"volumes":{{json (index .Config "Volumes")}}}',image],
            check=True,capture_output=True,timeout=10)
        if len(checked.stdout)>65536:
            raise ContractError()
        info=load_json(checked.stdout.strip(),limit=65536)
        if info!={'id':image,'volumes':None}:
            raise ContractError()
        subprocess.run(['docker','create','--name',name,'--label','wealth-ledger.test=source-content-proof',
            '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--user','10001:10001','--memory','256m','--memory-swap','256m','--cpus','1','--pids-limit','16',
            '--entrypoint','/usr/local/bin/python',image,'-I','-S','-c','pass'],check=True,capture_output=True,timeout=10)
        created=True
        for root in sorted({PurePosixPath(x).parts[0] for x in expected}):
            process=subprocess.Popen(['docker','cp',name+':'+image_root+'/'+root,'-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            timer=threading.Timer(10,process.kill);timer.start();stderr=bytearray()
            def drain():
                while True:
                    chunk=process.stderr.read(4096)
                    if not chunk:break
                    stderr.extend(chunk[:max(0,65536-len(stderr))])
            thread=threading.Thread(target=drain,daemon=True);thread.start()
            class Bounded:
                total=0
                def read(self,size=-1):
                    chunk=process.stdout.read(min(size if size>=0 else 65536,65536))
                    self.total+=len(chunk)
                    if self.total>64*1024*1024:
                        process.kill();raise ContractError()
                    return chunk
            try:
                with tarfile.open(fileobj=Bounded(),mode='r|*') as archive:
                    for member in archive:
                        path=str(PurePosixPath(member.name))
                        if member.isdir():continue
                        if (not member.isfile() or path not in expected or path in observed
                                or member.size<0 or member.size>8*1024*1024):
                            raise ContractError()
                        reader=archive.extractfile(member)
                        hasher=hashlib.sha256();total=0
                        while True:
                            chunk=reader.read(65536)
                            if not chunk:break
                            total+=len(chunk);hasher.update(chunk)
                            if total>8*1024*1024:raise ContractError()
                        if total!=member.size or hasher.hexdigest()!=expected[path]:
                            raise ContractError()
                        observed[path]=hasher.hexdigest()
                if process.wait(timeout=2)!=0:
                    raise ContractError()
            finally:
                timer.cancel()
                if process.poll() is None:process.kill()
                process.wait(timeout=5)
                process.stdout.close();process.stderr.close();thread.join(timeout=2)
        if observed!=expected:
            raise ContractError()
        return ContentProof(installation_id(descriptor),descriptor.artifact_sha256,descriptor.execution_image_digest,
                            digest([{'path':path,'sha256':expected[path]} for path in sorted(expected)]),len(expected),_PROOF_SEAL)
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError,tarfile.TarError):
        raise ContractError() from None
    finally:
        if created:
            # The generated name is unique and owned; never prune unknown resources.
            removed=subprocess.run(['docker','rm',name],capture_output=True,timeout=10)
            if removed.returncode:
                raise ContractError()
