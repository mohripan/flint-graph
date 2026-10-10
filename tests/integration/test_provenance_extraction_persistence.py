import json
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.extraction_proposals import (
    EvidenceProposal,
    ExtractedClaimProposal,
    ExtractedEntityProposal,
    ExtractedRelationProposal,
    ExtractionBatch,
    ExtractionInputChunk,
)
from flint_graph.application.services.provenance_extraction import (
    ProvenanceExtractionMetadata,
    persist_failed_provenance_extraction_run,
    persist_provenance_extraction_run,
)
from flint_graph.domain.enums import (
    EntityType,
    ExtractionRunStatus,
    SourceType,
    StagedProposalStatus,
)
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentVersion,
    EvidenceSpan,
    ExtractedClaim,
    ExtractedClaimEvidence,
    ExtractedEntity,
    ExtractedEntityEvidence,
    ExtractedRelation,
    ExtractedRelationEvidence,
    ExtractionArtifact,
    ExtractionInvocation,
    ExtractionRun,
    Tenant,
)
from flint_graph.infrastructure.object_store import ObjectInfo


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.metadata: dict[str, dict[str, str]] = {}

    async def put_bytes(
        self,
        uri: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        self.objects[uri] = data
        self.content_types[uri] = content_type
        self.metadata[uri] = dict(metadata or {})

    async def get_bytes(self, uri: str) -> bytes:
        return self.objects[uri]

    async def head_object(self, uri: str) -> ObjectInfo:
        return ObjectInfo(
            size_bytes=len(self.objects[uri]),
            content_type=self.content_types[uri],
            metadata=self.metadata[uri],
        )


async def test_persist_provenance_extraction_run_records_staged_batch(
    db_session: AsyncSession,
) -> None:
    tenant, document, version = await _seed_document(db_session)
    store = FakeObjectStore()
    chunks = [
        ExtractionInputChunk(
            chunk_id="chunk-000001",
            text="Acme Corporation is headquartered in Berlin.",
        )
    ]
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                aliases=["Acme"],
                confidence=0.91,
                attributes={"ticker": "ACME"},
                evidence=[
                    EvidenceProposal(chunk_id="chunk-000001", quote="Acme Corporation")
                ],
            ),
            ExtractedEntityProposal(
                local_id="e2",
                name="Berlin",
                entity_type="place",
                confidence=0.88,
                evidence=[EvidenceProposal(chunk_id="chunk-000001", quote="Berlin")],
            ),
        ],
        relations=[
            ExtractedRelationProposal(
                local_id="r1",
                subject_entity_id="e1",
                predicate="headquartered_in",
                object_entity_id="e2",
                confidence=0.82,
                evidence=[
                    EvidenceProposal(
                        chunk_id="chunk-000001",
                        quote="Acme Corporation is headquartered in Berlin",
                    )
                ],
            )
        ],
        claims=[
            ExtractedClaimProposal(
                local_id="c1",
                subject_entity_id="e1",
                predicate="headquartered_in",
                object_entity_id="e2",
                confidence=0.8,
                evidence=[
                    EvidenceProposal(
                        chunk_id="chunk-000001",
                        quote="Acme Corporation is headquartered in Berlin",
                    )
                ],
            )
        ],
    )

    result = await persist_provenance_extraction_run(
        db_session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        document_id=document.id,
        version_id=version.id,
        chunks=chunks,
        batch=batch,
        metadata=ProvenanceExtractionMetadata(
            prompt_version="proposal-v1",
            extractor_version="deterministic-v1",
            model_provider="deterministic",
            model_name="deterministic",
            request_hash="sha256:request",
            response_hash="sha256:response",
            latency_ms=12,
        ),
    )

    run = await db_session.get(ExtractionRun, result.extraction_run_id)
    assert run is not None
    assert run.status == ExtractionRunStatus.READY
    assert run.accepted_entity_count == 2
    assert run.accepted_relation_count == 1
    assert run.accepted_claim_count == 1
    assert run.manifest_uri == result.manifest_uri
    assert run.manifest_hash.startswith("sha256:")

    invocation = (await db_session.execute(select(ExtractionInvocation))).scalar_one()
    assert invocation.input_chunk_ids == ["chunk-000001"]
    assert invocation.request_hash == "sha256:request"
    assert invocation.response_hash == "sha256:response"
    assert invocation.latency_ms == 12

    entities = list((await db_session.execute(select(ExtractedEntity))).scalars().all())
    assert [(entity.local_id, entity.entity_type) for entity in entities] == [
        ("e1", EntityType.ORGANIZATION),
        ("e2", EntityType.PLACE),
    ]
    assert entities[0].normalized_name == "acme corporation"
    assert entities[0].aliases == ["Acme"]
    assert entities[0].attributes == {"ticker": "ACME"}
    assert entities[0].status == StagedProposalStatus.ACCEPTED
    assert entities[0].stable_id.startswith("xe_")

    relation = (await db_session.execute(select(ExtractedRelation))).scalar_one()
    assert relation.subject_extracted_entity_id == entities[0].id
    assert relation.object_extracted_entity_id == entities[1].id
    assert relation.stable_id.startswith("xr_")

    claim = (await db_session.execute(select(ExtractedClaim))).scalar_one()
    assert claim.subject_extracted_entity_id == entities[0].id
    assert claim.object_extracted_entity_id == entities[1].id
    assert claim.stable_id.startswith("xc_")

    spans = list((await db_session.execute(select(EvidenceSpan))).scalars().all())
    assert {span.quote for span in spans} == {
        "Acme Corporation",
        "Berlin",
        "Acme Corporation is headquartered in Berlin",
    }

    assert (await db_session.execute(select(ExtractedEntityEvidence))).scalars().all()
    assert (await db_session.execute(select(ExtractedRelationEvidence))).scalars().all()
    assert (await db_session.execute(select(ExtractedClaimEvidence))).scalars().all()

    artifact = (await db_session.execute(select(ExtractionArtifact))).scalar_one()
    assert artifact.object_uri == result.manifest_uri
    assert artifact.content_hash == result.manifest_hash
    assert store.content_types[result.manifest_uri] == "application/json"

    manifest = json.loads(store.objects[result.manifest_uri])
    assert manifest["schema_version"] == "1"
    assert manifest["source"]["document_version_id"] == str(version.id)
    assert manifest["counts"] == {"entities": 2, "relations": 1, "claims": 1, "spans": 3}


