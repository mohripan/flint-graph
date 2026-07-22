from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.entity_resolution import (
    CandidateEntity,
    CandidateFeatures,
    MentionKey,
    ScoredCandidate,
    score_candidates,
)
from flint_graph.application.services.candidate_generation import generate_candidates
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
)
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    Claim,
    EntityAlias,
    EntityMention,
    EntityRelationship,
    MergeCandidate,
    MergeDecision,
)

_ADVISORY_LOCK_NAMESPACE = 4242


@dataclass(frozen=True)
class ResolutionConfig:
    auto_threshold: float
    review_threshold: float
    trigram_threshold: float
    candidate_limit: int


@dataclass(frozen=True)
class ResolutionResult:
    mentions_processed: int
    auto_attached: int
    new_entities: int
    review_queued: int
    relationships_upserted: int


class CandidateProvider(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        normalized_text: str,
        entity_type: EntityType,
        trigram_threshold: float,
        limit: int,
    ) -> list[CandidateEntity]: ...


async def acquire_tenant_resolution_lock(session: AsyncSession, tenant_id: UUID) -> None:
    """Take a transaction-scoped PostgreSQL advisory lock for a tenant.

    Guarantees a single writer per tenant during resolution regardless of how many
    workers run. The lock releases automatically when the transaction ends.
    """

    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:tenant))").bindparams(
            bindparam("ns", _ADVISORY_LOCK_NAMESPACE),
            bindparam("tenant", str(tenant_id)),
        )
    )


async def resolve_pending_mentions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    config: ResolutionConfig,
    candidate_provider: CandidateProvider = generate_candidates,
) -> ResolutionResult:
    """Resolve every pending mention for a tenant using banded decisions.

    For each pending mention the best-scoring candidate determines the outcome:
    auto-attach (>= auto threshold), review queue (>= review threshold), or a new
    canonical entity (below review, or no candidate). After mentions are attached,
    resolved claims are aggregated into canonical relationships. Idempotent: once a
    mention leaves ``pending`` it is not reprocessed.
    """

    pending = list(
        (
            await session.execute(
                select(EntityMention)
                .where(
                    EntityMention.tenant_id == tenant_id,
                    EntityMention.resolution_status == MentionResolutionStatus.PENDING,
                )
                .order_by(EntityMention.created_at, EntityMention.id)
            )
        )
        .scalars()
        .all()
    )

    auto_attached = 0
    new_entities = 0
    review_queued = 0
    for mention in pending:
        candidates = await candidate_provider(
            session,
            tenant_id=tenant_id,
            normalized_text=mention.normalized_text,
            entity_type=mention.entity_type,
            trigram_threshold=config.trigram_threshold,
            limit=config.candidate_limit,
        )
        scored = score_candidates(
            MentionKey(mention.normalized_text, mention.entity_type, mention.document_id),
            candidates,
            auto_threshold=config.auto_threshold,
            review_threshold=config.review_threshold,
        )
        best = scored[0] if scored else None
        if best is not None and best.band == MergeCandidateBand.AUTO:
            await _auto_attach(session, tenant_id=tenant_id, mention=mention, best=best)
            auto_attached += 1
        elif best is not None and best.band == MergeCandidateBand.REVIEW:
            await _queue_review(session, tenant_id=tenant_id, mention=mention, best=best)
            review_queued += 1
        else:
            await _create_new_entity(session, tenant_id=tenant_id, mention=mention)
            new_entities += 1
        await session.flush()

    relationships = await aggregate_relationships(session, tenant_id=tenant_id)
    await session.flush()

    return ResolutionResult(
        mentions_processed=len(pending),
        auto_attached=auto_attached,
        new_entities=new_entities,
        review_queued=review_queued,
        relationships_upserted=relationships,
    )


