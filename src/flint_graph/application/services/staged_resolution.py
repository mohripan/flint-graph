from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.entity_resolution import normalize_name
from flint_graph.domain.enums import (
    AliasSource,
    CandidateOutcome,
    CandidateTargetKind,
    DocumentVersionStatus,
    EntityStatus,
    ExtractionRunStatus,
    MergeCandidateStatus,
    MergeDecisionSource,
    MergeDecisionType,
    RelationshipStatus,
    StagedProposalStatus,
    StagedResolutionStatus,
)
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    DocumentVersion,
    EntityAlias,
    EntityRelationship,
    EntityResolutionCandidate,
    ExtractedClaim,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionRun,
    MergeDecision,
)

_STAGED_PROVENANCE_SOURCES = frozenset(
    {"staged_extracted_relation", "staged_extracted_claim"}
)


@dataclass(frozen=True, slots=True)
class StagedResolutionResult:
    source_entity_count: int
    auto_attached: int
    new_entities: int
    review_queued: int
    relationships_upserted: int


async def resolve_pending_staged_entities(
    session: AsyncSession, *, tenant_id: UUID
) -> StagedResolutionResult:
    """Resolve all ready extraction runs with pending staged entities for a tenant."""

    run_ids = list(
        (
            await session.execute(
                select(ExtractionRun.id)
                .join(ExtractedEntity, ExtractedEntity.extraction_run_id == ExtractionRun.id)
                .join(DocumentVersion, DocumentVersion.id == ExtractionRun.document_version_id)
                .where(
                    ExtractionRun.tenant_id == tenant_id,
                    ExtractionRun.status == ExtractionRunStatus.READY,
                    DocumentVersion.status == DocumentVersionStatus.ACTIVE,
                    ExtractedEntity.status == StagedProposalStatus.ACCEPTED,
                    ExtractedEntity.resolution_status == StagedResolutionStatus.PENDING,
                )
                .distinct()
                .order_by(ExtractionRun.id)
            )
        )
        .scalars()
        .all()
    )
    total = StagedResolutionResult(
        source_entity_count=0,
        auto_attached=0,
        new_entities=0,
        review_queued=0,
        relationships_upserted=0,
    )
    for run_id in run_ids:
        result = await resolve_staged_extraction_run(
            session, tenant_id=tenant_id, extraction_run_id=run_id
        )
        total = _add_results(total, result)
    if not run_ids:
        relationships = await rebuild_staged_relationships(session, tenant_id=tenant_id)
        total = StagedResolutionResult(
            source_entity_count=0,
            auto_attached=0,
            new_entities=0,
            review_queued=0,
            relationships_upserted=relationships,
        )
    return total


