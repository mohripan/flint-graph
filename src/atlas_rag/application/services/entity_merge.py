from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.domain.enums import (
    AliasSource,
    EntityStatus,
    MergeDecisionSource,
    MergeDecisionType,
)
from atlas_rag.domain.errors import BadRequestError, NotFoundError
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    EntityAlias,
    EntityMention,
    EntityRelationship,
    MergeDecision,
)


async def merge_entities(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    source_entity_id: UUID,
    target_entity_id: UUID,
    source: MergeDecisionSource,
    actor: str,
    reason: str,
) -> None:
    """Soft-merge ``source`` into ``target`` and record a reversible decision.

    The source keeps a ``merged_into_id`` pointer and status ``merged`` (no rows
    are destroyed), while its aliases, mentions, and relationships are re-parented
    onto the target. Duplicate aliases and relationships are folded into the
    target's, and relationships that would become self-loops are dropped.
    """

    if source_entity_id == target_entity_id:
        raise BadRequestError("Cannot merge an entity into itself.")

    source_entity = await _load_active_entity(session, tenant_id, source_entity_id)
    target_entity = await _load_active_entity(session, tenant_id, target_entity_id)

    await _reparent_aliases(session, tenant_id, source_entity, target_entity)
    await session.execute(
        update(EntityMention)
        .where(
            EntityMention.tenant_id == tenant_id,
            EntityMention.resolved_entity_id == source_entity_id,
        )
        .values(resolved_entity_id=target_entity_id)
    )
    await _reparent_relationships(session, tenant_id, source_entity_id, target_entity_id)

    target_entity.support_count += source_entity.support_count
    source_entity.support_count = 0
    source_entity.status = EntityStatus.MERGED
    source_entity.merged_into_id = target_entity_id

    session.add(
        MergeDecision(
            tenant_id=tenant_id,
            candidate_id=None,
            decision_type=MergeDecisionType.MERGE,
            source=source,
            actor=actor,
            reason=reason,
            payload={
                "source_entity_id": str(source_entity_id),
                "target_entity_id": str(target_entity_id),
            },
        )
    )
    await session.flush()


async def _load_active_entity(
    session: AsyncSession, tenant_id: UUID, entity_id: UUID
) -> CanonicalEntity:
    entity = await session.get(CanonicalEntity, entity_id)
    if entity is None or entity.tenant_id != tenant_id:
        raise NotFoundError(f"Canonical entity '{entity_id}' was not found.")
    if entity.status != EntityStatus.ACTIVE:
        raise BadRequestError(f"Canonical entity '{entity_id}' is not active.")
    return entity


async def _reparent_aliases(
    session: AsyncSession,
    tenant_id: UUID,
    source_entity: CanonicalEntity,
    target_entity: CanonicalEntity,
) -> None:
    target_forms = set(
        (
            await session.execute(
                select(EntityAlias.normalized_form).where(
                    EntityAlias.canonical_entity_id == target_entity.id
                )
            )
        )
        .scalars()
        .all()
    )
    source_aliases = list(
        (
            await session.execute(
                select(EntityAlias).where(EntityAlias.canonical_entity_id == source_entity.id)
            )
        )
        .scalars()
        .all()
    )
    # Preserve the source's own canonical name as an alias of the target.
    source_aliases.append(
        EntityAlias(
            tenant_id=tenant_id,
            canonical_entity_id=source_entity.id,
            surface_form=source_entity.canonical_name,
            normalized_form=source_entity.normalized_name,
            source=AliasSource.MERGE,
        )
    )
    for alias in source_aliases:
        if alias.normalized_form in target_forms:
            if alias.id is not None:
                await session.delete(alias)
            continue
        alias.canonical_entity_id = target_entity.id
        alias.source = AliasSource.MERGE
        if alias.id is None:
            session.add(alias)
        target_forms.add(alias.normalized_form)
    await session.flush()


async def _reparent_relationships(
    session: AsyncSession,
    tenant_id: UUID,
    source_entity_id: UUID,
    target_entity_id: UUID,
) -> None:
    relationships = list(
        (
            await session.execute(
                select(EntityRelationship).where(
                    EntityRelationship.tenant_id == tenant_id,
                    (EntityRelationship.subject_entity_id == source_entity_id)
                    | (EntityRelationship.object_entity_id == source_entity_id),
                )
            )
        )
        .scalars()
        .all()
    )
    for relationship in relationships:
        new_subject = (
            target_entity_id
            if relationship.subject_entity_id == source_entity_id
            else relationship.subject_entity_id
        )
        new_object = (
            target_entity_id
            if relationship.object_entity_id == source_entity_id
            else relationship.object_entity_id
        )
        if new_subject == new_object:
            await session.delete(relationship)
            continue
        existing = await session.scalar(
            select(EntityRelationship).where(
                EntityRelationship.tenant_id == tenant_id,
                EntityRelationship.subject_entity_id == new_subject,
                EntityRelationship.predicate == relationship.predicate,
                EntityRelationship.object_entity_id == new_object,
                EntityRelationship.id != relationship.id,
            )
        )
        if existing is not None:
            existing.support_count += relationship.support_count
            existing.provenance = [*existing.provenance, *relationship.provenance]
            await session.delete(relationship)
        else:
            relationship.subject_entity_id = new_subject
            relationship.object_entity_id = new_object
        await session.flush()
