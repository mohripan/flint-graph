from typing import Any
from uuid import UUID, uuid4

import pytest

from flint_graph.application.services.vector_projection import (
    CREATE_VECTOR_INDEX_TEMPLATE,
    DELETE_CHUNK_VECTORS,
    UPSERT_CHUNK_VECTORS,
    VectorChunkRecord,
    build_create_vector_index_cypher,
    delete_chunk_vectors,
    project_chunk_vectors,
    vector_chunk_node_id,
)

TENANT = UUID("11111111-1111-4111-8111-111111111111")


class FakeCypherClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((query, parameters or {}))
        return []


def _record() -> VectorChunkRecord:
    document_id = uuid4()
    document_version_id = uuid4()
    index_version_id = uuid4()
    return VectorChunkRecord(
        tenant_id=TENANT,
        document_id=document_id,
        document_version_id=document_version_id,
        chunk_id="chunk-000001",
        chunk_hash="sha256:chunk",
        retrieval_index_version_id=index_version_id,
        vector=[0.1, 0.2, 0.3],
        text_preview="Acme Corporation is headquartered in Berlin.",
        metadata={"source_type": "upload"},
    )


def test_vector_chunk_node_id_is_stable_by_tenant_version_chunk_and_index() -> None:
    record = _record()

    assert vector_chunk_node_id(record) == (
        f"{record.tenant_id}:{record.retrieval_index_version_id}:"
        f"{record.document_version_id}:chunk-000001"
    )


def test_build_create_vector_index_cypher_validates_identifiers_and_options() -> None:
    query = build_create_vector_index_cypher(
        index_name="chunk_embedding_v000001",
        label="Chunk",
        property_name="embedding_v000001",
        dimensions=384,
    )

    assert query == CREATE_VECTOR_INDEX_TEMPLATE.format(
        index_name="chunk_embedding_v000001",
        label="Chunk",
        property_name="embedding_v000001",
        dimensions=384,
        similarity_function="cosine",
    )

    with pytest.raises(ValueError, match="unsafe Neo4j identifier"):
        build_create_vector_index_cypher(
            index_name="chunk embedding",
            label="Chunk",
            property_name="embedding",
            dimensions=384,
        )

    with pytest.raises(ValueError, match="dimensions"):
        build_create_vector_index_cypher(
            index_name="chunk_embedding",
            label="Chunk",
            property_name="embedding",
            dimensions=0,
        )


async def test_project_chunk_vectors_upserts_rows_with_configured_vector_property() -> None:
    client = FakeCypherClient()
    record = _record()

    await project_chunk_vectors(
        client,
        records=[record],
        vector_property_name="embedding_v000001",
    )

    assert client.calls == [
        (
            UPSERT_CHUNK_VECTORS,
            {
                "rows": [
                    {
                        "id": vector_chunk_node_id(record),
                        "tenant_id": str(record.tenant_id),
                        "document_id": str(record.document_id),
                        "document_version_id": str(record.document_version_id),
                        "chunk_id": record.chunk_id,
                        "chunk_hash": record.chunk_hash,
                        "retrieval_index_version_id": str(record.retrieval_index_version_id),
                        "vector": [0.1, 0.2, 0.3],
                        "text_preview": record.text_preview,
                        "metadata_json": '{"source_type":"upload"}',
                    }
                ],
                "vector_property_name": "embedding_v000001",
            },
        )
    ]


async def test_delete_chunk_vectors_deletes_by_tenant_index_version_and_ids() -> None:
    client = FakeCypherClient()
    index_version_id = uuid4()

    await delete_chunk_vectors(
        client,
        tenant_id=TENANT,
        retrieval_index_version_id=index_version_id,
        chunk_node_ids=["chunk-node-1", "chunk-node-2"],
    )

    assert client.calls == [
        (
            DELETE_CHUNK_VECTORS,
            {
                "tenant_id": str(TENANT),
                "retrieval_index_version_id": str(index_version_id),
                "ids": ["chunk-node-1", "chunk-node-2"],
            },
        )
    ]
