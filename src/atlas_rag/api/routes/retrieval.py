from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from atlas_rag.api.dependencies import (
    EmbeddingModelDep,
    IndexBackfillWorkflowStarterDep,
    Neo4jClientDep,
    OpenSearchClientDep,
    SessionDep,
    TenantIdDep,
)
from atlas_rag.api.schemas import (
    CanonicalEntitySummary,
    DocumentIndexCoverageResponse,
    EntityNeighborhoodResponse,
    EntityRelationshipSummary,
    IndexBackfillCreateRequest,
    IndexBackfillJobResponse,
    RetrievalChunkResultResponse,
    RetrievalIndexVersionResponse,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from atlas_rag.application.services.retrieval import (
    create_tenant_index_backfill_job,
    get_tenant_index_backfill_job,
    lexical_search,
    list_index_coverage,
    list_index_versions,
    load_entity_neighborhood,
    vector_search,
)
from atlas_rag.domain.enums import (
    DocumentIndexCoverageStatus,
    RetrievalIndexVersionStatus,
)

router = APIRouter(prefix="/v1", tags=["retrieval"])


@router.get("/index-versions", response_model=list[RetrievalIndexVersionResponse])
async def get_index_versions(
    tenant_id: TenantIdDep,
    session: SessionDep,
    status: RetrievalIndexVersionStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RetrievalIndexVersionResponse]:
    versions = await list_index_versions(
        session,
        tenant_id=tenant_id,
        status=status,
        limit=limit,
    )
    return [RetrievalIndexVersionResponse.model_validate(version) for version in versions]


@router.get("/index-coverage", response_model=list[DocumentIndexCoverageResponse])
async def get_index_coverage(
    tenant_id: TenantIdDep,
    session: SessionDep,
    retrieval_index_version_id: UUID | None = None,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
    status: DocumentIndexCoverageStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DocumentIndexCoverageResponse]:
    coverage = await list_index_coverage(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
        document_id=document_id,
        document_version_id=document_version_id,
        status=status,
        limit=limit,
    )
    return [DocumentIndexCoverageResponse.model_validate(row) for row in coverage]


@router.post("/index-backfills", response_model=IndexBackfillJobResponse)
async def create_index_backfill(
    payload: IndexBackfillCreateRequest,
    tenant_id: TenantIdDep,
    session: SessionDep,
    starter: IndexBackfillWorkflowStarterDep,
) -> IndexBackfillJobResponse:
    job = await create_tenant_index_backfill_job(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=payload.retrieval_index_version_id,
        document_id=payload.document_id,
        document_version_id=payload.document_version_id,
    )
    await session.commit()
    await starter.start_index_backfill_workflow(job_id=job.id)
    return IndexBackfillJobResponse.model_validate(job)


@router.get("/index-backfills/{job_id}", response_model=IndexBackfillJobResponse)
async def get_index_backfill(
    job_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> IndexBackfillJobResponse:
    job = await get_tenant_index_backfill_job(session, tenant_id=tenant_id, job_id=job_id)
    return IndexBackfillJobResponse.model_validate(job)


@router.post("/search/lexical", response_model=RetrievalSearchResponse)
async def search_lexical(
    payload: RetrievalSearchRequest,
    tenant_id: TenantIdDep,
    session: SessionDep,
    opensearch_client: OpenSearchClientDep,
) -> RetrievalSearchResponse:
    result = await lexical_search(
        session,
        tenant_id=tenant_id,
        opensearch_client=opensearch_client,
        query=payload.query,
        limit=payload.limit,
        retrieval_index_version_id=payload.retrieval_index_version_id,
        filters=payload.filters,
    )
    return RetrievalSearchResponse(
        index_version_id=result.index_version.id,
        results=[
            RetrievalChunkResultResponse.model_validate(chunk) for chunk in result.results
        ],
    )


@router.post("/search/vector", response_model=RetrievalSearchResponse)
async def search_vector(
    payload: RetrievalSearchRequest,
    tenant_id: TenantIdDep,
    session: SessionDep,
    neo4j_client: Neo4jClientDep,
    embedding_model: EmbeddingModelDep,
) -> RetrievalSearchResponse:
    result = await vector_search(
        session,
        tenant_id=tenant_id,
        neo4j_client=neo4j_client,
        embedding_model=embedding_model,
        query=payload.query,
        limit=payload.limit,
        retrieval_index_version_id=payload.retrieval_index_version_id,
        filters=payload.filters,
    )
    return RetrievalSearchResponse(
        index_version_id=result.index_version.id,
        results=[
            RetrievalChunkResultResponse.model_validate(chunk) for chunk in result.results
        ],
    )


@router.get("/entities/{entity_id}/neighborhood", response_model=EntityNeighborhoodResponse)
async def get_entity_neighborhood(
    entity_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    depth: int = Query(default=1, ge=1, le=3),
    limit: int = Query(default=25, ge=1, le=100),
) -> EntityNeighborhoodResponse:
    neighborhood = await load_entity_neighborhood(
        session,
        tenant_id=tenant_id,
        entity_id=entity_id,
        depth=depth,
        limit=limit,
    )
    return EntityNeighborhoodResponse(
        root_entity_id=neighborhood.root_entity_id,
        depth=neighborhood.depth,
        entities=[
            CanonicalEntitySummary.model_validate(entity)
            for entity in neighborhood.entities
        ],
        relationships=[
            EntityRelationshipSummary.model_validate(relationship)
            for relationship in neighborhood.relationships
        ],
    )