async def test_persist_provenance_extraction_run_reuses_ready_run_on_retry(
    db_session: AsyncSession,
) -> None:
    tenant, document, version = await _seed_document(db_session)
    store = FakeObjectStore()
    chunks = [
        ExtractionInputChunk(
            chunk_id="chunk-000001",
            text="Acme Corporation is headquartered in Berlin.",
        )
    ]
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="Acme Corporation",
                entity_type="organization",
                evidence=[
                    EvidenceProposal(chunk_id="chunk-000001", quote="Acme Corporation")
                ],
            )
        ],
    )
    metadata = ProvenanceExtractionMetadata(
        prompt_version="proposal-v1",
        extractor_version="deterministic-v1",
        model_provider="deterministic",
        model_name="deterministic",
        request_hash="sha256:request",
        response_hash="sha256:response",
    )

    first = await persist_provenance_extraction_run(
        db_session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        document_id=document.id,
        version_id=version.id,
        chunks=chunks,
        batch=batch,
        metadata=metadata,
    )
    second = await persist_provenance_extraction_run(
        db_session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        document_id=document.id,
        version_id=version.id,
        chunks=chunks,
        batch=batch,
        metadata=metadata,
    )

    assert second == first
    assert len((await db_session.execute(select(ExtractionRun))).scalars().all()) == 1
    assert len((await db_session.execute(select(ExtractedEntity))).scalars().all()) == 1
    assert len((await db_session.execute(select(EvidenceSpan))).scalars().all()) == 1
    assert len(store.objects) == 1


async def _seed_document(
    session: AsyncSession,
) -> tuple[Tenant, Document, DocumentVersion]:
    tenant = Tenant(name="provenance-persistence")
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

    return tenant, document, version


