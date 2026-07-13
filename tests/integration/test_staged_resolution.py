from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.application.services.staged_resolution import (
    resolve_pending_staged_entities,
    resolve_staged_extraction_run,
)
from atlas_rag.domain.enums import (
    AliasSource,
    CandidateOutcome,
    CandidateTargetKind,
    EntityStatus,
    EntityType,
    ExtractionRunStatus,
    MergeCandidateStatus,
    RelationshipStatus,
    SourceType,
    StagedProposalStatus,
    StagedResolutionStatus,
)
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    Document,
    DocumentVersion,
    EntityAlias,
    EntityRelationship,
    EntityResolutionCandidate,
    ExtractedClaim,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionRun,
    MergeDecision,
    Tenant,
)


async def test_staged_resolution_auto_attaches_to_canonical_candidate(
    db_session: AsyncSession,
) -> None:
    tenant, run = await _seed_run(db_session)
    extracted = await _extracted_entity(
        db_session,
        tenant=tenant,
        run=run,
        local_id="e1",
        name="Acme Corp",
        normalized_name="acme corp",
        entity_type=EntityType.ORGANIZATION,
        aliases=["ACME"],
    )
    canonical = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Acme Corporation",
        normalized_name="acme corporation",
        status=EntityStatus.ACTIVE,
        support_count=3,
    )
    db_session.add(canonical)
    await db_session.flush()
    candidate = EntityResolutionCandidate(
        tenant_id=tenant.id,
        source_extracted_entity_id=extracted.id,
        target_kind=CandidateTargetKind.CANONICAL_ENTITY,
        target_canonical_entity_id=canonical.id,
        score=1.0,
        features={"alias_exact": True},
        reasons=["alias_exact"],
        outcome=CandidateOutcome.AUTO,
        status=MergeCandidateStatus.PENDING,
    )
    db_session.add(candidate)
    await db_session.flush()

    result = await resolve_staged_extraction_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
    )
    second = await resolve_staged_extraction_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
    )

    assert result.source_entity_count == 1
    assert result.auto_attached == 1
    assert second.source_entity_count == 0
    await db_session.refresh(extracted)
    await db_session.refresh(canonical)
    await db_session.refresh(candidate)
    assert extracted.resolution_status == StagedResolutionStatus.RESOLVED
    assert extracted.resolved_canonical_entity_id == canonical.id
    assert extracted.resolved_by_candidate_id == candidate.id
    assert canonical.support_count == 4
    assert candidate.status == MergeCandidateStatus.APPLIED

    alias = await db_session.scalar(select(EntityAlias))
    assert alias is not None
    assert alias.source == AliasSource.EXTRACTION
    assert alias.normalized_form == "acme corp"
    assert (await db_session.scalar(select(MergeDecision))) is not None


async def test_staged_resolution_creates_new_canonical_entity_without_candidate(
    db_session: AsyncSession,
) -> None:
    tenant, run = await _seed_run(db_session)
    extracted = await _extracted_entity(
        db_session,
        tenant=tenant,
        run=run,
        local_id="e1",
        name="Jane Doe",
        normalized_name="jane doe",
        entity_type=EntityType.PERSON,
    )

    result = await resolve_staged_extraction_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
    )

    assert result.new_entities == 1
    await db_session.refresh(extracted)
    entity = await db_session.scalar(select(CanonicalEntity))
    assert entity is not None
    assert entity.canonical_name == "Jane Doe"
    assert entity.support_count == 1
    assert extracted.resolved_canonical_entity_id == entity.id
    assert extracted.resolution_status == StagedResolutionStatus.RESOLVED


