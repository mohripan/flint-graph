import asyncio

import structlog

from atlas_rag.application.services.graph_projection import reconcile_all_tenants
from atlas_rag.config import get_settings
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.infrastructure.neo4j import create_neo4j_client
from atlas_rag.logging import configure_logging

logger = structlog.get_logger(__name__)


async def reconcile() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = create_neo4j_client(settings)
    try:
        async with SessionFactory() as session:
            count = await reconcile_all_tenants(session, client)
        logger.info("graph_reconcile.completed", tenants=count)
        return count
    finally:
        await client.close()


def main() -> None:
    asyncio.run(reconcile())


if __name__ == "__main__":
    main()
