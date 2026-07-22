from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx

from flint_graph.application.services.lexical_projection import (
    LexicalChunkRecord,
    build_opensearch_chunk_document,
    opensearch_chunk_document_id,
)
from flint_graph.config import Settings


class OpenSearchClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "http://localhost:9200",
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        auth = (username, password) if username is not None and password is not None else None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=base_url,
            auth=auth,
            timeout=timeout_seconds,
        )

    async def create_index(self, *, index_name: str, mapping: dict[str, Any]) -> None:
        response = await self._http_client.put(f"/{index_name}", json=mapping)
        _raise_for_status(response)

    async def point_alias(
        self,
        *,
        alias_name: str,
        index_name: str,
        previous_index_names: list[str] | None = None,
    ) -> None:
        actions: list[dict[str, Any]] = [
            {"remove": {"index": previous_index, "alias": alias_name}}
            for previous_index in previous_index_names or []
        ]
        actions.append({"add": {"index": index_name, "alias": alias_name}})
        response = await self._http_client.post("/_aliases", json={"actions": actions})
        _raise_for_status(response)

    async def bulk(self, *, body: str) -> None:
        response = await self._http_client.post(
            "/_bulk",
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
        )
        _raise_for_status(response)

    async def search(self, *, index_name: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        response = await self._http_client.post(f"/{index_name}/_search", json=body)
        _raise_for_status(response)
        hits = response.json().get("hits", {}).get("hits", [])
        if not isinstance(hits, list):
            raise ValueError("OpenSearch response did not include a list of hits.")
        return [
            {
                "id": hit.get("_id"),
                "score": hit.get("_score"),
                "source": hit.get("_source"),
            }
            for hit in hits
            if isinstance(hit, dict)
        ]

    async def close(self) -> None:
        await self._http_client.aclose()


def create_opensearch_client(settings: Settings) -> OpenSearchClient:
    return OpenSearchClient(
        base_url=settings.opensearch_url,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        timeout_seconds=settings.opensearch_timeout_seconds,
    )


def build_chunk_index_mapping() -> dict[str, Any]:
    return {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
            }
        },
        "mappings": {
            "dynamic": "false",
            "properties": {
                "tenant_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "document_version_id": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "chunk_hash": {"type": "keyword"},
                "index_version_id": {"type": "keyword"},
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "text": {"type": "text"},
                "heading_path": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "page_start": {"type": "integer"},
                "page_end": {"type": "integer"},
                "source_uri": {"type": "keyword"},
                "metadata": {"type": "object", "dynamic": True},
                "active": {"type": "boolean"},
            },
        },
    }


def build_upsert_chunks_bulk_body(
    *,
    index_name: str,
    records: list[LexicalChunkRecord],
    index_version_id: UUID,
) -> str:
    lines: list[str] = []
    for record in records:
        lines.append(
            _json_line(
                {
                    "index": {
                        "_index": index_name,
                        "_id": opensearch_chunk_document_id(record),
                    }
                }
            )
        )
        lines.append(
            _json_line(
                build_opensearch_chunk_document(record, index_version_id=index_version_id)
            )
        )
    return "\n".join(lines) + ("\n" if lines else "")


def build_delete_chunks_bulk_body(
    *,
    index_name: str,
    records: list[LexicalChunkRecord],
) -> str:
    lines = [
        _json_line(
            {
                "delete": {
                    "_index": index_name,
                    "_id": opensearch_chunk_document_id(record),
                }
            }
        )
        for record in records
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    message = (
        f"{response.status_code} {response.reason_phrase} from OpenSearch: "
        f"{response.text[:500]}"
    )
    raise httpx.HTTPStatusError(message, request=response.request, response=response)
