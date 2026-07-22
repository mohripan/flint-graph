from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.entity_resolution import normalize_name
from flint_graph.application.proposal_candidates import (
    ProposalCandidateEntity,
    ScoredProposalCandidate,
    score_proposal_candidate,
)
from flint_graph.domain.enums import (
    CandidateOutcome,
    CandidateTargetKind,
    EntityStatus,
    ExtractionRunStatus,
    MergeCandidateStatus,
    StagedProposalStatus,
)
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    EntityAlias,
    EntityResolutionCandidate,
    ExtractedEntity,
    ExtractionRun,
)


@dataclass(frozen=True, slots=True)
class ProposalCandidateGenerationResult:
    source_entity_count: int
    generated_count: int


@dataclass(frozen=True, slots=True)
class _CandidateTarget:
    entity: ProposalCandidateEntity
    kind: CandidateTargetKind
    canonical_entity_id: UUID | None = None
    extracted_entity_id: UUID | None = None


async def generate_proposal_candidates_for_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    extraction_run_id: UUID,
    auto_threshold: float,
    review_threshold: float,
    limit_per_source: int,
) -> ProposalCandidateGenerationResult:
    """Generate non-destructive resolution candidates for staged entities.

    The service rewrites only pending rows for entities in the extraction run, so
    activity retries get the same logical candidate set without touching rows that
    have already been reviewed.
    """

    run = await _get_ready_run(
        session, tenant_id=tenant_id, extraction_run_id=extraction_run_id
    )
    sources = await _load_source_entities(session, run=run)
    source_ids = [source.id for source in sources]
    if not source_ids:
        return ProposalCandidateGenerationResult(source_entity_count=0, generated_count=0)

    await session.execute(
        delete(EntityResolutionCandidate).where(
            EntityResolutionCandidate.source_extracted_entity_id.in_(source_ids),
            EntityResolutionCandidate.status == MergeCandidateStatus.PENDING,
        )
    )

    canonical_targets = await _load_canonical_targets(session, tenant_id=tenant_id)
    generated = 0
    for source_row in sources:
        source = _proposal_entity_from_extracted(source_row)
        targets = [
            *canonical_targets,
            *_same_run_targets_for_source(source_row, sources),
        ]
        scored = _score_targets(
            source,
            targets,
            auto_threshold=auto_threshold,
            review_threshold=review_threshold,
            limit=limit_per_source,
        )
        for target, score in scored:
            session.add(
                EntityResolutionCandidate(
                    tenant_id=tenant_id,
                    source_extracted_entity_id=source_row.id,
                    target_kind=target.kind,
                    target_canonical_entity_id=target.canonical_entity_id,
                    target_extracted_entity_id=target.extracted_entity_id,
                    score=score.score,
                    features=asdict(score.features),
                    reasons=list(score.reasons),
                    outcome=score.outcome,
                    status=MergeCandidateStatus.PENDING,
                )
            )
            generated += 1
    await session.flush()
    return ProposalCandidateGenerationResult(
        source_entity_count=len(sources),
        generated_count=generated,
    )


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
        raise ValueError("Proposal candidates can only be generated for ready runs.")
    return run


async def _load_source_entities(
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


async def _load_canonical_targets(
    session: AsyncSession, *, tenant_id: UUID
) -> list[_CandidateTarget]:
    entities = list(
        (
            await session.execute(
                select(CanonicalEntity)
                .where(
                    CanonicalEntity.tenant_id == tenant_id,
                    CanonicalEntity.status == EntityStatus.ACTIVE,
                )
                .order_by(CanonicalEntity.normalized_name, CanonicalEntity.id)
            )
        )
        .scalars()
        .all()
    )
    if not entities:
        return []

    aliases_by_entity: dict[UUID, list[str]] = {}
    alias_rows = (
        await session.execute(
            select(EntityAlias.canonical_entity_id, EntityAlias.normalized_form).where(
                EntityAlias.tenant_id == tenant_id,
                EntityAlias.canonical_entity_id.in_([entity.id for entity in entities]),
            )
        )
    ).all()
    for entity_id, normalized_form in alias_rows:
        aliases_by_entity.setdefault(entity_id, []).append(normalized_form)

    return [
        _CandidateTarget(
            entity=ProposalCandidateEntity(
                entity_id=entity.id,
                entity_type=entity.entity_type,
                normalized_name=entity.normalized_name,
                alias_forms=tuple(sorted(set(aliases_by_entity.get(entity.id, [])))),
            ),
            kind=CandidateTargetKind.CANONICAL_ENTITY,
            canonical_entity_id=entity.id,
        )
        for entity in entities
    ]


def _same_run_targets_for_source(
    source: ExtractedEntity, entities: list[ExtractedEntity]
) -> list[_CandidateTarget]:
    targets: list[_CandidateTarget] = []
    for target in entities:
        if source.id == target.id:
            continue
        if (source.local_id, str(source.id)) > (target.local_id, str(target.id)):
            continue
        targets.append(
            _CandidateTarget(
                entity=_proposal_entity_from_extracted(target),
                kind=CandidateTargetKind.EXTRACTED_ENTITY,
                extracted_entity_id=target.id,
            )
        )
    return targets


def _score_targets(
    source: ProposalCandidateEntity,
    targets: list[_CandidateTarget],
    *,
    auto_threshold: float,
    review_threshold: float,
    limit: int,
) -> list[tuple[_CandidateTarget, ScoredProposalCandidate]]:
    scored: list[tuple[_CandidateTarget, ScoredProposalCandidate]] = []
    for target in targets:
        score = score_proposal_candidate(
            source,
            target.entity,
            auto_threshold=auto_threshold,
            review_threshold=review_threshold,
        )
        if score.outcome != CandidateOutcome.REJECT:
            scored.append((target, score))
    scored.sort(
        key=lambda item: (
            -item[1].score,
            item[0].kind,
            str(item[0].canonical_entity_id or item[0].extracted_entity_id),
        )
    )
    return scored[:limit]


def _proposal_entity_from_extracted(entity: ExtractedEntity) -> ProposalCandidateEntity:
    return ProposalCandidateEntity(
        entity_id=entity.id,
        entity_type=entity.entity_type,
        normalized_name=entity.normalized_name,
        alias_forms=tuple(sorted({normalize_name(alias) for alias in entity.aliases})),
    )
