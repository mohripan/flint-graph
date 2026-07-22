from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.domain.enums import (
    AliasSource,
    ClaimStatus,
    EntityStatus,
    EntityType,
    MentionResolutionStatus,
    MergeCandidateBand,
    MergeCandidateStatus,
    MergeDecisionSource,
    MergeDecisionType,
    RelationshipStatus,
    SourceType,
)
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    Claim,
    Document,
    DocumentVersion,
    EntityAlias,
    EntityMention,
    EntityRelationship,
    MergeCandidate,
    MergeDecision,
    Tenant,
)


async def _seed_document(session: AsyncSession) -> tuple[Tenant, Document, DocumentVersion]:
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


async def test_full_graph_chain_persists_and_reads_back(db_session: AsyncSession) -> None:
    tenant, document, version = await _seed_document(db_session)

    subject = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Acme Corporation",
        normalized_name="acme corporation",
        status=EntityStatus.ACTIVE,
    )
    obj = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.PLACE,
        canonical_name="Berlin",
        normalized_name="berlin",
        status=EntityStatus.ACTIVE,
    )
    db_session.add_all([subject, obj])
    await db_session.flush()

    db_session.add(
        EntityAlias(
            tenant_id=tenant.id,
            canonical_entity_id=subject.id,
            surface_form="Acme Corp",
            normalized_form="acme corp",
            source=AliasSource.EXTRACTION,
        )
    )

    subject_mention = EntityMention(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        surface_text="Acme Corp",
        normalized_text="acme corp",
        entity_type=EntityType.ORGANIZATION,
        chunk_ids=["c1"],
        resolved_entity_id=subject.id,
        resolution_status=MentionResolutionStatus.RESOLVED,
    )
    object_mention = EntityMention(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        surface_text="Berlin",
        normalized_text="berlin",
        entity_type=EntityType.PLACE,
        chunk_ids=["c1"],
        resolved_entity_id=obj.id,
        resolution_status=MentionResolutionStatus.RESOLVED,
    )
    db_session.add_all([subject_mention, object_mention])
    await db_session.flush()

    db_session.add(
        Claim(
            tenant_id=tenant.id,
            document_id=document.id,
            document_version_id=version.id,
            subject_mention_id=subject_mention.id,
            predicate="headquartered_in",
            object_mention_id=object_mention.id,
            claim_text="Acme Corp is headquartered in Berlin.",
            evidence_chunk_ids=["c1"],
            status=ClaimStatus.LINKED,
        )
    )
    db_session.add(
        EntityRelationship(
            tenant_id=tenant.id,
            subject_entity_id=subject.id,
            predicate="headquartered_in",
            object_entity_id=obj.id,
            support_count=1,
            provenance=[{"document_version_id": str(version.id)}],
            status=RelationshipStatus.ACTIVE,
        )
    )

    candidate = MergeCandidate(
        tenant_id=tenant.id,
        mention_id=subject_mention.id,
        target_entity_id=subject.id,
        score=0.92,
        features={"name_similarity": 1.0, "type_match": True},
        band=MergeCandidateBand.AUTO,
        status=MergeCandidateStatus.APPLIED,
    )
    db_session.add(candidate)
    await db_session.flush()

    db_session.add(
        MergeDecision(
            tenant_id=tenant.id,
            candidate_id=candidate.id,
            decision_type=MergeDecisionType.ATTACH,
            source=MergeDecisionSource.AUTO,
            actor="resolver",
            reason="score above auto threshold",
            payload={"mention_id": str(subject_mention.id)},
        )
    )
    await db_session.commit()

    relationship = (
        await db_session.execute(select(EntityRelationship))
    ).scalar_one()
    assert relationship.subject_entity_id == subject.id
    assert relationship.object_entity_id == obj.id
    assert relationship.provenance == [{"document_version_id": str(version.id)}]

    decision = (await db_session.execute(select(MergeDecision))).scalar_one()
    assert decision.candidate_id == candidate.id
    assert decision.decision_type == MergeDecisionType.ATTACH


async def test_soft_merge_pointer_links_entities(db_session: AsyncSession) -> None:
    tenant, _document, _version = await _seed_document(db_session)

    survivor = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.PERSON,
        canonical_name="Jane Doe",
        normalized_name="jane doe",
    )
    duplicate = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.PERSON,
        canonical_name="J. Doe",
        normalized_name="j doe",
    )
    db_session.add_all([survivor, duplicate])
    await db_session.flush()

    duplicate.merged_into_id = survivor.id
    duplicate.status = EntityStatus.MERGED
    await db_session.commit()

    reloaded = (
        await db_session.execute(
            select(CanonicalEntity).where(CanonicalEntity.id == duplicate.id)
        )
    ).scalar_one()
    assert reloaded.status == EntityStatus.MERGED
    assert reloaded.merged_into_id == survivor.id