async def test_identical_quotes_in_one_tenant_have_distinct_document_version_evidence(
    extraction_db_session: AsyncSession,
) -> None:
    db_session = extraction_db_session
    tenant, first_document, first_version = await _seed_document(db_session)
    second_document = Document(tenant_id=tenant.id, title="Second", source_type=SourceType.UPLOAD)
    db_session.add(second_document)
    await db_session.flush()
    second_version = DocumentVersion(document_id=second_document.id, version_number=1)
    next_version = DocumentVersion(document_id=first_document.id, version_number=2)
    db_session.add_all([second_version, next_version])
    await db_session.flush()
    chunks = [ExtractionInputChunk(chunk_id="chunk-000001", text="Historical FinQA report.")]
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"],
        entities=[
            ExtractedEntityProposal(
                local_id="e1",
                name="FinQA",
                entity_type="organization",
                evidence=[EvidenceProposal(chunk_id="chunk-000001", quote="FinQA")],
            )
        ],
    )
    metadata = ProvenanceExtractionMetadata(
        prompt_version="proposal-v1",
        extractor_version="deterministic-v1",
        model_provider="deterministic",
        model_name="deterministic",
        request_hash="sha256:request",
    )
    store = FakeObjectStore()
    results = []
    for document, version in (
        (first_document, first_version),
        (second_document, second_version),
        (first_document, next_version),
    ):
        result = await persist_provenance_extraction_run(
            db_session,
            object_store=store,
            bucket="flint-graph",
            tenant_id=tenant.id,
            document_id=document.id,
            version_id=version.id,
            chunks=chunks,
            batch=batch,
            metadata=metadata,
        )
        results.append(result)
        await db_session.flush()
    retry = await persist_provenance_extraction_run(
        db_session,
        object_store=store,
        bucket="flint-graph",
        tenant_id=tenant.id,
        document_id=first_document.id,
        version_id=first_version.id,
        chunks=chunks,
        batch=batch,
        metadata=metadata,
    )
    assert retry == results[0]
    spans = list((await db_session.scalars(select(EvidenceSpan))).all())
    assert len(spans) == 3
    assert len({span.stable_id for span in spans}) == 3
    assert {(span.start_offset, span.end_offset, span.quote) for span in spans} == {
        (11, 16, "FinQA")
    }
    for result in results:
        manifest = json.loads(store.objects[result.manifest_uri])
        assert manifest["counts"]["spans"] == 1


async def test_failed_extraction_can_retry_successfully_without_losing_invocation_history(
    extraction_db_session: AsyncSession,
) -> None:
    session = extraction_db_session
    tenant, document, version = await _seed_document(session)
    chunks = [ExtractionInputChunk(chunk_id="chunk-000001", text="Acme Corporation.")]
    metadata = ProvenanceExtractionMetadata(
        prompt_version="proposal-v1", extractor_version="fixture-v1",
        model_provider="deterministic",
        model_name="fixture", request_hash="sha256:request",
    )
    for attempt in range(2):
        failed = await persist_failed_provenance_extraction_run(
            session, tenant_id=tenant.id, document_id=document.id, version_id=version.id,
            chunks=chunks, metadata=metadata, error_code="fixture_failure",
            error_message=f"attempt {attempt}",
        )
    batch = ExtractionBatch(
        input_chunk_ids=["chunk-000001"], entities=[ExtractedEntityProposal(
            local_id="e1", name="Acme Corporation", entity_type="organization",
            evidence=[EvidenceProposal(chunk_id="chunk-000001", quote="Acme Corporation")],
        )],
    )
    store = FakeObjectStore()
    ready = await persist_provenance_extraction_run(
        session, object_store=store, bucket="flint-graph", tenant_id=tenant.id,
        document_id=document.id, version_id=version.id,
        chunks=chunks, batch=batch, metadata=metadata,
    )
    assert ready.extraction_run_id == failed.extraction_run_id
    run = await session.get(ExtractionRun, ready.extraction_run_id)
    assert run.status == ExtractionRunStatus.READY and run.invocation_count == 3
    invocations = list((await session.scalars(
        select(ExtractionInvocation).order_by(ExtractionInvocation.invocation_index)
    )).all())
    assert [item.invocation_index for item in invocations] == [0, 1, 2]
    assert [item.status.value for item in invocations] == ["failed", "failed", "succeeded"]
    assert [item.error_message for item in invocations[:2]] == ["attempt 0", "attempt 1"]
    # An error on a later provider retry must not invalidate existing verified provenance.
    await persist_failed_provenance_extraction_run(
        session, tenant_id=tenant.id, document_id=document.id, version_id=version.id,
        chunks=chunks, metadata=metadata, error_code="later_failure",
        error_message="provider unavailable",
    )
    assert run.status == ExtractionRunStatus.READY and run.invocation_count == 4
    assert len((await session.scalars(select(EvidenceSpan))).all()) == 1
