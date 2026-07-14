import json
from uuid import uuid4

import httpx
import pytest

from atlas_rag.application.services.lexical_projection import (
    LexicalChunkRecord,
    build_lexical_search_body,
    build_opensearch_chunk_document,
    opensearch_chunk_document_id,
)
from atlas_rag.infrastructure.opensearch import (
    OpenSearchClient,
    build_chunk_index_mapping,
    build_delete_chunks_bulk_body,
    build_upsert_chunks_bulk_body,
)


def _record(*, text: str = "Acme Corporation is headquartered in Berlin.") -> LexicalChunkRecord:
    tenant_id = uuid4()
    document_id = uuid4()
    document_version_id = uuid4()
    return LexicalChunkRecord(
        tenant_id=tenant_id,
        document_id=document_id,
        document_version_id=document_version_id,
        chunk_id="chunk-000001",
        chunk_hash="sha256:chunk",
        title="Acme Brief",
        text=text,
        heading_path=["Acme Corporation", "Overview"],
        page_start=1,
        page_end=2,
        source_uri="s3://atlas/raw.txt",
        metadata={"source_type": "upload", "external_id": "acme-brief"},
    )


def test_chunk_index_mapping_contains_text_and_filter_fields() -> None:
    mapping = build_chunk_index_mapping()
    properties = mapping["mappings"]["properties"]

    assert properties["text"]["type"] == "text"
    assert properties["title"]["type"] == "text"
    assert properties["heading_path"]["type"] == "text"
    assert properties["tenant_id"]["type"] == "keyword"
    assert properties["document_id"]["type"] == "keyword"
    assert properties["document_version_id"]["type"] == "keyword"
    assert properties["chunk_id"]["type"] == "keyword"
    assert properties["chunk_hash"]["type"] == "keyword"
    assert properties["page_start"]["type"] == "integer"
    assert properties["active"]["type"] == "boolean"


def test_chunk_document_id_and_payload_are_stable_and_filterable() -> None:
    record = _record()

    assert opensearch_chunk_document_id(record) == (
        f"{record.tenant_id}:{record.document_version_id}:chunk-000001"
    )

    payload = build_opensearch_chunk_document(record, index_version_id=uuid4())

    assert payload["tenant_id"] == str(record.tenant_id)
    assert payload["document_id"] == str(record.document_id)
    assert payload["document_version_id"] == str(record.document_version_id)
    assert payload["chunk_id"] == "chunk-000001"
    assert payload["chunk_hash"] == "sha256:chunk"
    assert payload["title"] == "Acme Brief"
    assert payload["text"] == "Acme Corporation is headquartered in Berlin."
    assert payload["heading_path"] == ["Acme Corporation", "Overview"]
    assert payload["page_start"] == 1
    assert payload["page_end"] == 2
    assert payload["active"] is True
    assert payload["metadata"] == {"source_type": "upload", "external_id": "acme-brief"}


def test_bulk_upsert_and_delete_payloads_use_stable_document_ids() -> None:
    record = _record()
    index_version_id = uuid4()

    upsert_body = build_upsert_chunks_bulk_body(
        index_name="atlas_chunks_v000001",
        records=[record],
        index_version_id=index_version_id,
    )
    upsert_lines = [json.loads(line) for line in upsert_body.strip().splitlines()]

    assert upsert_lines[0] == {
        "index": {
            "_index": "atlas_chunks_v000001",
            "_id": opensearch_chunk_document_id(record),
        }
    }
    assert upsert_lines[1]["index_version_id"] == str(index_version_id)
    assert upsert_lines[1]["text"] == record.text

    delete_body = build_delete_chunks_bulk_body(
        index_name="atlas_chunks_v000001",
        records=[record],
    )
    delete_lines = [json.loads(line) for line in delete_body.strip().splitlines()]
    assert delete_lines == [
        {
            "delete": {
                "_index": "atlas_chunks_v000001",
                "_id": opensearch_chunk_document_id(record),
            }
        }
    ]


def test_lexical_search_body_always_includes_tenant_and_metadata_filters() -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    body = build_lexical_search_body(
        tenant_id=tenant_id,
        query="Berlin office",
        limit=5,
        filters={
            "document_id": str(document_id),
            "page_start_gte": 2,
            "source_type": "upload",
        },
    )

    bool_query = body["query"]["bool"]
    assert body["size"] == 5
    assert {
        "multi_match": {
            "query": "Berlin office",
            "fields": ["title^2", "text", "heading_path"],
        }
    } in bool_query["must"]
    assert {"term": {"tenant_id": str(tenant_id)}} in bool_query["filter"]
    assert {"term": {"document_id": str(document_id)}} in bool_query["filter"]
    assert {"range": {"page_start": {"gte": 2}}} in bool_query["filter"]
    assert {"term": {"metadata.source_type": "upload"}} in bool_query["filter"]


@pytest.mark.anyio
async def test_opensearch_client_sends_mapping_alias_bulk_and_search_requests() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/_search"):
            return httpx.Response(
                200,
                json={
                    "hits": {
                        "hits": [
                            {
                                "_id": "doc-1",
                                "_score": 1.7,
                                "_source": {"chunk_id": "chunk-000001"},
                            }
                        ]
                    }
                },
                request=request,
            )
        return httpx.Response(200, json={"acknowledged": True}, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://opensearch") as http_client:
        client = OpenSearchClient(http_client=http_client, base_url="http://opensearch")
        await client.create_index(index_name="atlas_chunks_v000001", mapping={"settings": {}})
        await client.point_alias(
            alias_name="atlas_chunks_active",
            index_name="atlas_chunks_v000001",
            previous_index_names=["atlas_chunks_v000000"],
        )
        await client.bulk(body='{"index":{}}\n{"field":"value"}\n')
        result = await client.search(
            index_name="atlas_chunks_active",
            body={"query": {"match_all": {}}},
        )

    assert [request.method for request in requests] == ["PUT", "POST", "POST", "POST"]
    assert [request.url.path for request in requests] == [
        "/atlas_chunks_v000001",
        "/_aliases",
        "/_bulk",
        "/atlas_chunks_active/_search",
    ]
    bulk_request = requests[2]
    assert bulk_request.headers["content-type"] == "application/x-ndjson"
    assert result == [{"id": "doc-1", "score": 1.7, "source": {"chunk_id": "chunk-000001"}}]


@pytest.mark.anyio
async def test_opensearch_client_includes_error_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="cluster unavailable", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://opensearch") as http_client:
        client = OpenSearchClient(http_client=http_client, base_url="http://opensearch")

        with pytest.raises(httpx.HTTPStatusError, match="cluster unavailable"):
            await client.create_index(index_name="atlas_chunks_v000001", mapping={})
