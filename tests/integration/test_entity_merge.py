from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.services.entity_merge import merge_entities
from atlas_rag.domain.enums import (
    AliasSource,
    EntityStatus,
    EntityType,
    MergeDecisionSource,
    MergeDecisionType,
    RelationshipStatus,
    SourceType,
)
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    Document,
    DocumentVersion,
    EntityAlias,
    EntityMention,
    EntityRelationship,
    MergeDecision,
    Tenant,
)


async def _tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(name="acme")
    session.add(tenant)
    await session.flush()
    return tenant


async def _entity(
    session: AsyncSession, tenant: Tenant, name: str, normalized: str, *, support: int = 1
) -> CanonicalEntity:
    entity = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name=name,
        normalized_name=normalized,
        status=EntityStatus.ACTIVE,
        support_count=support,
    )
    session.add(entity)
    await session.flush()
    return entity


async def _relationship(
    session: AsyncSession,
    tenant: Tenant,
    subject: CanonicalEntity,
    obj: CanonicalEntity,
    *,
    support: int,
    provenance_id: str,
) -> None:
    session.add(
        EntityRelationship(
            tenant_id=tenant.id,
            subject_entity_id=subject.id,
            predicate="related_to",
            object_entity_id=obj.id,
            support_count=support,
            provenance=[{"claim_id": provenance_id}],
            status=RelationshipStatus.ACTIVE,
        )
    )
    await session.flush()


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))  # type: ignore[return-value]


async def test_merge_reparents_aliases_mentions_relationships(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    source = await _entity(db_session, tenant, "A Corp", "a corp", support=2)
    target = await _entity(db_session, tenant, "B Corp", "b corp", support=3)
    other = await _entity(db_session, tenant, "C Corp", "c corp")

    db_session.add(
        EntityAlias(
            tenant_id=tenant.id,
            canonical_entity_id=source.id,
            surface_form="A Corp Inc",
            normalized_form="a corp inc",
            source=AliasSource.EXTRACTION,
        )
    )
    document = Document(
        tenant_id=tenant.id, title="d", source_type=SourceType.UPLOAD, next_version_number=1
    )
    db_session.add(document)
    await db_session.flush()
    version = DocumentVersion(document_id=document.id, version_number=1)
    db_session.add(version)
    await db_session.flush()
    mention = EntityMention(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        surface_text="A Corp",
        normalized_text="a corp",
        entity_type=EntityType.ORGANIZATION,
        resolved_entity_id=source.id,
    )
    db_session.add(mention)
    await _relationship(db_session, tenant, source, other, support=1, provenance_id="p1")

    await merge_entities(
        db_session,
        tenant_id=tenant.id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        source=MergeDecisionSource.HUMAN,
        actor="reviewer",
        reason="duplicate organization",
    )
    await db_session.commit()

    await db_session.refresh(source)
    await db_session.refresh(target)
    assert source.status == EntityStatus.MERGED
    assert source.merged_into_id == target.id
    assert source.support_count == 0
    assert target.support_count == 5

    await db_session.refresh(mention)
    assert mention.resolved_entity_id == target.id

    target_alias_forms = set(
        (
            await db_session.execute(
                select(EntityAlias.normalized_form).where(
                    EntityAlias.canonical_entity_id == target.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {"a corp", "a corp inc"} <= target_alias_forms

    relationship = await db_session.scalar(select(EntityRelationship))
    assert relationship is not None
    assert relationship.subject_entity_id == target.id
    assert relationship.object_entity_id == other.id

    decision = await db_session.scalar(
        select(MergeDecision).where(MergeDecision.decision_type == MergeDecisionType.MERGE)
    )
    assert decision is not None
    assert decision.payload["source_entity_id"] == str(source.id)
    assert decision.payload["target_entity_id"] == str(target.id)


async def test_merge_folds_duplicate_relationships(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    source = await _entity(db_session, tenant, "A Corp", "a corp")
    target = await _entity(db_session, tenant, "B Corp", "b corp")
    other = await _entity(db_session, tenant, "C Corp", "c corp")
    await _relationship(db_session, tenant, source, other, support=2, provenance_id="p1")
    await _relationship(db_session, tenant, target, other, support=3, provenance_id="p2")

    await merge_entities(
        db_session,
        tenant_id=tenant.id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        source=MergeDecisionSource.AUTO,
        actor="resolver",
        reason="auto",
    )
    await db_session.commit()

    assert await _count(db_session, EntityRelationship) == 1
    relationship = await db_session.scalar(select(EntityRelationship))
    assert relationship is not None
    assert relationship.subject_entity_id == target.id
    assert relationship.support_count == 5
    assert len(relationship.provenance) == 2


async def test_merge_drops_self_loop_relationships(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    source = await _entity(db_session, tenant, "A Corp", "a corp")
    target = await _entity(db_session, tenant, "B Corp", "b corp")
    await _relationship(db_session, tenant, source, target, support=1, provenance_id="p1")

    await merge_entities(
        db_session,
        tenant_id=tenant.id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        source=MergeDecisionSource.AUTO,
        actor="resolver",
        reason="auto",
    )
    await db_session.commit()

    assert await _count(db_session, EntityRelationship) == 0
