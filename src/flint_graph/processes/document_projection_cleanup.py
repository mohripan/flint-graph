import asyncio

import structlog

from flint_graph.application.services.document_lifecycle import run_next_projection_cleanup
from flint_graph.config import get_settings
from flint_graph.domain.enums import DocumentProjectionCleanupStatus
from flint_graph.infrastructure.db.models import DocumentProjectionCleanup
from flint_graph.infrastructure.db.session import SessionFactory
from flint_graph.infrastructure.neo4j import create_neo4j_client
from flint_graph.infrastructure.opensearch import create_opensearch_client
from flint_graph.observability.runtime import PROJECTION_CLEANUP_ROLE, configure_observability


def log_cleanup_outcome(cleanup: DocumentProjectionCleanup) -> None:
    logger = structlog.get_logger(__name__)
    fields = {
        "cleanup_id": str(cleanup.id),
        "status": cleanup.status.value,
        "attempt_count": cleanup.attempt_count,
    }
    if cleanup.status == DocumentProjectionCleanupStatus.COMPLETED:
        logger.info("document_projection_cleanup.completed", **fields)
    elif cleanup.status == DocumentProjectionCleanupStatus.FAILED:
        logger.warning(
            "document_projection_cleanup.failed", error_code="projection_cleanup_failed", **fields
        )
    else:
        logger.warning(
            "document_projection_cleanup.incomplete", error_code="cleanup_incomplete", **fields
        )


def log_cleanup_iteration_failure() -> None:
    logger = structlog.get_logger(__name__)
    # Unexpected exceptions can contain URLs, credentials or provider payloads.
    logger.warning(
        "document_projection_cleanup.iteration_failed", error_code="cleanup_iteration_failed"
    )


async def cleanup_once() -> int:
    settings = get_settings()
    neo4j_client = create_neo4j_client(settings)
    opensearch_client = create_opensearch_client(settings)
    try:
        async with SessionFactory() as session:
            try:
                cleanup = await run_next_projection_cleanup(
                    session,
                    neo4j_client=neo4j_client,
                    opensearch_client=opensearch_client,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        if cleanup is None:
            return 0
        log_cleanup_outcome(cleanup)
        return 1
    finally:
        await neo4j_client.close()
        await opensearch_client.close()


async def run_forever() -> None:
    settings = get_settings()
    configure_observability(settings, role=PROJECTION_CLEANUP_ROLE)
    while True:
        try:
            processed = await cleanup_once()
            if processed:
                continue
        except Exception:
            log_cleanup_iteration_failure()
        await asyncio.sleep(settings.projection_cleanup_poll_interval_seconds)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
