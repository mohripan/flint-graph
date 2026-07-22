import asyncio

from temporalio.worker import Worker

from flint_graph.config import get_settings
from flint_graph.infrastructure.temporal import connect_temporal
from flint_graph.logging import configure_logging
from flint_graph.worker.activities.index_backfill import (
    complete_index_backfill_activity,
    fail_index_backfill_activity,
    load_index_backfill_batch,
    mark_index_backfill_cancelled,
    mark_index_backfill_document_completed,
    mark_index_backfill_document_failed,
    mark_index_backfill_running,
)
from flint_graph.worker.activities.indexing import (
    enqueue_document_indexing,
    index_document_batch,
    mark_document_indexing_cancelled,
    mark_document_indexing_completed,
    mark_document_indexing_failed,
    plan_document_indexing_activity,
    prepare_document_indexing,
)
from flint_graph.worker.activities.ingestion import (
    mark_ingestion_job_cancelled,
    mark_ingestion_job_completed,
    mark_ingestion_job_failed,
    mark_ingestion_job_running,
    run_ingestion_pipeline,
)
from flint_graph.worker.activities.resolution import (
    enqueue_tenant_resolution,
    resolve_tenant_entities,
)
from flint_graph.workflows.backfill import IndexBackfillWorkflow
from flint_graph.workflows.indexing import IndexDocumentVersionWorkflow
from flint_graph.workflows.ingestion import IngestDocumentWorkflow
from flint_graph.workflows.resolution import ResolveEntitiesWorkflow


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = await connect_temporal(settings)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            IngestDocumentWorkflow,
            IndexDocumentVersionWorkflow,
            IndexBackfillWorkflow,
            ResolveEntitiesWorkflow,
        ],
        activities=[
            mark_ingestion_job_running,
            run_ingestion_pipeline,
            prepare_document_indexing,
            enqueue_document_indexing,
            mark_ingestion_job_completed,
            mark_ingestion_job_failed,
            mark_ingestion_job_cancelled,
            plan_document_indexing_activity,
            index_document_batch,
            mark_document_indexing_completed,
            mark_document_indexing_failed,
            mark_document_indexing_cancelled,
            mark_index_backfill_running,
            load_index_backfill_batch,
            mark_index_backfill_document_completed,
            mark_index_backfill_document_failed,
            complete_index_backfill_activity,
            fail_index_backfill_activity,
            mark_index_backfill_cancelled,
            resolve_tenant_entities,
            enqueue_tenant_resolution,
        ],
    )
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
