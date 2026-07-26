import asyncio

import structlog

from flint_graph.application.services.graph_projection import reconcile_all_tenants
from flint_graph.config import get_settings
from flint_graph.infrastructure.db.session import SessionFactory
from flint_graph.infrastructure.neo4j import create_neo4j_client
from flint_graph.observability.runtime import GRAPH_RECONCILE_ROLE, configure_observability

logger = structlog.get_logger(__name__)


async def reconcile() -> int:
    settings = get_settings()
    configure_observability(settings, role=GRAPH_RECONCILE_ROLE)
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