async def test_staged_resolution_groups_same_run_duplicate_entities(
    db_session: AsyncSession,
) -> None:
    tenant, run = await _seed_run(db_session)
    source = await _extracted_entity(
        db_session,
        tenant=tenant,
        run=run,
        local_id="e1",
        name="Acme Corp",
        normalized_name="acme corp",
        entity_type=EntityType.ORGANIZATION,
    )
    target = await _extracted_entity(
        db_session,
        tenant=tenant,
        run=run,
        local_id="e2",
        name="ACME Corporation",
        normalized_name="acme corporation",
        entity_type=EntityType.ORGANIZATION,
    )
    duplicate_candidate = EntityResolutionCandidate(
        tenant_id=tenant.id,
        source_extracted_entity_id=source.id,
        target_kind=CandidateTargetKind.EXTRACTED_ENTITY,
        target_extracted_entity_id=target.id,
        score=0.98,
        features={"acronym_match": True},
        reasons=["acronym_match"],
        outcome=CandidateOutcome.AUTO,
        status=MergeCandidateStatus.PENDING,
    )
    db_session.add(duplicate_candidate)
    await db_session.flush()

    result = await resolve_staged_extraction_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
    )

    assert result.new_entities == 1
    await db_session.refresh(source)
    await db_session.refresh(target)
    await db_session.refresh(duplicate_candidate)
    assert source.resolved_canonical_entity_id == target.resolved_canonical_entity_id
    assert source.resolution_status == StagedResolutionStatus.RESOLVED
    assert target.resolution_status == StagedResolutionStatus.RESOLVED
    assert duplicate_candidate.status == MergeCandidateStatus.APPLIED
    canonical = await db_session.scalar(select(CanonicalEntity))
    assert canonical is not None
    assert canonical.support_count == 2


async def test_staged_resolution_leaves_review_candidate_pending(
    db_session: AsyncSession,
) -> None:
    tenant, run = await _seed_run(db_session)
    extracted = await _extracted_entity(
        db_session,
        tenant=tenant,
        run=run,
        local_id="e1",
        name="Acme Corporation",
        normalized_name="acme corporation",
        entity_type=EntityType.ORGANIZATION,
    )
    canonical = CanonicalEntity(
        tenant_id=tenant.id,
        entity_type=EntityType.ORGANIZATION,
        canonical_name="Acme Corp",
        normalized_name="acme corp",
        status=EntityStatus.ACTIVE,
    )
    db_session.add(canonical)
    await db_session.flush()
    candidate = EntityResolutionCandidate(
        tenant_id=tenant.id,
        source_extracted_entity_id=extracted.id,
        target_kind=CandidateTargetKind.CANONICAL_ENTITY,
        target_canonical_entity_id=canonical.id,
        score=0.7,
        features={"sequence_similarity": 0.75},
        reasons=["sequence_similarity"],
        outcome=CandidateOutcome.REVIEW,
        status=MergeCandidateStatus.PENDING,
    )
    db_session.add(candidate)
    await db_session.flush()

    result = await resolve_staged_extraction_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
    )

    assert result.review_queued == 1
    await db_session.refresh(extracted)
    await db_session.refresh(candidate)
    assert extracted.resolution_status == StagedResolutionStatus.REVIEW
    assert extracted.resolved_canonical_entity_id is None
    assert candidate.status == MergeCandidateStatus.PENDING


