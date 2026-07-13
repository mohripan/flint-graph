from __future__ import annotations

from uuid import UUID

from temporalio import activity
from temporalio.common import WorkflowIDConflictPolicy

from atlas_rag.application.services.resolution import (
    ResolutionConfig,
    acquire_tenant_resolution_lock,
    resolve_pending_mentions,
)
from atlas_rag.config import Settings, get_settings
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.infrastructure.temporal import connect_temporal
from atlas_rag.workflows.resolution import (
    ENQUEUE_TENANT_RESOLUTION_ACTIVITY,
    REQUEST_RESOLUTION_SIGNAL,
    RESOLVE_ENTITIES_WORKFLOW,
    RESOLVE_TENANT_ENTITIES_ACTIVITY,
)


def _resolution_config(settings: Settings) -> ResolutionConfig:
    return ResolutionConfig(
        auto_threshold=settings.entity_resolution_auto_threshold,
        review_threshold=settings.entity_resolution_review_threshold,
        trigram_threshold=settings.entity_resolution_trigram_threshold,
        candidate_limit=settings.entity_resolution_candidate_limit,
    )


@activity.defn(name=RESOLVE_TENANT_ENTITIES_ACTIVITY)
async def resolve_tenant_entities(tenant_id: str) -> int:
    settings = get_settings()
    config = _resolution_config(settings)
    async with SessionFactory() as session:
        try:
            await acquire_tenant_resolution_lock(session, UUID(tenant_id))
            result = await resolve_pending_mentions(
                session, tenant_id=UUID(tenant_id), config=config
            )
            await session.commit()
            return result.mentions_processed
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=ENQUEUE_TENANT_RESOLUTION_ACTIVITY)
async def enqueue_tenant_resolution(tenant_id: str) -> None:
    settings = get_settings()
    client = await connect_temporal(settings)
    await client.start_workflow(
        RESOLVE_ENTITIES_WORKFLOW,
        tenant_id,
        id=f"entity-resolution-{tenant_id}",
        task_queue=settings.temporal_task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        start_signal=REQUEST_RESOLUTION_SIGNAL,
    )
