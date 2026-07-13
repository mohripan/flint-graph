from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import Any

from atlas_rag.config import Settings


class Neo4jClient:
    """Thin async wrapper over the Neo4j driver.

    Runs one Cypher statement per call and returns the records as dicts. Keeping
    the surface this small makes the migration runner and future projection code
    easy to fake in unit tests.
    """

    def __init__(self, driver: Any, *, database: str) -> None:
        self._driver = driver
        self._database = database

    async def execute(
        self,
        query: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        async with self._driver.session(database=self._database) as session:
            result = await session.run(query, dict(parameters or {}))
            return [record.data() async for record in result]

    async def close(self) -> None:
        await self._driver.close()


def create_neo4j_driver(settings: Settings) -> Any:
    neo4j: Any = import_module("neo4j")
    return neo4j.AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        max_connection_pool_size=settings.neo4j_max_connection_pool_size,
        connection_timeout=settings.neo4j_connection_timeout_seconds,
    )


def create_neo4j_client(settings: Settings) -> Neo4jClient:
    return Neo4jClient(create_neo4j_driver(settings), database=settings.neo4j_database)
