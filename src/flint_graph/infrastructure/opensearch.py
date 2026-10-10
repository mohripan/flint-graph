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

    async def ensure_index(self, *, index_name: str, mapping: dict[str, Any]) -> None:
        response = await self._http_client.put(f"/{index_name}", json=mapping)
        if response.status_code == 400 and _is_resource_already_exists(response):
            return
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
        actions = _bulk_actions(body)
        if not actions:
            return
        response = await self._http_client.post(
            "/_bulk",
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
        )
        if not response.is_success:
            raise httpx.HTTPStatusError(
                f"OpenSearch bulk HTTP failure ({response.status_code}).",
                request=response.request,
                response=response,
            )
        _validate_bulk_response(response, actions)

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

    async def check_cluster(self) -> None:
        """Verify the cluster answers. Used by readiness probes."""
        response = await self._http_client.get("/_cluster/health")
        _raise_for_status(response)

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
            _json_line(build_opensearch_chunk_document(record, index_version_id=index_version_id))
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


def _bulk_actions(body: str) -> list[str]:
    """Read action lines, skipping sources even if they contain action-like keys."""
    lines = iter(body.splitlines())
    actions: list[str] = []
    try:
        for line in lines:
            metadata = json.loads(line)
            if not isinstance(metadata, dict) or len(metadata) != 1:
                raise ValueError
            action = next(iter(metadata))
            if action not in {"index", "create", "update", "delete"}:
                raise ValueError
            if not isinstance(metadata[action], dict):
                raise ValueError
            if action != "delete":
                if not isinstance(json.loads(next(lines)), dict):
                    raise ValueError
            actions.append(action)
    except (ValueError, StopIteration):
        raise ValueError("OpenSearch bulk request is malformed.") from None
    return actions


def _validate_bulk_response(response: httpx.Response, actions: list[str]) -> None:
    # Never persist provider reasons, document bodies or identifiers in errors.
    try:
        payload = response.json()
    except ValueError:
        raise ValueError("OpenSearch bulk response is malformed.") from None
    if not isinstance(payload, dict) or type(payload.get("errors")) is not bool:
        raise ValueError("OpenSearch bulk response is malformed.")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != len(actions):
        raise ValueError("OpenSearch bulk response item count mismatch.")
    failures = 0
    for action, item in zip(actions, items, strict=True):
        if not isinstance(item, dict) or set(item) != {action}:
            raise ValueError("OpenSearch bulk response action mismatch.")
        details = item[action]
        if not isinstance(details, dict) or type(details.get("status")) is not int:
            raise ValueError("OpenSearch bulk response item is malformed.")
        status = details["status"]
        success = 200 <= status < 300 or (
            action == "delete" and status == 404 and details.get("result") == "not_found"
        )
        if not success or "error" in details:
            failures += 1
    if failures or payload["errors"]:
        raise ValueError(f"OpenSearch bulk failed ({failures}/{len(actions)} items unsuccessful).")


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    message = (
        f"{response.status_code} {response.reason_phrase} from OpenSearch: {response.text[:500]}"
    )
    raise httpx.HTTPStatusError(message, request=response.request, response=response)


def _is_resource_already_exists(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, dict) and error.get("type") == "resource_already_exists_exception"
