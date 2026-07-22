from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class LexicalChunkRecord:
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    chunk_id: str
    chunk_hash: str
    title: str
    text: str
    heading_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    active: bool = True


def opensearch_chunk_document_id(record: LexicalChunkRecord) -> str:
    return f"{record.tenant_id}:{record.document_version_id}:{record.chunk_id}"


def build_opensearch_chunk_document(
    record: LexicalChunkRecord,
    *,
    index_version_id: UUID,
) -> dict[str, Any]:
    return {
        "tenant_id": str(record.tenant_id),
        "document_id": str(record.document_id),
        "document_version_id": str(record.document_version_id),
        "chunk_id": record.chunk_id,
        "chunk_hash": record.chunk_hash,
        "index_version_id": str(index_version_id),
        "title": record.title,
        "text": record.text,
        "heading_path": record.heading_path,
        "page_start": record.page_start,
        "page_end": record.page_end,
        "source_uri": record.source_uri,
        "metadata": record.metadata,
        "active": record.active,
    }


def build_lexical_search_body(
    *,
    tenant_id: UUID,
    query: str,
    limit: int,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    filter_clauses: list[dict[str, Any]] = [{"term": {"tenant_id": str(tenant_id)}}]
    for name, value in (filters or {}).items():
        if name == "page_start_gte":
            filter_clauses.append({"range": {"page_start": {"gte": value}}})
        elif name == "page_end_lte":
            filter_clauses.append({"range": {"page_end": {"lte": value}}})
        elif name in {"document_id", "document_version_id", "chunk_id", "index_version_id"}:
            filter_clauses.append({"term": {name: str(value)}})
        else:
            filter_clauses.append({"term": {f"metadata.{name}": value}})

    return {
        "size": limit,
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["title^2", "text", "heading_path"],
                        }
                    }
                ],
                "filter": filter_clauses,
            }
        },
    }
