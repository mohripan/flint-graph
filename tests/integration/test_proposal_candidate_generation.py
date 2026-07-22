from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.proposal_candidate_generation import (
    generate_proposal_candidates_for_run,
)
from flint_graph.domain.enums import (
    AliasSource,
    CandidateOutcome,
    CandidateTargetKind,
    EntityStatus,
    EntityType,
    ExtractionRunStatus,
    MergeCandidateStatus,
    SourceType,
    StagedProposalStatus,
)
from flint_graph.infrastructure.db.models import (
    CanonicalEntity,
    Document,
    DocumentVersion,
    EntityAlias,
    EntityResolutionCandidate,
    ExtractedEntity,
    ExtractionRun,
    Tenant,
)


async def test_generate_proposal_candidates_matches_canonical_and_staged_entities(
    db_session: AsyncSession,
) -> None:
    tenant, run, source, staged_target, canonical_target = await _seed_candidate_graph(
        db_session
    )

    result = await generate_proposal_candidates_for_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
        auto_threshold=0.92,
        review_threshold=0.62,
        limit_per_source=10,
    )

    assert result.source_entity_count == 3
    assert result.generated_count == 3

    candidates = list(
        (
            await db_session.execute(
                select(EntityResolutionCandidate).order_by(
                    EntityResolutionCandidate.score.desc(),
                    EntityResolutionCandidate.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(candidates) == 3

    canonical_candidate = next(
        candidate
        for candidate in candidates
        if candidate.source_extracted_entity_id == source.id
        and candidate.target_kind == CandidateTargetKind.CANONICAL_ENTITY
    )
    assert canonical_candidate.target_canonical_entity_id == canonical_target.id
    assert canonical_candidate.target_extracted_entity_id is None
    assert canonical_candidate.outcome == CandidateOutcome.AUTO
    assert canonical_candidate.status == MergeCandidateStatus.PENDING
    assert canonical_candidate.features["alias_exact"] is True
    assert "alias_exact" in canonical_candidate.reasons

    staged_candidate = next(
        candidate
        for candidate in candidates
        if candidate.source_extracted_entity_id == source.id
        and candidate.target_kind == CandidateTargetKind.EXTRACTED_ENTITY
    )
    assert staged_candidate.target_extracted_entity_id == staged_target.id
    assert staged_candidate.target_canonical_entity_id is None
    assert staged_candidate.outcome == CandidateOutcome.AUTO
    assert staged_candidate.features["normalized_name_equal"] is True


async def test_generate_proposal_candidates_is_idempotent_for_pending_rows(
    db_session: AsyncSession,
) -> None:
    tenant, run, *_ = await _seed_candidate_graph(db_session)

    first = await generate_proposal_candidates_for_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
        auto_threshold=0.92,
        review_threshold=0.62,
        limit_per_source=10,
    )
    second = await generate_proposal_candidates_for_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
        auto_threshold=0.92,
        review_threshold=0.62,
        limit_per_source=10,
    )

    assert second == first
    rows = (
        (await db_session.execute(select(EntityResolutionCandidate))).scalars().all()
    )
    assert len(rows) == first.generated_count


async def _seed_candidate_graph(
    session: AsyncSession,
) -> tuple[Tenant, ExtractionRun, ExtractedEntity, ExtractedEntity, CanonicalEntity]:
    tenant = Tenant(name="proposal-candidates")
    other_tenant = Tenant(name="proposal-candidates-other")
    session.add_all([tenant, other_tenant])
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

    run = ExtractionRun(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        status=ExtractionRunStatus.READY,
        schema_version="1",
        prompt_version="proposal-v1",
        extractor_version="deterministic-v1",
        model_provider="deterministic",
        model_name="deterministic",
        input_hash="sha256:input",
    )
    session.add(run)
    await session.flush()

    source = ExtractedEntity(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        extraction_run_id=run.id,
        stable_id="xe_source",
        local_id="e1",
        name="Acme Corp",
        normalized_name="acme corp",
        entity_type=EntityType.ORGANIZATION,
        aliases=["ACME"],
        confidence=0.9,
        attributes={},
        status=StagedProposalStatus.ACCEPTED,
    )
    staged_target = ExtractedEntity(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        extraction_run_id=run.id,
        stable_id="xe_staged_target",
        local_id="e2",
        name="Acme Corp",
        normalized_name="acme corp",
        entity_type=EntityType.ORGANIZATION,
        aliases=[],
        confidence=0.85,
        attributes={},
        status=StagedProposalStatus.ACCEPTED,
    )
    unrelated = ExtractedEntity(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        extraction_run_id=run.id,
        stable_id="xe_unrelated",
        local_id="e3",
        name="Berlin",
        normalized_name="berlin",
        entity_type=EntityType.PLACE,
        aliases=[],
        confidence=0.8,
        attributes={},
        status=StagedProposalStatus.ACCEPTED,
    )
    session.add_all([source, staged_target, unrelated])
    await session.flush()

    canonical_target = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Acme Corporation",
        normalized_name="acme corporation",
        status=EntityStatus.ACTIVE,
    )
    deprecated = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Deprecated Acme",
        normalized_name="acme corp",
        status=EntityStatus.DEPRECATED,
    )
    foreign = CanonicalEntity(
        tenant_id=other_tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Acme Corp",
        normalized_name="acme corp",
        status=EntityStatus.ACTIVE,
    )
    session.add_all([canonical_target, deprecated, foreign])
    await session.flush()
    session.add(
        EntityAlias(
            tenant_id=tenant.id,
            canonical_entity_id=canonical_target.id,
            surface_form="Acme Corp",
            normalized_form="acme corp",
            source=AliasSource.EXTRACTION,
        )
    )
    await session.flush()

    return tenant, run, source, staged_target, canonical_target
