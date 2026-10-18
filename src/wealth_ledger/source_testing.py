"""Offline parser-author assertions; structural evidence, never ledger acceptance.

These helpers do not sandbox Python or prove the absence of side effects. Use only
reviewed trusted adapters and synthetic fixtures, in a disposable test environment.
"""
from dataclasses import dataclass
import hashlib

from .source_protocol import canonical_json, resolve_detection, validate_batch, validate_info


@dataclass(frozen=True)
class ContractResult:
    export_version: str
    normalized_sha256: str
    record_count: int
    coverage_count: int


def check_contract(adapter, raw: bytes) -> ContractResult:
    """Check detection, validation, byte-identical replay and declared metadata.

    Do not include a clock-generated fetched_at in v1 output. V2 will carry host
    parse context. Changing raw input changes its evidence hash, even on overlap.
    """
    validate_info(adapter.info)
    first = adapter.detect(raw)
    _, detected = resolve_detection(((adapter.info, first),))
    if adapter.detect(raw) != first:
        raise AssertionError("Detector is not deterministic")
    batches = [adapter.normalize(raw, export_version=detected.export_version) for _ in range(2)]
    for batch in batches:
        validate_batch(batch, raw)
        if batch.adapter != adapter.info:
            raise AssertionError("Normalized adapter metadata differs from registration")
        if batch.export_version != detected.export_version:
            raise AssertionError("Normalized export version differs from detection")
    encoded = [canonical_json(batch) for batch in batches]
    if encoded[0] != encoded[1]:
        raise AssertionError("Normalization is not deterministic")
    return ContractResult(detected.export_version, hashlib.sha256(encoded[0].encode()).hexdigest(),
                          len(batches[0].records), len(batches[0].coverage))


def check_rejected(adapter, raw: bytes, *, export_version: str):
    """A bad fixture must not produce a structurally accepted normalized batch.

    Only ValueError is an expected format rejection; implementation bugs propagate.
    """
    try:
        batch = adapter.normalize(raw, export_version=export_version)
        validate_batch(batch, raw)
        if batch.adapter != adapter.info or batch.export_version != export_version:
            raise AssertionError("Parser returned mismatched metadata instead of rejecting input")
    except ValueError:
        return
    raise AssertionError("Invalid source fixture was accepted")


def record_index(batch, raw: bytes):
    """Validated source identities for fixture overlap/revision assertions.

    No stateful deduplication, revision-lineage resolution, transfer matching or
    contribution inference is performed. Those need the central ledger in SRC-004.
    """
    validate_batch(batch, raw)
    return {(record.key.account, record.kind, record.key.source_id): record for record in batch.records}
