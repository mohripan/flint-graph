from uuid import UUID

from fastapi import APIRouter, Header, Response, status

from atlas_rag.api.dependencies import SessionDep, TenantIdDep
from atlas_rag.api.schemas import (
    DocumentCreate,
    DocumentResponse,
    IngestionJobEventResponse,
    IngestionJobResponse,
)
from atlas_rag.application.services.documents import create_document
from atlas_rag.application.services.ingestion_jobs import (
    JobRecord,
    create_ingestion_job,
    get_ingestion_job,
    list_ingestion_job_events,
)
from atlas_rag.application.services.job_cancellation import cancel_ingestion_job

router = APIRouter(prefix="/v1", tags=["documents"])


def _job_response(record: JobRecord) -> IngestionJobResponse:
    job = record.job
    return IngestionJobResponse(
        id=job.id,
        tenant_id=job.tenant_id,
        document_id=job.document_id,
        document_version_id=job.document_version_id,
        version_number=record.version_number,
        status=job.status,
        idempotency_key=job.idempotency_key,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_code=job.error_code,
        error_message=job.error_message,
    )


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document_endpoint(
    payload: DocumentCreate,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> DocumentResponse:
    document = await create_document(
        session,
        tenant_id=tenant_id,
        title=payload.title,
        source_type=payload.source_type,
        source_uri=payload.source_uri,
        external_id=payload.external_id,
    )
    return DocumentResponse.model_validate(document)


@router.post(
    "/documents/{document_id}/ingestion-jobs",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_job_endpoint(
    document_id: UUID,
    response: Response,
    tenant_id: TenantIdDep,
    session: SessionDep,
    idempotency_key: str = Header(alias="Idempotency-key", min_length=8, max_length=200),
) -> IngestionJobResponse:
    record = await create_ingestion_job(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        idempotency_key=idempotency_key,
    )
    if not record.created:
        response.status_code = status.HTTP_200_OK
    return _job_response(record)


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobResponse)
async def get_job_endpoint(
    job_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> IngestionJobResponse:
    record = await get_ingestion_job(session, tenant_id=tenant_id, job_id=job_id)
    return _job_response(record)


@router.post("/ingestion-jobs/{job_id}/cancel", response_model=IngestionJobResponse)
async def cancel_job_endpoint(
    job_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> IngestionJobResponse:
    record = await cancel_ingestion_job(session, tenant_id=tenant_id, job_id=job_id)
    return _job_response(record)


@router.get(
    "/ingestion-jobs/{job_id}/events",
    response_model=list[IngestionJobEventResponse],
)
async def list_job_events_endpoint(
    job_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> list[IngestionJobEventResponse]:
    events = await list_ingestion_job_events(session, tenant_id=tenant_id, job_id=job_id)
    return [IngestionJobEventResponse.model_validate(event) for event in events]
