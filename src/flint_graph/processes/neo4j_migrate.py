import asyncio
from pathlib import Path

import structlog

from flint_graph.config import get_settings
from flint_graph.infrastructure.neo4j import create_neo4j_client
from flint_graph.infrastructure.neo4j_migrations import apply_migrations, load_migrations
from flint_graph.logging import configure_logging

logger = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path("migrations/neo4j")


async def run_migrations() -> list[str]:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = create_neo4j_client(settings)
    try:
        migrations = load_migrations(MIGRATIONS_DIR)
        applied = await apply_migrations(client, migrations)
        if applied:
            logger.info("neo4j_migrate.applied", versions=applied)
        else:
            logger.info("neo4j_migrate.up_to_date")
        return applied
    finally:
        await client.close()


def main() -> None:
    asyncio.run(run_migrations())


if __name__ == "__main__":
    main()
