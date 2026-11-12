"""Explicit host construction of built-in metadata; never called by source menus."""
from .contract_v1 import Descriptor, validate_descriptor


def builtin_descriptors(*, package_distribution, package_version, artifact_sha256,
                        execution_image_digest, entry_point_target):
    from ..source_builtin import registrations
    result = []
    for registration in registrations():
        info = registration.adapter.info
        categories = ("CASH", "SECURITY") if info.provider_id == "wealthsimple" else ("CASH", "CRYPTO")
        result.append(validate_descriptor(Descriptor(1, info.provider_id, info.provider_id,
            info.adapter_id, package_distribution, package_version, info.adapter_id,
            entry_point_target, artifact_sha256, execution_image_digest, 1, 1,
            info.api_version, "parser_v2", ("FILE_IMPORT",), tuple(sorted(info.export_versions)),
            categories, "forbidden" if info.provider_id == "wealthsimple" else "required", "reviewed-file-v1")))
    return tuple(result)



def parser_provenance(raw,canonical_bytes,batch,context):
    """Project the unchanged bridge's evidence before any mapping may block it."""
    import hashlib
    from ..domain import canonical_v1 as domain
    digest=hashlib.sha256(canonical_bytes).hexdigest()
    def legacy(value,field):
        return domain.LegacyDateTimeV1(value.isoformat(),domain.LegacyRecordRefV1(digest,'evidence',None,field))
    if batch.evidence.effective_at is None:
        return None  # The unchanged bridge determines its typed time blocker.
    return domain.ProvenanceV1(hashlib.sha256(raw).hexdigest(),digest,batch.adapter.provider_id,
        batch.adapter.adapter_id,batch.adapter.adapter_version,batch.export_version,context.evidence_reference,
        legacy(batch.evidence.effective_at,'effective_at'),legacy(batch.evidence.context.evidence_at,'context.evidence_at'),
        context.binding_context.value.imported_at,context.binding_context.value.accepted_at,
        domain.LegacyRecordRefV1(digest,'batch',None,''))
