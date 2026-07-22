from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.domain.enums import (
    AliasSource,
    EntityStatus,
    MergeDecisionSource,
    MergeDecisionType,
    RelationshipStatus,
)
from flint_graph.domain.errors import BadRequestError, NotFoundError
from flint_graph.infrastructure.db.models import (
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
    """Soft-merge ``source`` into ``target`` and record a reversible undo log.

    The source keeps a ``merged_into_id`` pointer and status ``merged`` while its
    aliases, mentions, and relationships are re-parented onto the target. The merge
    decision payload records exactly what changed (moved mentions, alias actions,
    per-relationship repoint/fold/self-loop) so ``unmerge_entity`` can reverse it.
    """

    if source_entity_id == target_entity_id:
        raise BadRequestError("Cannot merge an entity into itself.")

    source_entity = await _load_active_entity(session, tenant_id, source_entity_id)
    target_entity = await _load_active_entity(session, tenant_id, target_entity_id)

    undo: dict[str, Any] = {
        "source_entity_id": str(source_entity_id),
        "target_entity_id": str(target_entity_id),
        "source_support_count": source_entity.support_count,
        "moved_mention_ids": [],
        "alias_actions": [],
        "relationship_actions": [],
    }

    moved_mentions = list(
        (
            await session.execute(
                select(EntityMention.id).where(
                    EntityMention.tenant_id == tenant_id,
                    EntityMention.resolved_entity_id == source_entity_id,
                )
            )
        )
        .scalars()
        .all()
    )
    undo["moved_mention_ids"] = [str(mention_id) for mention_id in moved_mentions]
    await session.execute(
        update(EntityMention)
        .where(
            EntityMention.tenant_id == tenant_id,
            EntityMention.resolved_entity_id == source_entity_id,
        )
        .values(resolved_entity_id=target_entity_id)
    )

    await _reparent_aliases(session, tenant_id, source_entity, target_entity, undo)
    await _reparent_relationships(session, tenant_id, source_entity_id, target_entity_id, undo)

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
            payload=undo,
        )
    )
    await session.flush()


