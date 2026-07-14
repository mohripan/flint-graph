import asyncio

import structlog

from atlas_rag.application.services.indexing import reconcile_completed_index_projections
from atlas_rag.config import get_settings
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.infrastructure.neo4j import create_neo4j_client
from atlas_rag.infrastructure.opensearch import create_opensearch_client
from atlas_rag.logging import configure_logging

logger = structlog.get_logger(__name__)


async def reconcile() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    neo4j_client = create_neo4j_client(settings)
    opensearch_client = create_opensearch_client(settings)
    try:
        async with SessionFactory() as session:
            count = await reconcile_completed_index_projections(
                session,
                neo4j_client=neo4j_client,
                opensearch_client=opensearch_client,
            )
        logger.info("retrieval_index_reconcile.completed", document_versions=count)
        return count
    finally:
        await neo4j_client.close()
        await opensearch_client.close()


def main() -> None:
    asyncio.run(reconcile())


if __name__ == "__main__":
    main()
