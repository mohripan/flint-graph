from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.extraction import (
    ExtractedClaim,
    ExtractedDocumentFacts,
    ExtractedEntity,
)
from atlas_rag.application.services.mentions import persist_mentions_and_claims
from atlas_rag.domain.enums import (
    DocumentArtifactType,
    EntityType,
    MentionResolutionStatus,
    SourceType,
)
from atlas_rag.domain.errors import NotFoundError
from atlas_rag.infrastructure.db.models import (
    Claim,
    Document,
    DocumentArtifact,
    DocumentVersion,
    EntityMention,
    Tenant,
)


async def _seed(session: AsyncSession) -> tuple[Tenant, Document, DocumentVersion]:
    tenant = Tenant(name="acme")
    session.add(tenant)
    await session.flush()
    document = Document(
        tenant_id=tenant.id,
        title="Doc",
        source_type=SourceType.UPLOAD,
        next_version_number=1,
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(document_id=document.id, version_number=1)
    session.add(version)
    await session.flush()
    return tenant, document, version


def _facts() -> ExtractedDocumentFacts:
    return ExtractedDocumentFacts(
        summary="Acme Corp is headquartered in Berlin and led by Jane Doe.",
        entities=[
            ExtractedEntity(name="Acme Corp", type="organization"),
            ExtractedEntity(name="Berlin", type="place"),
        ],
        claims=[
            ExtractedClaim(
                subject="Acme Corp",
                predicate="headquartered_in",
                object="Berlin",
                evidence_chunk_ids=["chunk-000001"],
            ),
            ExtractedClaim(
                subject="Acme Corp",
                predicate="founded_in_year",
                object="1998",
                evidence_chunk_ids=["chunk-000002"],
            ),
            ExtractedClaim(
                subject="Jane Doe",
                predicate="leads",
                object="Acme Corp",
                evidence_chunk_ids=["chunk-000001"],
            ),
        ],
    )


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))  # type: ignore[return-value]


async def test_persist_creates_mentions_and_links_claims(db_session: AsyncSession) -> None:
    tenant, document, version = await _seed(db_session)
    artifact = DocumentArtifact(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        artifact_type=DocumentArtifactType.EXTRACTION,
        object_uri="s3://atlas-rag/x/artifacts/extraction.json",
        content_hash="sha256:abc",
        size_bytes=10,
        schema_version="2",
        metadata_={},
    )
    db_session.add(artifact)
    await db_session.flush()

    result = await persist_mentions_and_claims(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        version_id=version.id,
        extraction=_facts(),
        source_artifact_id=artifact.id,
        prompt_hash="sha256:prompt",
        response_hash="sha256:response",
    )
    await db_session.commit()

    assert result.mention_count == 3
    assert result.claim_count == 3

    mentions = {
        m.normalized_text: m
        for m in (await db_session.execute(select(EntityMention))).scalars()
    }
    assert set(mentions) == {"acme corp", "berlin", "jane doe"}
    assert mentions["acme corp"].entity_type == EntityType.ORGANIZATION
    assert mentions["berlin"].entity_type == EntityType.PLACE
    # Jane Doe only appears as a claim subject, not in entities -> typed other.
    assert mentions["jane doe"].entity_type == EntityType.OTHER
    # Provenance propagates onto every mention.
    assert mentions["acme corp"].source_artifact_id == artifact.id
    assert mentions["acme corp"].prompt_hash == "sha256:prompt"
    assert mentions["acme corp"].response_hash == "sha256:response"
    assert mentions["berlin"].resolution_status == MentionResolutionStatus.PENDING
    # Evidence chunk ids aggregate across every claim that names the surface.
    assert mentions["acme corp"].chunk_ids == ["chunk-000001", "chunk-000002"]

    claims = {c.predicate: c for c in (await db_session.execute(select(Claim))).scalars()}
    assert claims["headquartered_in"].object_mention_id == mentions["berlin"].id
    assert claims["headquartered_in"].object_literal is None
    # "1998" is not an extracted entity, so it is stored as a literal object.
    assert claims["founded_in_year"].object_mention_id is None
    assert claims["founded_in_year"].object_literal == "1998"
    assert claims["leads"].subject_mention_id == mentions["jane doe"].id
    assert claims["leads"].object_mention_id == mentions["acme corp"].id


async def test_persist_is_idempotent_per_version(db_session: AsyncSession) -> None:
    tenant, document, version = await _seed(db_session)

    for _ in range(2):
        result = await persist_mentions_and_claims(
            db_session,
            tenant_id=tenant.id,
            document_id=document.id,
            version_id=version.id,
            extraction=_facts(),
            source_artifact_id=None,
            prompt_hash=None,
            response_hash=None,
        )
    await db_session.commit()

    assert result.mention_count == 3
    assert await _count(db_session, EntityMention) == 3
    assert await _count(db_session, Claim) == 3


async def test_persist_none_extraction_clears_existing(db_session: AsyncSession) -> None:
    tenant, document, version = await _seed(db_session)
    await persist_mentions_and_claims(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        version_id=version.id,
        extraction=_facts(),
        source_artifact_id=None,
        prompt_hash=None,
        response_hash=None,
    )
    await db_session.flush()

    result = await persist_mentions_and_claims(
        db_session,
        tenant_id=tenant.id,
        document_id=document.id,
        version_id=version.id,
        extraction=None,
        source_artifact_id=None,
        prompt_hash=None,
        response_hash=None,
    )
    await db_session.commit()

    assert result == type(result)(mention_count=0, claim_count=0)
    assert await _count(db_session, EntityMention) == 0
    assert await _count(db_session, Claim) == 0


async def test_persist_rejects_unknown_version(db_session: AsyncSession) -> None:
    tenant, document, _version = await _seed(db_session)
    missing_version = UUID("99999999-9999-4999-8999-999999999999")

    with pytest.raises(NotFoundError, match="was not found"):
        await persist_mentions_and_claims(
            db_session,
            tenant_id=tenant.id,
            document_id=document.id,
            version_id=missing_version,
            extraction=_facts(),
            source_artifact_id=None,
            prompt_hash=None,
            response_hash=None,
        )