async def aggregate_relationships(session: AsyncSession, *, tenant_id: UUID) -> int:
    """Fold resolved claims into canonical entity relationships.

    Only claims whose subject and object mentions are both resolved to entities
    become relationships. Each contributing claim is marked ``linked`` so re-runs
    do not double count. Claims with a literal object are left pending.
    """

    claims = list(
        (
            await session.execute(
                select(Claim).where(
                    Claim.tenant_id == tenant_id,
                    Claim.status == ClaimStatus.PENDING,
                    Claim.object_mention_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    upserted = 0
    for claim in claims:
        subject_mention = await session.get(EntityMention, claim.subject_mention_id)
        object_mention = (
            await session.get(EntityMention, claim.object_mention_id)
            if claim.object_mention_id is not None
            else None
        )
        if subject_mention is None or object_mention is None:
            continue
        subject_id = subject_mention.resolved_entity_id
        object_id = object_mention.resolved_entity_id
        if subject_id is None or object_id is None:
            continue
        if subject_id == object_id:
            claim.status = ClaimStatus.LINKED
            continue

        provenance = {
            "claim_id": str(claim.id),
            "document_version_id": str(claim.document_version_id),
        }
        relationship = await session.scalar(
            select(EntityRelationship).where(
                EntityRelationship.tenant_id == tenant_id,
                EntityRelationship.subject_entity_id == subject_id,
                EntityRelationship.predicate == claim.predicate,
                EntityRelationship.object_entity_id == object_id,
            )
        )
        if relationship is None:
            session.add(
                EntityRelationship(
                    tenant_id=tenant_id,
                    subject_entity_id=subject_id,
                    predicate=claim.predicate,
                    object_entity_id=object_id,
                    support_count=1,
                    provenance=[provenance],
                    status=RelationshipStatus.ACTIVE,
                )
            )
        else:
            relationship.support_count += 1
            relationship.provenance = [*relationship.provenance, provenance]
        claim.status = ClaimStatus.LINKED
        upserted += 1

    return upserted


async def _auto_attach(
    session: AsyncSession, *, tenant_id: UUID, mention: EntityMention, best: ScoredCandidate
) -> None:
    entity = await session.get(CanonicalEntity, best.candidate.entity_id)
    if entity is None:
        await _create_new_entity(session, tenant_id=tenant_id, mention=mention)
        return
    candidate_row = MergeCandidate(
        tenant_id=tenant_id,
        mention_id=mention.id,
        target_entity_id=entity.id,
        score=best.score,
        features=_features_dict(best.features),
        band=MergeCandidateBand.AUTO,
        status=MergeCandidateStatus.APPLIED,
    )
    session.add(candidate_row)
    await session.flush()

    mention.resolved_entity_id = entity.id
    mention.resolution_status = MentionResolutionStatus.RESOLVED
    entity.support_count += 1
    await _ensure_alias(
        session,
        tenant_id=tenant_id,
        entity_id=entity.id,
        surface_form=mention.surface_text,
        normalized_form=mention.normalized_text,
        source=AliasSource.EXTRACTION,
    )
    session.add(
        MergeDecision(
            tenant_id=tenant_id,
            candidate_id=candidate_row.id,
            decision_type=MergeDecisionType.ATTACH,
            source=MergeDecisionSource.AUTO,
            actor="resolver",
            reason="score at or above auto threshold",
            payload={
                "mention_id": str(mention.id),
                "entity_id": str(entity.id),
                "score": best.score,
            },
        )
    )


async def _queue_review(
    session: AsyncSession, *, tenant_id: UUID, mention: EntityMention, best: ScoredCandidate
) -> None:
    session.add(
        MergeCandidate(
            tenant_id=tenant_id,
            mention_id=mention.id,
            target_entity_id=best.candidate.entity_id,
            score=best.score,
            features=_features_dict(best.features),
            band=MergeCandidateBand.REVIEW,
            status=MergeCandidateStatus.PENDING,
        )
    )
    mention.resolution_status = MentionResolutionStatus.REVIEW


async def _create_new_entity(
    session: AsyncSession, *, tenant_id: UUID, mention: EntityMention
) -> None:
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
    session.add(
        EntityAlias(
            tenant_id=tenant_id,
            canonical_entity_id=entity.id,
            surface_form=mention.surface_text,
            normalized_form=mention.normalized_text,
            source=AliasSource.EXTRACTION,
        )
    )
    mention.resolved_entity_id = entity.id
    mention.resolution_status = MentionResolutionStatus.RESOLVED
    session.add(
        MergeDecision(
            tenant_id=tenant_id,
            candidate_id=None,
            decision_type=MergeDecisionType.ATTACH,
            source=MergeDecisionSource.AUTO,
            actor="resolver",
            reason="no candidate above review threshold",
            payload={
                "mention_id": str(mention.id),
                "entity_id": str(entity.id),
                "new_entity": True,
            },
        )
    )


async def _ensure_alias(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    entity_id: UUID,
    surface_form: str,
    normalized_form: str,
    source: AliasSource,
) -> None:
    if not normalized_form:
        return
    exists = await session.scalar(
        select(EntityAlias.id).where(
            EntityAlias.tenant_id == tenant_id,
            EntityAlias.canonical_entity_id == entity_id,
            EntityAlias.normalized_form == normalized_form,
        )
    )
    if exists is None:
        session.add(
            EntityAlias(
                tenant_id=tenant_id,
                canonical_entity_id=entity_id,
                surface_form=surface_form,
                normalized_form=normalized_form,
                source=source,
            )
        )


def _features_dict(features: CandidateFeatures) -> dict[str, Any]:
    return {
        "name_similarity": features.name_similarity,
        "type_match": features.type_match,
        "alias_exact": features.alias_exact,
        "shared_document": features.shared_document,
    }
