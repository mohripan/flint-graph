from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.resolution import aggregate_relationships
from flint_graph.domain.enums import (
    AliasSource,
    EntityStatus,
    MentionResolutionStatus,
    MergeCandidateBand,
    MergeCandidateStatus,
    MergeDecisionSource,
    MergeDecisionType,
)
from flint_graph.domain.errors import BadRequestError, NotFoundError
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    EntityAlias,
    EntityMention,
    MergeCandidate,
    MergeDecision,
)

ReviewDecision = Literal["accept", "reject"]


@dataclass(frozen=True)
class PendingReview:
    candidate_id: UUID
    mention_id: UUID
    mention_surface: str
    entity_type: str
    target_entity_id: UUID
    target_name: str
    score: float


async def list_pending_reviews(session: AsyncSession, *, tenant_id: UUID) -> list[PendingReview]:
    rows = (
        await session.execute(
            select(
                MergeCandidate.id,
                MergeCandidate.mention_id,
                MergeCandidate.target_entity_id,
                MergeCandidate.score,
                EntityMention.surface_text,
                EntityMention.entity_type,
                CanonicalEntity.canonical_name,
            )
            .join(EntityMention, EntityMention.id == MergeCandidate.mention_id)
            .join(CanonicalEntity, CanonicalEntity.id == MergeCandidate.target_entity_id)
            .where(
                MergeCandidate.tenant_id == tenant_id,
                MergeCandidate.band == MergeCandidateBand.REVIEW,
                MergeCandidate.status == MergeCandidateStatus.PENDING,
            )
            .order_by(MergeCandidate.created_at, MergeCandidate.id)
        )
    ).all()
    return [
        PendingReview(
            candidate_id=row.id,
            mention_id=row.mention_id,
            mention_surface=row.surface_text,
            entity_type=row.entity_type.value,
            target_entity_id=row.target_entity_id,
            target_name=row.canonical_name,
            score=row.score,
        )
        for row in rows
    ]


async def apply_review_decision(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    candidate_id: UUID,
    decision: ReviewDecision,
    actor: str,
    reason: str,
) -> None:
    """Resolve a review-queue mention: ``accept`` attaches to the candidate entity,
    ``reject`` creates a new distinct entity for the mention. Either way the
    candidate is closed, a human decision is recorded, and claims are re-aggregated.
    """

    candidate = await session.get(MergeCandidate, candidate_id)
    if candidate is None or candidate.tenant_id != tenant_id:
        raise NotFoundError(f"Merge candidate '{candidate_id}' was not found.")
    if candidate.band != MergeCandidateBand.REVIEW or (
        candidate.status != MergeCandidateStatus.PENDING
    ):
        raise BadRequestError("Merge candidate is not pending review.")
    if candidate.mention_id is None:
        raise BadRequestError("Merge candidate is not attached to a mention.")

    mention = await session.get(EntityMention, candidate.mention_id)
    if mention is None or mention.tenant_id != tenant_id:
        raise NotFoundError("Mention for the merge candidate was not found.")

    if decision == "accept":
        entity = await session.get(CanonicalEntity, candidate.target_entity_id)
        if entity is None or entity.tenant_id != tenant_id:
            raise NotFoundError("Target entity for the merge candidate was not found.")
        entity.support_count += 1
        await _ensure_alias(session, tenant_id, entity.id, mention)
        candidate.status = MergeCandidateStatus.ACCEPTED
        payload = {"mention_id": str(mention.id), "entity_id": str(entity.id), "accepted": True}
        entity_id = entity.id
    else:
        entity = CanonicalEntity(
            tenant_id=tenant_id,
            entity_type=mention.entity_type,
            canonical_name=mention.surface_text,
            normalized_name=mention.normalized_text,
            status=EntityStatus.ACTIVE,
            support_count=1,
        )
        session.add(entity)
        await session.flush()
        await _ensure_alias(session, tenant_id, entity.id, mention)
        candidate.status = MergeCandidateStatus.REJECTED
        payload = {"mention_id": str(mention.id), "entity_id": str(entity.id), "new_entity": True}
        entity_id = entity.id

    mention.resolved_entity_id = entity_id
    mention.resolution_status = MentionResolutionStatus.RESOLVED
    session.add(
        MergeDecision(
            tenant_id=tenant_id,
            candidate_id=candidate.id,
            decision_type=MergeDecisionType.ATTACH,
            source=MergeDecisionSource.HUMAN,
            actor=actor,
            reason=reason,
            payload=payload,
        )
    )
    await session.flush()
    await aggregate_relationships(session, tenant_id=tenant_id)
    await session.flush()


async def _ensure_alias(
    session: AsyncSession, tenant_id: UUID, entity_id: UUID, mention: EntityMention
) -> None:
    if not mention.normalized_text:
        return
    exists = await session.scalar(
        select(EntityAlias.id).where(
            EntityAlias.tenant_id == tenant_id,
            EntityAlias.canonical_entity_id == entity_id,
            EntityAlias.normalized_form == mention.normalized_text,
        )
    )
    if exists is None:
        session.add(
            EntityAlias(
                tenant_id=tenant_id,
                canonical_entity_id=entity_id,
                surface_form=mention.surface_text,
                normalized_form=mention.normalized_text,
                source=AliasSource.EXTRACTION,
            )
        )
