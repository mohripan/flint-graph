import asyncio

import structlog

from atlas_rag.application.services.document_lifecycle import run_next_projection_cleanup
from atlas_rag.config import get_settings
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.infrastructure.neo4j import create_neo4j_client
from atlas_rag.infrastructure.opensearch import create_opensearch_client
from atlas_rag.logging import configure_logging

logger = structlog.get_logger(__name__)


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
        logger.info("document_projection_cleanup.completed", cleanup_id=str(cleanup.id))
        return 1
    finally:
        await neo4j_client.close()
        await opensearch_client.close()


async def run_forever() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        try:
            cleaned = await cleanup_once()
            if cleaned:
                continue
        except Exception as exc:
            logger.warning("document_projection_cleanup.failed", error=str(exc))
        await asyncio.sleep(settings.projection_cleanup_poll_interval_seconds)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