async def resolve_staged_extraction_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    extraction_run_id: UUID,
) -> StagedResolutionResult:
    """Resolve accepted staged entities into canonical graph state.

    This service consumes staged proposal candidates but does not trust model
    output directly. It applies deterministic auto candidates, creates canonical
    entities when no candidate exists, and leaves review candidates unresolved.
    Relationship support is rebuilt from resolved staged relations and claims so
    retries do not inflate counts.
    """

    run = await _get_ready_run(
        session, tenant_id=tenant_id, extraction_run_id=extraction_run_id
    )
    pending = await _load_pending_entities(session, run=run)
    if not pending:
        relationships = await rebuild_staged_relationships(session, tenant_id=tenant_id)
        return StagedResolutionResult(
            source_entity_count=0,
            auto_attached=0,
            new_entities=0,
            review_queued=0,
            relationships_upserted=relationships,
        )

    candidates = await _load_candidates_by_source(
        session, tenant_id=tenant_id, source_ids=[entity.id for entity in pending]
    )
    all_run_entities = await _load_accepted_entities(session, run=run)
    entity_by_id = {entity.id: entity for entity in all_run_entities}
    pending_by_id = {entity.id: entity for entity in pending}

    duplicate_components = _duplicate_components(
        pending_by_id=pending_by_id,
        entity_by_id=entity_by_id,
        candidates_by_source=candidates,
    )
    handled_ids: set[UUID] = set()
    auto_attached = 0
    new_entities = 0
    review_queued = 0

    for component_ids in duplicate_components:
        component_entities = [entity_by_id[entity_id] for entity_id in sorted(component_ids)]
        canonical, created, candidate = await _canonical_for_component(
            session,
            tenant_id=tenant_id,
            component=component_entities,
            candidates_by_source=candidates,
        )
        for entity in component_entities:
            if entity.id in pending_by_id:
                _resolve_entity(
                    entity,
                    canonical_id=canonical.id,
                    candidate_id=candidate.id if candidate else None,
                )
                await _ensure_aliases(
                    session, tenant_id=tenant_id, canonical=canonical, entity=entity
                )
                _record_auto_decision(
                    session,
                    tenant_id=tenant_id,
                    extracted_entity=entity,
                    canonical=canonical,
                    candidate=candidate,
                    reason=(
                        "same-run staged entity candidate"
                        if candidate is not None
                        else "same-run staged entity group"
                    ),
                )
                handled_ids.add(entity.id)
        canonical.support_count += sum(
            1 for entity in component_entities if entity.id in pending_by_id
        )
        new_entities += 1 if created else 0
        auto_attached += 0 if created else sum(
            1 for entity in component_entities if entity.id in pending_by_id
        )
        for duplicate_candidate in _component_duplicate_candidates(
            component_ids, candidates
        ):
            duplicate_candidate.status = MergeCandidateStatus.APPLIED

    for entity in pending:
        if entity.id in handled_ids:
            continue
        best_auto = _best_candidate(candidates.get(entity.id, []), CandidateOutcome.AUTO)
        if best_auto is not None and best_auto.target_kind == CandidateTargetKind.CANONICAL_ENTITY:
            target_canonical = await _get_active_canonical(
                session, tenant_id=tenant_id, canonical_id=best_auto.target_canonical_entity_id
            )
            if target_canonical is not None:
                _resolve_entity(
                    entity, canonical_id=target_canonical.id, candidate_id=best_auto.id
                )
                target_canonical.support_count += 1
                best_auto.status = MergeCandidateStatus.APPLIED
                await _ensure_aliases(
                    session,
                    tenant_id=tenant_id,
                    canonical=target_canonical,
                    entity=entity,
                )
                _record_auto_decision(
                    session,
                    tenant_id=tenant_id,
                    extracted_entity=entity,
                    canonical=target_canonical,
                    candidate=best_auto,
                    reason="score at or above auto threshold",
                )
                auto_attached += 1
                continue

        best_review = _best_candidate(
            candidates.get(entity.id, []), CandidateOutcome.REVIEW
        )
        if best_review is not None:
            entity.resolution_status = StagedResolutionStatus.REVIEW
            review_queued += 1
            continue

        canonical = await _create_canonical_for_entity(
            session, tenant_id=tenant_id, entity=entity
        )
        _resolve_entity(entity, canonical_id=canonical.id, candidate_id=None)
        await _ensure_aliases(session, tenant_id=tenant_id, canonical=canonical, entity=entity)
        _record_auto_decision(
            session,
            tenant_id=tenant_id,
            extracted_entity=entity,
            canonical=canonical,
            candidate=None,
            reason="no candidate above review threshold",
        )
        new_entities += 1

    await session.flush()
    relationships = await rebuild_staged_relationships(session, tenant_id=tenant_id)
    await session.flush()
    return StagedResolutionResult(
        source_entity_count=len(pending),
        auto_attached=auto_attached,
        new_entities=new_entities,
        review_queued=review_queued,
        relationships_upserted=relationships,
    )


def _add_results(
    left: StagedResolutionResult, right: StagedResolutionResult
) -> StagedResolutionResult:
    return StagedResolutionResult(
        source_entity_count=left.source_entity_count + right.source_entity_count,
        auto_attached=left.auto_attached + right.auto_attached,
        new_entities=left.new_entities + right.new_entities,
        review_queued=left.review_queued + right.review_queued,
        relationships_upserted=right.relationships_upserted,
    )


