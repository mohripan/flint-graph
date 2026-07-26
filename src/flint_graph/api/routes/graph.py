from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from flint_graph.api.dependencies import (
    AuditActorDep,
    Neo4jClientDep,
    SessionDep,
    TenantAdminDep,
    TenantIdDep,
)
from flint_graph.api.schemas import (
    CanonicalEntityDetail,
    CanonicalEntitySummary,
    EntityAliasResponse,
    EntityMentionSummary,
    EntityMergeResponse,
    EntityRelationshipSummary,
    MergeDecisionResponse,
    MergeEntitiesRequest,
    PendingReviewResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    UnmergeEntityRequest,
)
from flint_graph.application.services.audit import record_audit_event
from flint_graph.application.services.entity_merge import merge_entities, unmerge_entity
from flint_graph.application.services.graph_projection import reconcile_tenant_graph
from flint_graph.application.services.review import apply_review_decision, list_pending_reviews
from flint_graph.domain.enums import AuditAction, EntityStatus, MergeDecisionSource
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    EntityAlias,
    EntityMention,
    EntityRelationship,
    MergeDecision,
)

router = APIRouter(prefix="/v1", tags=["graph"])


@router.get("/entities", response_model=list[CanonicalEntitySummary])
async def list_entities(
    tenant_id: TenantIdDep,
    session: SessionDep,
    status: EntityStatus | None = None,
    limit: int = 200,
) -> list[CanonicalEntitySummary]:
    stmt = select(CanonicalEntity).where(CanonicalEntity.tenant_id == tenant_id)
    if status is not None:
        stmt = stmt.where(CanonicalEntity.status == status)
    stmt = stmt.order_by(
        CanonicalEntity.support_count.desc(), CanonicalEntity.canonical_name
    ).limit(min(limit, 500))
    entities = (await session.execute(stmt)).scalars().all()
    return [CanonicalEntitySummary.model_validate(entity) for entity in entities]


