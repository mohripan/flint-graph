from collections.abc import Mapping
from pathlib import Path
from typing import Any

from atlas_rag.infrastructure.neo4j_migrations import (
    APPLIED_VERSIONS_QUERY,
    ENSURE_MIGRATION_CONSTRAINT,
    RECORD_MIGRATION_QUERY,
    Neo4jMigration,
    apply_migrations,
    load_migrations,
    split_statements,
)

REPO_MIGRATIONS_DIR = Path("migrations/neo4j")


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self._applied: list[str] = []

    async def execute(
        self, query: str, parameters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        params = dict(parameters or {})
        self.executed.append((query, params))
        if query == APPLIED_VERSIONS_QUERY:
            return [{"version": version} for version in self._applied]
        if query == RECORD_MIGRATION_QUERY:
            version = str(params["version"])
            if version not in self._applied:
                self._applied.append(version)
        return []


def test_split_statements_drops_comments_and_blank_lines() -> None:
    text = (
        "// a comment\n"
        "CREATE CONSTRAINT a IF NOT EXISTS\nFOR (e:Entity) REQUIRE e.id IS UNIQUE;\n"
        "\n"
        "// another comment\n"
        "CREATE INDEX b IF NOT EXISTS FOR (e:Entity) ON (e.tenant_id);\n"
    )

    statements = split_statements(text)

    assert statements == [
        "CREATE CONSTRAINT a IF NOT EXISTS\nFOR (e:Entity) REQUIRE e.id IS UNIQUE",
        "CREATE INDEX b IF NOT EXISTS FOR (e:Entity) ON (e.tenant_id)",
    ]


def test_split_statements_ignores_semicolons_inside_comments() -> None:
    text = "// a comment; with a semicolon inside it\nRETURN 1;\n"

    assert split_statements(text) == ["RETURN 1"]


def test_split_statements_ignores_trailing_separator() -> None:
    assert split_statements("RETURN 1;\n") == ["RETURN 1"]
    assert split_statements("") == []
    assert split_statements("// only a comment\n") == []


def test_load_migrations_orders_by_filename(tmp_path: Path) -> None:
    (tmp_path / "0002_second.cypher").write_text("RETURN 2;", encoding="utf-8")
    (tmp_path / "0001_first.cypher").write_text("RETURN 1;", encoding="utf-8")

    migrations = load_migrations(tmp_path)

    assert [migration.version for migration in migrations] == ["0001_first", "0002_second"]
    assert migrations[0].statements == ("RETURN 1",)


def test_repo_migration_defines_entity_constraint() -> None:
    migrations = load_migrations(REPO_MIGRATIONS_DIR)

    versions = {migration.version for migration in migrations}
    assert "0001_entity_constraints" in versions
    assert "0002_chunk_vector_indexes" in versions

    initial = next(m for m in migrations if m.version == "0001_entity_constraints")
    joined = "\n".join(initial.statements)
    assert "entity_id_unique" in joined
    assert "entity_tenant_type_name" in joined

    vector = next(m for m in migrations if m.version == "0002_chunk_vector_indexes")
    vector_joined = "\n".join(vector.statements)
    assert "chunk_id_unique" in vector_joined
    assert "chunk_tenant_index_version" in vector_joined
    assert "chunk_embedding_default" in vector_joined
    assert "vector.dimensions`: 384" in vector_joined


async def test_apply_migrations_runs_statements_and_records_versions() -> None:
    client = FakeNeo4jClient()
    migrations = [
        Neo4jMigration(version="0001_first", statements=("CREATE CONSTRAINT a", "CREATE INDEX b")),
    ]

    applied = await apply_migrations(client, migrations)

    assert applied == ["0001_first"]
    queries = [query for query, _ in client.executed]
    assert queries[0] == ENSURE_MIGRATION_CONSTRAINT
    assert "CREATE CONSTRAINT a" in queries
    assert "CREATE INDEX b" in queries
    assert (RECORD_MIGRATION_QUERY, {"version": "0001_first"}) in client.executed


async def test_apply_migrations_is_idempotent() -> None:
    client = FakeNeo4jClient()
    migrations = [Neo4jMigration(version="0001_first", statements=("CREATE CONSTRAINT a",))]

    first = await apply_migrations(client, migrations)
    second = await apply_migrations(client, migrations)

    assert first == ["0001_first"]
    assert second == []
    assert [query for query, _ in client.executed].count("CREATE CONSTRAINT a") == 1