async def test_staged_resolution_rebuilds_relationship_support_without_inflation(
    db_session: AsyncSession,
) -> None:
    tenant, run = await _seed_run(db_session)
    acme = await _extracted_entity(
        db_session,
        tenant=tenant,
        run=run,
        local_id="e1",
        name="Acme Corp",
        normalized_name="acme corp",
        entity_type=EntityType.ORGANIZATION,
    )
    berlin = await _extracted_entity(
        db_session,
        tenant=tenant,
        run=run,
        local_id="e2",
        name="Berlin",
        normalized_name="berlin",
        entity_type=EntityType.PLACE,
    )
    db_session.add_all(
        [
            ExtractedRelation(
                tenant_id=tenant.id,
                document_id=run.document_id,
                document_version_id=run.document_version_id,
                extraction_run_id=run.id,
                stable_id="xr_1",
                local_id="r1",
                subject_extracted_entity_id=acme.id,
                predicate="headquartered_in",
                object_extracted_entity_id=berlin.id,
                confidence=0.9,
                attributes={},
                status=StagedProposalStatus.ACCEPTED,
            ),
            ExtractedClaim(
                tenant_id=tenant.id,
                document_id=run.document_id,
                document_version_id=run.document_version_id,
                extraction_run_id=run.id,
                stable_id="xc_1",
                local_id="c1",
                subject_extracted_entity_id=acme.id,
                predicate="headquartered_in",
                object_extracted_entity_id=berlin.id,
                confidence=0.8,
                attributes={},
                status=StagedProposalStatus.ACCEPTED,
            ),
        ]
    )
    await db_session.flush()

    first = await resolve_staged_extraction_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
    )
    second = await resolve_staged_extraction_run(
        db_session,
        tenant_id=tenant.id,
        extraction_run_id=run.id,
    )

    assert first.relationships_upserted == 1
    assert second.relationships_upserted == 1
    relationship = await db_session.scalar(select(EntityRelationship))
    assert relationship is not None
    assert relationship.status == RelationshipStatus.ACTIVE
    assert relationship.support_count == 2
    assert {item["source"] for item in relationship.provenance} == {
        "staged_extracted_relation",
        "staged_extracted_claim",
    }


async def test_tenant_level_staged_resolution_drains_ready_runs(
    db_session: AsyncSession,
) -> None:
    tenant, first_run = await _seed_run(db_session)
    second_run = await _seed_additional_run(db_session, tenant=tenant)
    await _extracted_entity(
        db_session,
        tenant=tenant,
        run=first_run,
        local_id="e1",
        name="Jane Doe",
        normalized_name="jane doe",
        entity_type=EntityType.PERSON,
    )
    await _extracted_entity(
        db_session,
        tenant=tenant,
        run=second_run,
        local_id="e1",
        name="Berlin",
        normalized_name="berlin",
        entity_type=EntityType.PLACE,
    )

    result = await resolve_pending_staged_entities(db_session, tenant_id=tenant.id)
    second = await resolve_pending_staged_entities(db_session, tenant_id=tenant.id)

    assert result.source_entity_count == 2
    assert result.new_entities == 2
    assert second.source_entity_count == 0
    entities = (await db_session.execute(select(CanonicalEntity))).scalars().all()
    assert {entity.normalized_name for entity in entities} == {"jane doe", "berlin"}


async def _seed_run(session: AsyncSession) -> tuple[Tenant, ExtractionRun]:
    tenant = Tenant(name="staged-resolution")
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
    return tenant, run


async def _seed_additional_run(
    session: AsyncSession, *, tenant: Tenant
) -> ExtractionRun:
    document = Document(
        tenant_id=tenant.id,
        title="Doc 2",
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
        input_hash=f"sha256:input-{document.id}",
    )
    session.add(run)
    await session.flush()
    return run


async def _extracted_entity(
    session: AsyncSession,
    *,
    tenant: Tenant,
    run: ExtractionRun,
    local_id: str,
    name: str,
    normalized_name: str,
    entity_type: EntityType,
    aliases: list[str] | None = None,
) -> ExtractedEntity:
    entity = ExtractedEntity(
        tenant_id=tenant.id,
        document_id=run.document_id,
        document_version_id=run.document_version_id,
        extraction_run_id=run.id,
        stable_id=f"xe_{run.id}_{local_id}",
        local_id=local_id,
        name=name,
        normalized_name=normalized_name,
        entity_type=entity_type,
        aliases=aliases or [],
        confidence=0.9,
        attributes={},
        status=StagedProposalStatus.ACCEPTED,
        resolution_status=StagedResolutionStatus.PENDING,
    )
    session.add(entity)
    await session.flush()
    return entity
