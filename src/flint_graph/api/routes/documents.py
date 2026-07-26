from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Query, Response, UploadFile, status

from flint_graph.api.dependencies import (
    AuditActorDep,
    ObjectStoreDep,
    SessionDep,
    SettingsDep,
    TenantAdminDep,
    TenantIdDep,
    TenantMemberDep,
    URLFetcherDep,
)
from flint_graph.api.schemas import (
    DocumentCreate,
    DocumentDeleteResponse,
    DocumentIntakeResponse,
    DocumentLifecycleEventResponse,
    DocumentListItemResponse,
    DocumentProjectionCleanupResponse,
    DocumentResponse,
    IngestionJobEventResponse,
    IngestionJobResponse,
    URLIntakeCreate,
)
from flint_graph.application.services.audit import record_audit_event
from flint_graph.application.services.document_lifecycle import (
    delete_document,
    list_lifecycle_events,
    list_projection_cleanups,
    retry_projection_cleanups,
)
from flint_graph.application.services.documents import create_document, list_documents
from flint_graph.application.services.ingestion_jobs import (
    JobRecord,
    create_ingestion_job,
    get_ingestion_job,
    list_ingestion_job_events,
)
from flint_graph.application.services.intake import (
    IntakeRecord,
    create_upload_intake,
    create_url_intake,
)
from flint_graph.application.services.job_cancellation import cancel_ingestion_job
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import PayloadTooLargeError

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


def _intake_response(record: IntakeRecord) -> DocumentIntakeResponse:
    return DocumentIntakeResponse(
        document_id=record.document.id,
        document_version_id=record.version.id,
        ingestion_job_id=record.job.id,
        tenant_id=record.job.tenant_id,
        title=record.document.title,
        source_type=record.document.source_type,
        source_uri=record.document.source_uri,
        external_id=record.document.external_id,
        version_number=record.version_number,
        job_status=record.job.status,
        idempotency_key=record.job.idempotency_key,
        object_uri=record.version.object_uri or "",
        content_hash=record.version.content_hash or "",
        created_at=record.job.created_at,
    )


