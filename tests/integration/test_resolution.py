from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.entity_resolution import CandidateEntity, name_similarity, normalize_name
from atlas_rag.application.services.candidate_generation import load_candidate_entities
from atlas_rag.application.services.resolution import (
    ResolutionConfig,
    resolve_pending_mentions,
)
from atlas_rag.domain.enums import (
    ClaimStatus,
    EntityStatus,
    EntityType,
    MentionResolutionStatus,
    MergeCandidateBand,
    MergeCandidateStatus,
    SourceType,
)
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    Claim,
    Document,
    DocumentVersion,
    EntityAlias,
    EntityMention,
    MergeCandidate,
    Tenant,
)

DEFAULT_CONFIG = ResolutionConfig(
    auto_threshold=0.85, review_threshold=0.6, trigram_threshold=0.3, candidate_limit=20
)


async def _all_entities_provider(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    normalized_text: str,
    entity_type: EntityType,
    trigram_threshold: float,
    limit: int,
) -> list[CandidateEntity]:
    """SQLite-friendly stand-in for pg_trgm blocking: return all active same-type entities."""
    ids = list(
        (
            await session.execute(
                select(CanonicalEntity.id)
                .where(
                    CanonicalEntity.tenant_id == tenant_id,
                    CanonicalEntity.entity_type == entity_type,
                    CanonicalEntity.status == EntityStatus.ACTIVE,
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return await load_candidate_entities(session, entity_ids=ids) if ids else []


async def _tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(name="acme")
    session.add(tenant)
    await session.flush()
    return tenant


async def _document(session: AsyncSession, tenant: Tenant, external_id: str) -> DocumentVersion:
    document = Document(
        tenant_id=tenant.id,
        title=external_id,
        external_id=external_id,
        source_type=SourceType.UPLOAD,
        next_version_number=1,
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(document_id=document.id, version_number=1)
    session.add(version)
    await session.flush()
    return version


async def _mention(
    session: AsyncSession,
    tenant: Tenant,
    version: DocumentVersion,
    surface: str,
    entity_type: EntityType,
) -> EntityMention:
    mention = EntityMention(
        tenant_id=tenant.id,
        document_id=version.document_id,
        document_version_id=version.id,
        surface_text=surface,
        normalized_text=normalize_name(surface),
        entity_type=entity_type,
        resolution_status=MentionResolutionStatus.PENDING,
    )
    session.add(mention)
    await session.flush()
    return mention


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))  # type: ignore[return-value]


async def test_resolve_creates_new_entity_when_no_candidate(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    version = await _document(db_session, tenant, "doc-1")
    mention = await _mention(db_session, tenant, version, "Jane Doe", EntityType.PERSON)

    result = await resolve_pending_mentions(
        db_session,
        tenant_id=tenant.id,
        config=DEFAULT_CONFIG,
        candidate_provider=_all_entities_provider,
    )
    await db_session.commit()

    assert result.new_entities == 1
    entity = await db_session.scalar(select(CanonicalEntity))
    assert entity is not None
    assert entity.support_count == 1
    assert entity.normalized_name == "jane doe"
    await db_session.refresh(mention)
    assert mention.resolution_status == MentionResolutionStatus.RESOLVED
    assert mention.resolved_entity_id == entity.id
    assert await _count(db_session, EntityAlias) == 1


async def test_resolve_auto_attaches_same_entity_across_documents(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    version_one = await _document(db_session, tenant, "doc-1")
    version_two = await _document(db_session, tenant, "doc-2")
    mention_one = await _mention(
        db_session, tenant, version_one, "Acme Corporation", EntityType.ORGANIZATION
    )
    mention_two = await _mention(
        db_session, tenant, version_two, "Acme Corporation", EntityType.ORGANIZATION
    )

    result = await resolve_pending_mentions(
        db_session,
        tenant_id=tenant.id,
        config=DEFAULT_CONFIG,
        candidate_provider=_all_entities_provider,
    )
    await db_session.commit()

    assert result.new_entities == 1
    assert result.auto_attached == 1
    assert await _count(db_session, CanonicalEntity) == 1
    entity = await db_session.scalar(select(CanonicalEntity))
    assert entity is not None
    assert entity.support_count == 2
    await db_session.refresh(mention_one)
    await db_session.refresh(mention_two)
    assert mention_one.resolved_entity_id == entity.id
    assert mention_two.resolved_entity_id == entity.id
    # The identical surface is only registered as an alias once.
    assert await _count(db_session, EntityAlias) == 1


async def test_resolve_queues_midband_candidate_for_review(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    version = await _document(db_session, tenant, "doc-1")
    existing = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Acme Corp",
        normalized_name="acme corp",
        status=EntityStatus.ACTIVE,
        support_count=1,
    )
    db_session.add(existing)
    await db_session.flush()
    db_session.add(
        EntityAlias(
            tenant_id=tenant.id,
            canonical_entity_id=existing.id,
            surface_form="Acme Corp",
            normalized_form="acme corp",
        )
    )
    mention = await _mention(
        db_session, tenant, version, "Acme Corporation", EntityType.ORGANIZATION
    )

    similarity = name_similarity("acme corporation", "acme corp")
    config = ResolutionConfig(
        auto_threshold=min(1.0, similarity + 0.1),
        review_threshold=max(0.0, similarity - 0.1),
        trigram_threshold=0.3,
        candidate_limit=20,
    )
    result = await resolve_pending_mentions(
        db_session,
        tenant_id=tenant.id,
        config=config,
        candidate_provider=_all_entities_provider,
    )
    await db_session.commit()

    assert result.review_queued == 1
    assert result.new_entities == 0
    await db_session.refresh(mention)
    assert mention.resolution_status == MentionResolutionStatus.REVIEW
    assert mention.resolved_entity_id is None
    candidate = await db_session.scalar(select(MergeCandidate))
    assert candidate is not None
    assert candidate.band == MergeCandidateBand.REVIEW
    assert candidate.status == MergeCandidateStatus.PENDING
    assert candidate.target_entity_id == existing.id


async def test_resolve_is_idempotent(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    version = await _document(db_session, tenant, "doc-1")
    await _mention(db_session, tenant, version, "Jane Doe", EntityType.PERSON)

    first = await resolve_pending_mentions(
        db_session,
        tenant_id=tenant.id,
        config=DEFAULT_CONFIG,
        candidate_provider=_all_entities_provider,
    )
    second = await resolve_pending_mentions(
        db_session,
        tenant_id=tenant.id,
        config=DEFAULT_CONFIG,
        candidate_provider=_all_entities_provider,
    )
    await db_session.commit()

    assert first.mentions_processed == 1
    assert second.mentions_processed == 0
    assert await _count(db_session, CanonicalEntity) == 1


async def test_resolve_aggregates_claims_into_relationships(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    version = await _document(db_session, tenant, "doc-1")
    subject = await _mention(db_session, tenant, version, "Acme Corp", EntityType.ORGANIZATION)
    obj = await _mention(db_session, tenant, version, "Berlin", EntityType.PLACE)
    db_session.add(
        Claim(
            tenant_id=tenant.id,
            document_id=version.document_id,
            document_version_id=version.id,
            subject_mention_id=subject.id,
            predicate="headquartered_in",
            object_mention_id=obj.id,
            evidence_chunk_ids=["chunk-000001"],
            status=ClaimStatus.PENDING,
        )
    )
    await db_session.flush()

    result = await resolve_pending_mentions(
        db_session,
        tenant_id=tenant.id,
        config=DEFAULT_CONFIG,
        candidate_provider=_all_entities_provider,
    )
    await db_session.commit()

    assert result.relationships_upserted == 1
    from atlas_rag.infrastructure.db.models import EntityRelationship

    relationship = await db_session.scalar(select(EntityRelationship))
    assert relationship is not None
    assert relationship.predicate == "headquartered_in"
    assert relationship.support_count == 1
    assert relationship.provenance[0]["document_version_id"] == str(version.id)
    claim = await db_session.scalar(select(Claim))
    assert claim is not None
    assert claim.status == ClaimStatus.LINKED
