import asyncio

from temporalio.worker import Worker

from atlas_rag.config import get_settings
from atlas_rag.infrastructure.temporal import connect_temporal
from atlas_rag.logging import configure_logging
from atlas_rag.worker.activities.ingestion import (
    mark_ingestion_job_cancelled,
    mark_ingestion_job_completed,
    mark_ingestion_job_failed,
    mark_ingestion_job_running,
    run_stub_ingestion,
)
from atlas_rag.workflows.ingestion import IngestDocumentWorkflow


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = await connect_temporal(settings)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[IngestDocumentWorkflow],
        activities=[
            mark_ingestion_job_running,
            run_stub_ingestion,
            mark_ingestion_job_completed,
            mark_ingestion_job_failed,
            mark_ingestion_job_cancelled,
        ],
    )
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