async def unmerge_entity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    source_entity_id: UUID,
    actor: str,
    reason: str,
) -> None:
    """Reverse the most recent merge of ``source_entity_id`` using its undo log."""

    source_entity = await session.get(CanonicalEntity, source_entity_id)
    if source_entity is None or source_entity.tenant_id != tenant_id:
        raise NotFoundError(f"Canonical entity '{source_entity_id}' was not found.")
    if source_entity.status != EntityStatus.MERGED or source_entity.merged_into_id is None:
        raise BadRequestError(f"Canonical entity '{source_entity_id}' is not merged.")

    target_entity_id = source_entity.merged_into_id
    undo = await _latest_merge_payload(session, tenant_id, source_entity_id)
    if undo is None:
        raise BadRequestError("No merge decision found to reverse.")

    await _restore_relationships(session, tenant_id, undo["relationship_actions"])
    await _restore_aliases(session, tenant_id, source_entity_id, undo["alias_actions"])
    for mention_id in undo["moved_mention_ids"]:
        mention = await session.get(EntityMention, UUID(mention_id))
        if mention is not None:
            mention.resolved_entity_id = source_entity_id

    target_entity = await session.get(CanonicalEntity, target_entity_id)
    restored_support = int(undo["source_support_count"])
    if target_entity is not None:
        target_entity.support_count = max(0, target_entity.support_count - restored_support)
    source_entity.support_count = restored_support
    source_entity.status = EntityStatus.ACTIVE
    source_entity.merged_into_id = None

    session.add(
        MergeDecision(
            tenant_id=tenant_id,
            candidate_id=None,
            decision_type=MergeDecisionType.SPLIT,
            source=MergeDecisionSource.HUMAN,
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
    undo: dict[str, Any],
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
    for alias in source_aliases:
        if alias.normalized_form in target_forms:
            undo["alias_actions"].append(
                {
                    "action": "deleted",
                    "surface_form": alias.surface_form,
                    "normalized_form": alias.normalized_form,
                    "source": alias.source.value,
                }
            )
            await session.delete(alias)
        else:
            undo["alias_actions"].append({"action": "moved", "alias_id": str(alias.id)})
            alias.canonical_entity_id = target_entity.id
            target_forms.add(alias.normalized_form)

    if source_entity.normalized_name not in target_forms:
        added = EntityAlias(
            tenant_id=tenant_id,
            canonical_entity_id=target_entity.id,
            surface_form=source_entity.canonical_name,
            normalized_form=source_entity.normalized_name,
            source=AliasSource.MERGE,
        )
        session.add(added)
        await session.flush()
        undo["alias_actions"].append({"action": "added_canonical", "alias_id": str(added.id)})
    await session.flush()


async def _reparent_relationships(
    session: AsyncSession,
    tenant_id: UUID,
    source_entity_id: UUID,
    target_entity_id: UUID,
    undo: dict[str, Any],
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
        original_subject = relationship.subject_entity_id
        original_object = relationship.object_entity_id
        new_subject = target_entity_id if original_subject == source_entity_id else original_subject
        new_object = target_entity_id if original_object == source_entity_id else original_object
        record = {
            "subject_id": str(original_subject),
            "predicate": relationship.predicate,
            "object_id": str(original_object),
            "support": relationship.support_count,
            "provenance": relationship.provenance,
        }
        if new_subject == new_object:
            undo["relationship_actions"].append({"action": "self_loop_deleted", **record})
            await session.delete(relationship)
            await session.flush()
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
            undo["relationship_actions"].append(
                {"action": "folded", "surviving_id": str(existing.id), **record}
            )
            existing.support_count += relationship.support_count
            existing.provenance = [*existing.provenance, *relationship.provenance]
            await session.delete(relationship)
        else:
            undo["relationship_actions"].append(
                {
                    "action": "repointed",
                    "relationship_id": str(relationship.id),
                    "original_subject_id": str(original_subject),
                    "original_object_id": str(original_object),
                }
            )
            relationship.subject_entity_id = new_subject
            relationship.object_entity_id = new_object
        await session.flush()


async def _latest_merge_payload(
    session: AsyncSession, tenant_id: UUID, source_entity_id: UUID
) -> dict[str, Any] | None:
    decisions = list(
        (
            await session.execute(
                select(MergeDecision)
                .where(
                    MergeDecision.tenant_id == tenant_id,
                    MergeDecision.decision_type == MergeDecisionType.MERGE,
                )
                .order_by(MergeDecision.created_at.desc(), MergeDecision.id.desc())
            )
        )
        .scalars()
        .all()
    )
    for decision in decisions:
        if decision.payload.get("source_entity_id") == str(source_entity_id):
            return decision.payload
    return None


async def _restore_relationships(
    session: AsyncSession, tenant_id: UUID, actions: list[dict[str, Any]]
) -> None:
    for action in reversed(actions):
        kind = action["action"]
        if kind == "repointed":
            relationship = await session.get(
                EntityRelationship, UUID(action["relationship_id"])
            )
            if relationship is not None:
                relationship.subject_entity_id = UUID(action["original_subject_id"])
                relationship.object_entity_id = UUID(action["original_object_id"])
        elif kind == "folded":
            surviving = await session.get(EntityRelationship, UUID(action["surviving_id"]))
            if surviving is not None:
                surviving.support_count = max(
                    0, surviving.support_count - int(action["support"])
                )
                folded_provenance = action["provenance"]
                surviving.provenance = _remove_provenance(surviving.provenance, folded_provenance)
            _recreate_relationship(session, tenant_id, action)
        elif kind == "self_loop_deleted":
            _recreate_relationship(session, tenant_id, action)
        await session.flush()


def _recreate_relationship(
    session: AsyncSession, tenant_id: UUID, action: dict[str, Any]
) -> None:
    session.add(
        EntityRelationship(
            tenant_id=tenant_id,
            subject_entity_id=UUID(action["subject_id"]),
            predicate=action["predicate"],
            object_entity_id=UUID(action["object_id"]),
            support_count=int(action["support"]),
            provenance=action["provenance"],
            status=RelationshipStatus.ACTIVE,
        )
    )


def _remove_provenance(
    current: list[dict[str, Any]], to_remove: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    remaining = list(current)
    for entry in to_remove:
        if entry in remaining:
            remaining.remove(entry)
    return remaining


async def _restore_aliases(
    session: AsyncSession,
    tenant_id: UUID,
    source_entity_id: UUID,
    actions: list[dict[str, Any]],
) -> None:
    for action in actions:
        kind = action["action"]
        if kind == "moved":
            alias = await session.get(EntityAlias, UUID(action["alias_id"]))
            if alias is not None:
                alias.canonical_entity_id = source_entity_id
        elif kind == "added_canonical":
            alias = await session.get(EntityAlias, UUID(action["alias_id"]))
            if alias is not None:
                await session.delete(alias)
        elif kind == "deleted":
            session.add(
                EntityAlias(
                    tenant_id=tenant_id,
                    canonical_entity_id=source_entity_id,
                    surface_form=action["surface_form"],
                    normalized_form=action["normalized_form"],
                    source=AliasSource(action["source"]),
                )
            )
    await session.flush()
