from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ENSURE_MIGRATION_CONSTRAINT = (
    "CREATE CONSTRAINT schema_migration_version_unique IF NOT EXISTS "
    "FOR (m:_SchemaMigration) REQUIRE m.version IS UNIQUE"
)
APPLIED_VERSIONS_QUERY = "MATCH (m:_SchemaMigration) RETURN m.version AS version"
RECORD_MIGRATION_QUERY = (
    "MERGE (m:_SchemaMigration {version: $version}) ON CREATE SET m.applied_at = datetime()"
)


class SupportsCypher(Protocol):
    async def execute(
        self, query: str, parameters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class Neo4jMigration:
    version: str
    statements: tuple[str, ...]


def split_statements(text: str) -> list[str]:
    """Split a Cypher file into individual statements.

    The Neo4j driver runs a single statement per call, so schema files are split
    on `;`. Blank lines and full-line `//` comments are dropped.
    """

    lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    body = "\n".join(lines)
    statements: list[str] = []
    for block in body.split(";"):
        statement = block.strip()
        if statement:
            statements.append(statement)
    return statements


def load_migrations(directory: Path) -> list[Neo4jMigration]:
    """Load ordered `*.cypher` migrations from a directory.

    The file stem (e.g. `0001_entity_constraints`) is the version; files are
    applied in lexicographic order.
    """

    migrations: list[Neo4jMigration] = []
    for path in sorted(directory.glob("*.cypher")):
        statements = split_statements(path.read_text(encoding="utf-8"))
        migrations.append(Neo4jMigration(version=path.stem, statements=tuple(statements)))
    return migrations


async def apply_migrations(
    client: SupportsCypher, migrations: Sequence[Neo4jMigration]
) -> list[str]:
    """Apply pending migrations and return the versions newly applied.

    Idempotent: applied versions are tracked as `(:_SchemaMigration)` nodes, so a
    re-run over the same migrations is a no-op and returns an empty list.
    """

    await client.execute(ENSURE_MIGRATION_CONSTRAINT)
    records = await client.execute(APPLIED_VERSIONS_QUERY)
    applied = {record["version"] for record in records}

    newly_applied: list[str] = []
    for migration in migrations:
        if migration.version in applied:
            continue
        for statement in migration.statements:
            await client.execute(statement)
        await client.execute(RECORD_MIGRATION_QUERY, {"version": migration.version})
        newly_applied.append(migration.version)
    return newly_applied
