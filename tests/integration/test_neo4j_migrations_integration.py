import os
from pathlib import Path

import pytest

from atlas_rag.config import Settings
from atlas_rag.infrastructure.neo4j import create_neo4j_client
from atlas_rag.infrastructure.neo4j_migrations import apply_migrations, load_migrations

pytestmark = pytest.mark.skipif(
    not os.getenv("ATLAS_NEO4J_INTEGRATION"),
    reason="Set ATLAS_NEO4J_INTEGRATION=1 with a running Neo4j to run this test.",
)

REPO_MIGRATIONS_DIR = Path("migrations/neo4j")


async def test_apply_migrations_against_real_neo4j() -> None:
    client = create_neo4j_client(Settings())
    try:
        migrations = load_migrations(REPO_MIGRATIONS_DIR)

        first = await apply_migrations(client, migrations)
        second = await apply_migrations(client, migrations)

        assert "0001_entity_constraints" in first
        assert second == []

        constraints = await client.execute("SHOW CONSTRAINTS YIELD name RETURN name")
        names = {row["name"] for row in constraints}
        assert "entity_id_unique" in names
    finally:
        await client.close()