async def rebuild_staged_relationships(session: AsyncSession, *, tenant_id: UUID) -> int:
    entities = {
        entity.id: entity
        for entity in (
            await session.execute(
                select(ExtractedEntity).where(
                    ExtractedEntity.tenant_id == tenant_id,
                    ExtractedEntity.resolution_status == StagedResolutionStatus.RESOLVED,
                    ExtractedEntity.resolved_canonical_entity_id.is_not(None),
                )
                .join(DocumentVersion, DocumentVersion.id == ExtractedEntity.document_version_id)
                .where(DocumentVersion.status == DocumentVersionStatus.ACTIVE)
            )
        )
        .scalars()
        .all()
    }
    contributions: dict[tuple[UUID, str, UUID], list[dict[str, Any]]] = defaultdict(list)

    relations = (
        await session.execute(
            select(ExtractedRelation)
            .join(DocumentVersion, DocumentVersion.id == ExtractedRelation.document_version_id)
            .where(
                ExtractedRelation.tenant_id == tenant_id,
                ExtractedRelation.status == StagedProposalStatus.ACCEPTED,
                DocumentVersion.status == DocumentVersionStatus.ACTIVE,
            )
        )
    ).scalars()
    for relation in relations:
        subject = entities.get(relation.subject_extracted_entity_id)
        obj = entities.get(relation.object_extracted_entity_id)
        if subject is None or obj is None:
            continue
        _add_relationship_contribution(
            contributions,
            subject_id=subject.resolved_canonical_entity_id,
            predicate=relation.predicate,
            object_id=obj.resolved_canonical_entity_id,
            provenance={
                "source": "staged_extracted_relation",
                "extracted_relation_id": str(relation.id),
                "extraction_run_id": str(relation.extraction_run_id),
                "document_version_id": str(relation.document_version_id),
            },
        )

    claims = (
        await session.execute(
            select(ExtractedClaim)
            .join(DocumentVersion, DocumentVersion.id == ExtractedClaim.document_version_id)
            .where(
                ExtractedClaim.tenant_id == tenant_id,
                ExtractedClaim.status == StagedProposalStatus.ACCEPTED,
                DocumentVersion.status == DocumentVersionStatus.ACTIVE,
                ExtractedClaim.object_extracted_entity_id.is_not(None),
            )
        )
    ).scalars()
    for claim in claims:
        if claim.subject_extracted_entity_id is None or claim.object_extracted_entity_id is None:
            continue
        subject = entities.get(claim.subject_extracted_entity_id)
        obj = entities.get(claim.object_extracted_entity_id)
        if subject is None or obj is None:
            continue
        _add_relationship_contribution(
            contributions,
            subject_id=subject.resolved_canonical_entity_id,
            predicate=claim.predicate,
            object_id=obj.resolved_canonical_entity_id,
            provenance={
                "source": "staged_extracted_claim",
                "extracted_claim_id": str(claim.id),
                "extraction_run_id": str(claim.extraction_run_id),
                "document_version_id": str(claim.document_version_id),
            },
        )

    upserted = 0
    for (subject_id, predicate, object_id), staged_provenance in contributions.items():
        relationship = await session.scalar(
            select(EntityRelationship).where(
                EntityRelationship.tenant_id == tenant_id,
                EntityRelationship.subject_entity_id == subject_id,
                EntityRelationship.predicate == predicate,
                EntityRelationship.object_entity_id == object_id,
            )
        )
        if relationship is None:
            session.add(
                EntityRelationship(
                    tenant_id=tenant_id,
                    subject_entity_id=subject_id,
                    predicate=predicate,
                    object_entity_id=object_id,
                    support_count=len(staged_provenance),
                    provenance=staged_provenance,
                    status=RelationshipStatus.ACTIVE,
                )
            )
        else:
            retained = [
                item
                for item in relationship.provenance
                if item.get("source") not in _STAGED_PROVENANCE_SOURCES
            ]
            relationship.provenance = [*retained, *staged_provenance]
            relationship.support_count = len(relationship.provenance)
            relationship.status = RelationshipStatus.ACTIVE
        upserted += 1
    return upserted