@router.get("/entities/{entity_id}", response_model=CanonicalEntityDetail)
async def get_entity(
    entity_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> CanonicalEntityDetail:
    entity = await session.get(CanonicalEntity, entity_id)
    if entity is None or entity.tenant_id != tenant_id:
        raise NotFoundError(f"Canonical entity '{entity_id}' was not found.")

    aliases = (
        await session.execute(
            select(EntityAlias).where(EntityAlias.canonical_entity_id == entity_id)
        )
    ).scalars().all()
    mentions = (
        await session.execute(
            select(EntityMention).where(EntityMention.resolved_entity_id == entity_id)
        )
    ).scalars().all()
    relationships = (
        await session.execute(
            select(EntityRelationship).where(
                EntityRelationship.tenant_id == tenant_id,
                (EntityRelationship.subject_entity_id == entity_id)
                | (EntityRelationship.object_entity_id == entity_id),
            )
        )
    ).scalars().all()

    return CanonicalEntityDetail(
        id=entity.id,
        entity_type=entity.entity_type,
        canonical_name=entity.canonical_name,
        normalized_name=entity.normalized_name,
        status=entity.status,
        support_count=entity.support_count,
        merged_into_id=entity.merged_into_id,
        aliases=[EntityAliasResponse.model_validate(alias) for alias in aliases],
        mentions=[EntityMentionSummary.model_validate(mention) for mention in mentions],
        relationships=[
            EntityRelationshipSummary.model_validate(relationship)
            for relationship in relationships
        ],
    )


@router.post("/entities/{entity_id}/merge", response_model=EntityMergeResponse)
async def merge_entity_endpoint(
    entity_id: UUID,
    payload: MergeEntitiesRequest,
    tenant_id: TenantAdminDep,
    session: SessionDep,
    neo4j_client: Neo4jClientDep,
    audit_actor: AuditActorDep,
) -> EntityMergeResponse:
    await merge_entities(
        session,
        tenant_id=tenant_id,
        source_entity_id=entity_id,
        target_entity_id=payload.target_entity_id,
        source=MergeDecisionSource.HUMAN,
        actor=payload.actor,
        reason=payload.reason,
    )
    await record_audit_event(
        session,
        action=AuditAction.ENTITY_MERGED,
        actor=audit_actor,
        tenant_id=tenant_id,
        resource_type="canonical_entity",
        resource_id=entity_id,
        metadata={
            "target_entity_id": str(payload.target_entity_id),
            # The claimed actor from the payload is kept alongside the
            # authenticated identity, never in place of it.
            "claimed_actor": payload.actor,
            "reason": payload.reason,
        },
    )
    await session.commit()
    await reconcile_tenant_graph(session, neo4j_client, tenant_id=tenant_id)
    return EntityMergeResponse(
        source_entity_id=entity_id, target_entity_id=payload.target_entity_id, status="merged"
    )


@router.post("/entities/{entity_id}/unmerge", response_model=EntityMergeResponse)
async def unmerge_entity_endpoint(
    entity_id: UUID,
    payload: UnmergeEntityRequest,
    tenant_id: TenantAdminDep,
    session: SessionDep,
    neo4j_client: Neo4jClientDep,
    audit_actor: AuditActorDep,
) -> EntityMergeResponse:
    entity = await session.get(CanonicalEntity, entity_id)
    former_target = entity.merged_into_id if entity is not None else None
    await unmerge_entity(
        session,
        tenant_id=tenant_id,
        source_entity_id=entity_id,
        actor=payload.actor,
        reason=payload.reason,
    )
    await record_audit_event(
        session,
        action=AuditAction.ENTITY_UNMERGED,
        actor=audit_actor,
        tenant_id=tenant_id,
        resource_type="canonical_entity",
        resource_id=entity_id,
        metadata={
            "former_target_entity_id": str(former_target) if former_target else None,
            "claimed_actor": payload.actor,
            "reason": payload.reason,
        },
    )
    await session.commit()
    await reconcile_tenant_graph(session, neo4j_client, tenant_id=tenant_id)
    return EntityMergeResponse(
        source_entity_id=entity_id, target_entity_id=former_target, status="unmerged"
    )


@router.get("/merge-reviews", response_model=list[PendingReviewResponse])
async def list_merge_reviews(
    tenant_id: TenantIdDep, session: SessionDep
) -> list[PendingReviewResponse]:
    reviews = await list_pending_reviews(session, tenant_id=tenant_id)
    return [
        PendingReviewResponse(
            candidate_id=review.candidate_id,
            mention_id=review.mention_id,
            mention_surface=review.mention_surface,
            entity_type=review.entity_type,
            target_entity_id=review.target_entity_id,
            target_name=review.target_name,
            score=review.score,
        )
        for review in reviews
    ]


@router.post(
    "/merge-reviews/{candidate_id}/decision", response_model=ReviewDecisionResponse
)
async def decide_merge_review(
    candidate_id: UUID,
    payload: ReviewDecisionRequest,
    tenant_id: TenantAdminDep,
    session: SessionDep,
    neo4j_client: Neo4jClientDep,
    audit_actor: AuditActorDep,
) -> ReviewDecisionResponse:
    await apply_review_decision(
        session,
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        decision=payload.decision,
        actor=payload.actor,
        reason=payload.reason,
    )
    await record_audit_event(
        session,
        action=AuditAction.MERGE_REVIEW_DECIDED,
        actor=audit_actor,
        tenant_id=tenant_id,
        resource_type="merge_candidate",
        resource_id=candidate_id,
        metadata={
            "decision": str(payload.decision),
            "claimed_actor": payload.actor,
            "reason": payload.reason,
        },
    )
    await session.commit()
    await reconcile_tenant_graph(session, neo4j_client, tenant_id=tenant_id)
    return ReviewDecisionResponse(
        candidate_id=candidate_id, decision=payload.decision, status="applied"
    )


@router.get("/merge-decisions", response_model=list[MergeDecisionResponse])
async def list_merge_decisions(
    tenant_id: TenantIdDep, session: SessionDep, limit: int = 200
) -> list[MergeDecisionResponse]:
    decisions = (
        await session.execute(
            select(MergeDecision)
            .where(MergeDecision.tenant_id == tenant_id)
            .order_by(MergeDecision.created_at.desc(), MergeDecision.id.desc())
            .limit(min(limit, 500))
        )
    ).scalars().all()
    return [MergeDecisionResponse.model_validate(decision) for decision in decisions]