@router.get("/documents", response_model=list[DocumentListItemResponse])
async def list_documents_endpoint(
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DocumentListItemResponse]:
    documents = await list_documents(session, tenant_id=tenant_id, limit=limit)
    return [DocumentListItemResponse(**asdict(document)) for document in documents]


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document_endpoint(
    payload: DocumentCreate,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> DocumentResponse:
    document = await create_document(
        session,
        tenant_id=tenant_id,
        title=payload.title,
        source_type=payload.source_type,
        source_uri=payload.source_uri,
        external_id=payload.external_id,
    )
    await record_audit_event(
        session,
        action=AuditAction.DOCUMENT_CREATED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="document",
        resource_id=document.id,
        metadata={"source_type": document.source_type.value},
    )
    return DocumentResponse.model_validate(document)


@router.post(
    "/documents/uploads",
    response_model=DocumentIntakeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_endpoint(
    response: Response,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    object_store: ObjectStoreDep,
    settings: SettingsDep,
    actor: AuditActorDep,
    title: Annotated[str, Form(min_length=1, max_length=500)],
    file: Annotated[UploadFile, File()],
    external_id: Annotated[str | None, Form(max_length=500)] = None,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
) -> DocumentIntakeResponse:
    max_upload_bytes = settings.max_upload_bytes or settings.intake_max_source_bytes
    data = await file.read(max_upload_bytes + 1)
    await file.close()
    if len(data) > max_upload_bytes:
        raise PayloadTooLargeError("Uploaded file exceeds the intake limit.")

    record = await create_upload_intake(
        session,
        object_store=object_store,
        bucket=settings.object_store_bucket,
        tenant_id=tenant_id,
        title=title,
        external_id=external_id,
        idempotency_key=idempotency_key,
        data=data,
        content_type=file.content_type or "application/octet-stream",
        original_filename=file.filename or None,
    )
    if record.created:
        # Only a new intake is an audited action; a replayed idempotency key
        # returns the existing record and creates nothing.
        await record_audit_event(
            session,
            action=AuditAction.DOCUMENT_INTAKE_CREATED,
            actor=actor,
            tenant_id=tenant_id,
            resource_type="document",
            resource_id=record.document.id,
            metadata={
                "source_type": record.document.source_type.value,
                "document_version_id": str(record.version.id),
                "ingestion_job_id": str(record.job.id),
                "byte_count": len(data),
            },
        )
    else:
        response.status_code = status.HTTP_200_OK
    return _intake_response(record)


@router.post(
    "/documents/from-url",
    response_model=DocumentIntakeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_from_url_endpoint(
    payload: URLIntakeCreate,
    response: Response,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    object_store: ObjectStoreDep,
    settings: SettingsDep,
    url_fetcher: URLFetcherDep,
    actor: AuditActorDep,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
) -> DocumentIntakeResponse:
    fetched = await url_fetcher.fetch(payload.source_url)
    record = await create_url_intake(
        session,
        object_store=object_store,
        bucket=settings.object_store_bucket,
        tenant_id=tenant_id,
        title=payload.title,
        source_url=payload.source_url,
        external_id=payload.external_id,
        idempotency_key=idempotency_key,
        data=fetched.body,
        content_type=fetched.content_type,
        final_url=fetched.final_url,
    )
    if record.created:
        await record_audit_event(
            session,
            action=AuditAction.DOCUMENT_INTAKE_CREATED,
            actor=actor,
            tenant_id=tenant_id,
            resource_type="document",
            resource_id=record.document.id,
            metadata={
                "source_type": record.document.source_type.value,
                "document_version_id": str(record.version.id),
                "ingestion_job_id": str(record.job.id),
                "final_url": fetched.final_url,
                "byte_count": len(fetched.body),
            },
        )
    else:
        response.status_code = status.HTTP_200_OK
    return _intake_response(record)


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document_endpoint(
    document_id: UUID,
    tenant_id: TenantAdminDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> DocumentDeleteResponse:
    result = await delete_document(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        reason="api document delete",
    )
    await record_audit_event(
        session,
        action=AuditAction.DOCUMENT_DELETED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="document",
        resource_id=document_id,
        metadata={
            "deleted_version_count": len(result.deleted_version_ids),
            "cleanup_count": result.cleanup_count,
        },
    )
    return DocumentDeleteResponse(
        document_id=result.document_id,
        deleted_version_ids=result.deleted_version_ids,
        cleanup_count=result.cleanup_count,
    )


@router.get(
    "/documents/{document_id}/lifecycle-events",
    response_model=list[DocumentLifecycleEventResponse],
)
async def list_document_lifecycle_events_endpoint(
    document_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DocumentLifecycleEventResponse]:
    events = await list_lifecycle_events(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        limit=limit,
    )
    return [DocumentLifecycleEventResponse.model_validate(event) for event in events]


@router.get(
    "/documents/{document_id}/projection-cleanups",
    response_model=list[DocumentProjectionCleanupResponse],
)
async def list_document_projection_cleanups_endpoint(
    document_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DocumentProjectionCleanupResponse]:
    cleanups = await list_projection_cleanups(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        limit=limit,
    )
    return [DocumentProjectionCleanupResponse.model_validate(cleanup) for cleanup in cleanups]


@router.post(
    "/documents/{document_id}/projection-cleanups/retry",
    response_model=list[DocumentProjectionCleanupResponse],
)
async def retry_document_projection_cleanups_endpoint(
    document_id: UUID,
    tenant_id: TenantAdminDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> list[DocumentProjectionCleanupResponse]:
    cleanups = await retry_projection_cleanups(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
    )
    await record_audit_event(
        session,
        action=AuditAction.PROJECTION_CLEANUP_RETRIED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="document",
        resource_id=document_id,
        metadata={"cleanup_count": len(cleanups)},
    )
    return [DocumentProjectionCleanupResponse.model_validate(cleanup) for cleanup in cleanups]


@router.post(
    "/documents/{document_id}/ingestion-jobs",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_job_endpoint(
    document_id: UUID,
    response: Response,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
    idempotency_key: str = Header(alias="Idempotency-key", min_length=8, max_length=200),
) -> IngestionJobResponse:
    record = await create_ingestion_job(
        session,
        tenant_id=tenant_id,
        document_id=document_id,
        idempotency_key=idempotency_key,
    )
    if record.created:
        await record_audit_event(
            session,
            action=AuditAction.INGESTION_JOB_CREATED,
            actor=actor,
            tenant_id=tenant_id,
            resource_type="ingestion_job",
            resource_id=record.job.id,
            metadata={"document_id": str(document_id)},
        )
    else:
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
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> IngestionJobResponse:
    record = await cancel_ingestion_job(session, tenant_id=tenant_id, job_id=job_id)
    await record_audit_event(
        session,
        action=AuditAction.INGESTION_JOB_CANCELLED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="ingestion_job",
        resource_id=job_id,
        metadata={"status": record.job.status.value},
    )
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
