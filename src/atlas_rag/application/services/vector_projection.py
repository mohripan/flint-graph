from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

CREATE_VECTOR_INDEX_TEMPLATE = (
    "CREATE VECTOR INDEX {index_name} IF NOT EXISTS\n"
    "FOR (c:{label}) ON (c.{property_name})\n"
    "OPTIONS {{indexConfig: {{`vector.dimensions`: {dimensions}, "
    "`vector.similarity_function`: '{similarity_function}'}}}}"
)

UPSERT_CHUNK_VECTORS = """
UNWIND $rows AS row
MERGE (c:Chunk {id: row.id})
SET c.tenant_id = row.tenant_id,
    c.document_id = row.document_id,
    c.document_version_id = row.document_version_id,
    c.chunk_id = row.chunk_id,
    c.chunk_hash = row.chunk_hash,
    c.retrieval_index_version_id = row.retrieval_index_version_id,
    c.text_preview = row.text_preview,
    c.metadata_json = row.metadata_json,
    c[$vector_property_name] = row.vector
"""

DELETE_CHUNK_VECTORS = """
MATCH (c:Chunk {tenant_id: $tenant_id, retrieval_index_version_id: $retrieval_index_version_id})
WHERE c.id IN $ids
DETACH DELETE c
"""

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SIMILARITY_FUNCTIONS = {"cosine", "euclidean"}


class SupportsCypher(Protocol):
    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class VectorChunkRecord:
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    chunk_id: str
    chunk_hash: str
    retrieval_index_version_id: UUID
    vector: list[float]
    text_preview: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def vector_chunk_node_id(record: VectorChunkRecord) -> str:
    return (
        f"{record.tenant_id}:{record.retrieval_index_version_id}:"
        f"{record.document_version_id}:{record.chunk_id}"
    )


def build_create_vector_index_cypher(
    *,
    index_name: str,
    label: str,
    property_name: str,
    dimensions: int,
    similarity_function: str = "cosine",
) -> str:
    _validate_identifier(index_name)
    _validate_identifier(label)
    _validate_identifier(property_name)
    if dimensions <= 0:
        raise ValueError("dimensions must be greater than zero.")
    if similarity_function not in _SIMILARITY_FUNCTIONS:
        raise ValueError("similarity_function must be one of: cosine, euclidean.")
    return CREATE_VECTOR_INDEX_TEMPLATE.format(
        index_name=index_name,
        label=label,
        property_name=property_name,
        dimensions=dimensions,
        similarity_function=similarity_function,
    )


async def project_chunk_vectors(
    client: SupportsCypher,
    *,
    records: list[VectorChunkRecord],
    vector_property_name: str,
) -> None:
    _validate_identifier(vector_property_name)
    rows = [
        {
            "id": vector_chunk_node_id(record),
            "tenant_id": str(record.tenant_id),
            "document_id": str(record.document_id),
            "document_version_id": str(record.document_version_id),
            "chunk_id": record.chunk_id,
            "chunk_hash": record.chunk_hash,
            "retrieval_index_version_id": str(record.retrieval_index_version_id),
            "vector": record.vector,
            "text_preview": record.text_preview,
            "metadata_json": json.dumps(
                record.metadata,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for record in records
    ]
    await client.execute(
        UPSERT_CHUNK_VECTORS,
        {"rows": rows, "vector_property_name": vector_property_name},
    )


async def delete_chunk_vectors(
    client: SupportsCypher,
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
    chunk_node_ids: list[str],
) -> None:
    await client.execute(
        DELETE_CHUNK_VECTORS,
        {
            "tenant_id": str(tenant_id),
            "retrieval_index_version_id": str(retrieval_index_version_id),
            "ids": chunk_node_ids,
        },
    )


def _validate_identifier(value: str) -> None:
    if _IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"unsafe Neo4j identifier: {value}")
