from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.domain.enums import (
    EntityType,
    ExtractionRunStatus,
    SourceType,
    StagedProposalStatus,
)
from atlas_rag.infrastructure.db.models import (
    Document,
    DocumentVersion,
    EvidenceSpan,
    ExtractedEntity,
    ExtractedEntityEvidence,
    ExtractionRun,
    Tenant,
)


async def test_provenance_extraction_chain_persists_and_reads_back(
    db_session: AsyncSession,
) -> None:
    tenant = Tenant(name="provenance")
    db_session.add(tenant)
    await db_session.flush()

    document = Document(
        tenant_id=tenant.id,
        title="Doc",
        source_type=SourceType.UPLOAD,
        next_version_number=1,
    )
    db_session.add(document)
    await db_session.flush()

    version = DocumentVersion(document_id=document.id, version_number=1)
    db_session.add(version)
    await db_session.flush()

    run = ExtractionRun(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        status=ExtractionRunStatus.READY,
        schema_version="1",
        prompt_version="proposal-v1",
        extractor_version="deterministic-v1",
        model_provider="deterministic",
        model_name="deterministic",
        input_hash="sha256:input",
        manifest_uri="s3://bucket/manifest.json",
        manifest_hash="sha256:manifest",
        input_chunk_count=1,
        invocation_count=1,
        accepted_entity_count=1,
    )
    db_session.add(run)
    await db_session.flush()

    span = EvidenceSpan(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        extraction_run_id=run.id,
        stable_id="ev_abc",
        chunk_id="chunk-000001",
        quote="Acme Corporation",
        start_offset=0,
        end_offset=16,
        span_hash="sha256:span",
    )
    entity = ExtractedEntity(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        extraction_run_id=run.id,
        stable_id="xe_abc",
        local_id="e1",
        name="Acme Corporation",
        normalized_name="acme corporation",
        entity_type=EntityType.ORGANIZATION,
        aliases=["Acme"],
        confidence=0.9,
        attributes={"source": "test"},
        status=StagedProposalStatus.ACCEPTED,
    )
    db_session.add_all([span, entity])
    await db_session.flush()

    db_session.add(
        ExtractedEntityEvidence(
            tenant_id=tenant.id,
            extracted_entity_id=entity.id,
            evidence_span_id=span.id,
        )
    )
    await db_session.commit()

    reloaded = (await db_session.execute(select(ExtractedEntity))).scalar_one()
    assert reloaded.stable_id == "xe_abc"
    assert reloaded.aliases == ["Acme"]

    link = (await db_session.execute(select(ExtractedEntityEvidence))).scalar_one()
    assert link.extracted_entity_id == entity.id
    assert link.evidence_span_id == span.id