async def _get_ready_run(
    session: AsyncSession, *, tenant_id: UUID, extraction_run_id: UUID
) -> ExtractionRun:
    run = await session.scalar(
        select(ExtractionRun).where(
            ExtractionRun.id == extraction_run_id,
            ExtractionRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        raise NotFoundError(f"Extraction run '{extraction_run_id}' was not found.")
    if run.status != ExtractionRunStatus.READY:
        raise ValueError("Staged resolution can only run for ready extraction runs.")
    return run


async def _load_pending_entities(
    session: AsyncSession, *, run: ExtractionRun
) -> list[ExtractedEntity]:
    return list(
        (
            await session.execute(
                select(ExtractedEntity)
                .where(
                    ExtractedEntity.tenant_id == run.tenant_id,
                    ExtractedEntity.extraction_run_id == run.id,
                    ExtractedEntity.status == StagedProposalStatus.ACCEPTED,
                    ExtractedEntity.resolution_status == StagedResolutionStatus.PENDING,
                )
                .order_by(ExtractedEntity.local_id, ExtractedEntity.id)
            )
        )
        .scalars()
        .all()
    )


async def _load_accepted_entities(
    session: AsyncSession, *, run: ExtractionRun
) -> list[ExtractedEntity]:
    return list(
        (
            await session.execute(
                select(ExtractedEntity)
                .where(
                    ExtractedEntity.tenant_id == run.tenant_id,
                    ExtractedEntity.extraction_run_id == run.id,
                    ExtractedEntity.status == StagedProposalStatus.ACCEPTED,
                )
                .order_by(ExtractedEntity.local_id, ExtractedEntity.id)
            )
        )
        .scalars()
        .all()
    )


async def _load_candidates_by_source(
    session: AsyncSession, *, tenant_id: UUID, source_ids: list[UUID]
) -> dict[UUID, list[EntityResolutionCandidate]]:
    if not source_ids:
        return {}
    rows = (
        await session.execute(
            select(EntityResolutionCandidate)
            .where(
                EntityResolutionCandidate.tenant_id == tenant_id,
                EntityResolutionCandidate.source_extracted_entity_id.in_(source_ids),
                EntityResolutionCandidate.status == MergeCandidateStatus.PENDING,
            )
            .order_by(EntityResolutionCandidate.score.desc(), EntityResolutionCandidate.id)
        )
    ).scalars()
    candidates: dict[UUID, list[EntityResolutionCandidate]] = defaultdict(list)
    for row in rows:
        candidates[row.source_extracted_entity_id].append(row)
    return candidates


def _duplicate_components(
    *,
    pending_by_id: dict[UUID, ExtractedEntity],
    entity_by_id: dict[UUID, ExtractedEntity],
    candidates_by_source: dict[UUID, list[EntityResolutionCandidate]],
) -> list[set[UUID]]:
    parent = {entity_id: entity_id for entity_id in entity_by_id}

    def find(entity_id: UUID) -> UUID:
        while parent[entity_id] != entity_id:
            parent[entity_id] = parent[parent[entity_id]]
            entity_id = parent[entity_id]
        return entity_id

    def union(a: UUID, b: UUID) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for source_id, rows in candidates_by_source.items():
        for row in rows:
            if (
                row.outcome == CandidateOutcome.AUTO
                and row.target_kind == CandidateTargetKind.EXTRACTED_ENTITY
                and row.target_extracted_entity_id in entity_by_id
            ):
                union(source_id, row.target_extracted_entity_id)

    grouped: dict[UUID, set[UUID]] = defaultdict(set)
    for entity_id in entity_by_id:
        grouped[find(entity_id)].add(entity_id)
    return [
        component
        for component in grouped.values()
        if len(component) > 1 and any(entity_id in pending_by_id for entity_id in component)
    ]


async def _canonical_for_component(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    component: list[ExtractedEntity],
    candidates_by_source: dict[UUID, list[EntityResolutionCandidate]],
) -> tuple[CanonicalEntity, bool, EntityResolutionCandidate | None]:
    for entity in component:
        if entity.resolved_canonical_entity_id is not None:
            canonical = await _get_active_canonical(
                session,
                tenant_id=tenant_id,
                canonical_id=entity.resolved_canonical_entity_id,
            )
            if canonical is not None:
                return canonical, False, None

    best = _best_component_canonical_candidate(component, candidates_by_source)
    if best is not None:
        canonical = await _get_active_canonical(
            session, tenant_id=tenant_id, canonical_id=best.target_canonical_entity_id
        )
        if canonical is not None:
            best.status = MergeCandidateStatus.APPLIED
            return canonical, False, best

    canonical = await _create_canonical_for_entity(
        session, tenant_id=tenant_id, entity=component[0], support_count=0
    )
    return canonical, True, None


def _best_component_canonical_candidate(
    component: list[ExtractedEntity],
    candidates_by_source: dict[UUID, list[EntityResolutionCandidate]],
) -> EntityResolutionCandidate | None:
    candidates: list[EntityResolutionCandidate] = []
    for entity in component:
        candidates.extend(
            row
            for row in candidates_by_source.get(entity.id, [])
            if row.outcome == CandidateOutcome.AUTO
            and row.target_kind == CandidateTargetKind.CANONICAL_ENTITY
        )
    return _best(candidates)


def _component_duplicate_candidates(
    component_ids: set[UUID],
    candidates_by_source: dict[UUID, list[EntityResolutionCandidate]],
) -> list[EntityResolutionCandidate]:
    rows: list[EntityResolutionCandidate] = []
    for source_id in component_ids:
        rows.extend(
            row
            for row in candidates_by_source.get(source_id, [])
            if row.outcome == CandidateOutcome.AUTO
            and row.target_kind == CandidateTargetKind.EXTRACTED_ENTITY
            and row.target_extracted_entity_id in component_ids
        )
    return rows


def _best_candidate(
    candidates: list[EntityResolutionCandidate], outcome: CandidateOutcome
) -> EntityResolutionCandidate | None:
    return _best([candidate for candidate in candidates if candidate.outcome == outcome])


def _best(candidates: list[EntityResolutionCandidate]) -> EntityResolutionCandidate | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda candidate: (-candidate.score, str(candidate.id)))[0]


async def _get_active_canonical(
    session: AsyncSession, *, tenant_id: UUID, canonical_id: UUID | None
) -> CanonicalEntity | None:
    if canonical_id is None:
        return None
    return cast(
        CanonicalEntity | None,
        await session.scalar(
            select(CanonicalEntity).where(
                CanonicalEntity.id == canonical_id,
                CanonicalEntity.tenant_id == tenant_id,
                CanonicalEntity.status == EntityStatus.ACTIVE,
            )
        ),
    )


async def _create_canonical_for_entity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    entity: ExtractedEntity,
    support_count: int = 1,
) -> CanonicalEntity:
    canonical = CanonicalEntity(
        tenant_id=tenant_id,
        entity_type=entity.entity_type,
        canonical_name=entity.name,
        normalized_name=entity.normalized_name,
        status=EntityStatus.ACTIVE,
        support_count=support_count,
    )
    session.add(canonical)
    await session.flush()
    return canonical


