from __future__ import annotations

from uuid import UUID

from temporalio import activity

from atlas_rag.application.outbox_contracts import (
    BackfillDocumentFailurePayload,
    IndexBackfillPayload,
)
from atlas_rag.application.services.index_backfill import (
    cancel_index_backfill,
    complete_backfill_document,
    complete_index_backfill,
    fail_backfill_document,
    fail_index_backfill,
    load_next_backfill_batch,
    mark_backfill_running,
)
from atlas_rag.config import get_settings
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.workflows.backfill import (
    COMPLETE_INDEX_BACKFILL_ACTIVITY,
    FAIL_INDEX_BACKFILL_ACTIVITY,
    LOAD_INDEX_BACKFILL_BATCH_ACTIVITY,
    MARK_INDEX_BACKFILL_CANCELLED_ACTIVITY,
    MARK_INDEX_BACKFILL_DOCUMENT_COMPLETED_ACTIVITY,
    MARK_INDEX_BACKFILL_DOCUMENT_FAILED_ACTIVITY,
    MARK_INDEX_BACKFILL_RUNNING_ACTIVITY,
)


@activity.defn(name=MARK_INDEX_BACKFILL_RUNNING_ACTIVITY)
async def mark_index_backfill_running(payload: IndexBackfillPayload) -> None:
    async with SessionFactory() as session:
        try:
            await mark_backfill_running(
                session,
                job_id=UUID(payload["backfill_job_id"]),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=LOAD_INDEX_BACKFILL_BATCH_ACTIVITY)
async def load_index_backfill_batch(payload: IndexBackfillPayload) -> dict[str, object]:
    settings = get_settings()
    async with SessionFactory() as session:
        try:
            batch = await load_next_backfill_batch(
                session,
                job_id=UUID(payload["backfill_job_id"]),
                batch_size=settings.index_backfill_batch_size,
            )
            await session.commit()
            return batch.to_payload()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=MARK_INDEX_BACKFILL_DOCUMENT_COMPLETED_ACTIVITY)
async def mark_index_backfill_document_completed(payload: dict[str, str]) -> None:
    async with SessionFactory() as session:
        try:
            await complete_backfill_document(
                session,
                job_id=UUID(payload["backfill_job_id"]),
                document_version_id=UUID(payload["document_version_id"]),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=MARK_INDEX_BACKFILL_DOCUMENT_FAILED_ACTIVITY)
async def mark_index_backfill_document_failed(
    payload: BackfillDocumentFailurePayload,
) -> None:
    async with SessionFactory() as session:
        try:
            await fail_backfill_document(
                session,
                job_id=UUID(payload["backfill_job_id"]),
                document_version_id=UUID(payload["document_version_id"]),
                error_code=payload["error_code"],
                error_message=payload["error_message"],
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=COMPLETE_INDEX_BACKFILL_ACTIVITY)
async def complete_index_backfill_activity(payload: IndexBackfillPayload) -> None:
    async with SessionFactory() as session:
        try:
            await complete_index_backfill(
                session,
                job_id=UUID(payload["backfill_job_id"]),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=FAIL_INDEX_BACKFILL_ACTIVITY)
async def fail_index_backfill_activity(payload: IndexBackfillPayload) -> None:
    async with SessionFactory() as session:
        try:
            await fail_index_backfill(
                session,
                job_id=UUID(payload["backfill_job_id"]),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=MARK_INDEX_BACKFILL_CANCELLED_ACTIVITY)
async def mark_index_backfill_cancelled(payload: IndexBackfillPayload) -> None:
    async with SessionFactory() as session:
        try:
            await cancel_index_backfill(
                session,
                job_id=UUID(payload["backfill_job_id"]),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