def _resolve_entity(
    entity: ExtractedEntity,
    *,
    canonical_id: UUID,
    candidate_id: UUID | None,
) -> None:
    entity.resolution_status = StagedResolutionStatus.RESOLVED
    entity.resolved_canonical_entity_id = canonical_id
    entity.resolved_by_candidate_id = candidate_id
    entity.resolved_at = datetime.now(UTC)


async def _ensure_aliases(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    canonical: CanonicalEntity,
    entity: ExtractedEntity,
) -> None:
    surfaces = [(entity.name, entity.normalized_name)]
    surfaces.extend((alias, normalize_name(alias)) for alias in entity.aliases)
    for surface_form, normalized_form in surfaces:
        if not normalized_form:
            continue
        exists = await session.scalar(
            select(EntityAlias.id).where(
                EntityAlias.tenant_id == tenant_id,
                EntityAlias.canonical_entity_id == canonical.id,
                EntityAlias.normalized_form == normalized_form,
            )
        )
        if exists is None:
            session.add(
                EntityAlias(
                    tenant_id=tenant_id,
                    canonical_entity_id=canonical.id,
                    surface_form=surface_form,
                    normalized_form=normalized_form,
                    source=AliasSource.EXTRACTION,
                )
            )


def _record_auto_decision(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    extracted_entity: ExtractedEntity,
    canonical: CanonicalEntity,
    candidate: EntityResolutionCandidate | None,
    reason: str,
) -> None:
    session.add(
        MergeDecision(
            tenant_id=tenant_id,
            candidate_id=None,
            decision_type=MergeDecisionType.ATTACH,
            source=MergeDecisionSource.AUTO,
            actor="staged-resolver",
            reason=reason,
            payload={
                "extracted_entity_id": str(extracted_entity.id),
                "canonical_entity_id": str(canonical.id),
                "entity_resolution_candidate_id": str(candidate.id) if candidate else None,
            },
        )
    )


def _add_relationship_contribution(
    contributions: dict[tuple[UUID, str, UUID], list[dict[str, Any]]],
    *,
    subject_id: UUID | None,
    predicate: str,
    object_id: UUID | None,
    provenance: dict[str, Any],
) -> None:
    if subject_id is None or object_id is None or subject_id == object_id:
        return
    contributions[(subject_id, predicate, object_id)].append(provenance)
