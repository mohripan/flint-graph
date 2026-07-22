from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, Field

from flint_graph.application.parsing import NormalizedDocument, NormalizedElement, SourceOffsets


class ChunkingConfig(BaseModel):
    max_chunk_chars: int = Field(default=1200, ge=1)
    overlap_chars: int = Field(default=120, ge=0)


class DocumentChunkManifestEntry(BaseModel):
    chunk_id: str
    chunk_index: int
    text: str
    chunk_hash: str
    source_element_ids: list[str]
    heading_path: list[str]
    page_start: int | None = None
    page_end: int | None = None
    source_offsets: dict[str, int] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunkManifest(BaseModel):
    schema_version: Literal["1"] = "1"
    source: dict[str, str]
    chunking_config: dict[str, int]
    chunks: list[DocumentChunkManifestEntry]


def chunk_normalized_document(
    document: NormalizedDocument,
    *,
    config: ChunkingConfig,
) -> DocumentChunkManifest:
    chunks: list[DocumentChunkManifestEntry] = []
    heading_stack: list[tuple[int, str]] = []
    pending = _PendingChunk(max_chars=config.max_chunk_chars)

    def emit_pending() -> None:
        if pending.texts:
            chunks.append(pending.to_manifest_entry(len(chunks)))
            pending.clear()

    for element in document.elements:
        if element.type == "heading":
            emit_pending()
            level = element.level or 1
            heading_stack = [item for item in heading_stack if item[0] < level]
            heading_stack.append((level, element.text))
            continue

        heading_path = [heading for _level, heading in heading_stack]
        parts = _split_element_if_needed(element, config=config)
        for part in parts:
            if pending.can_accept(part):
                pending.add(part, heading_path=heading_path)
            else:
                emit_pending()
                pending.add(part, heading_path=heading_path)
    emit_pending()

    return DocumentChunkManifest(
        source={
            "document_id": str(document.source.document_id),
            "document_version_id": str(document.source.document_version_id),
            "content_hash": document.source.content_hash,
        },
        chunking_config=config.model_dump(),
        chunks=chunks,
    )


class _ChunkPart(BaseModel):
    text: str
    source_element_id: str
    page: int | None = None
    source_offsets: SourceOffsets | None = None


class _PendingChunk:
    def __init__(self, *, max_chars: int) -> None:
        self._max_chars = max_chars
        self.texts: list[str] = []
        self.source_element_ids: list[str] = []
        self.heading_path: list[str] = []
        self.pages: list[int] = []
        self.offset_starts: list[int] = []
        self.offset_ends: list[int] = []

    def can_accept(self, part: _ChunkPart) -> bool:
        if not self.texts:
            return True
        candidate = "\n\n".join([*self.texts, part.text])
        return len(candidate) <= self._max_chars

    def add(self, part: _ChunkPart, *, heading_path: list[str]) -> None:
        if not self.texts:
            self.heading_path = heading_path
        self.texts.append(part.text)
        if part.source_element_id not in self.source_element_ids:
            self.source_element_ids.append(part.source_element_id)
        if part.page is not None:
            self.pages.append(part.page)
        if part.source_offsets is not None:
            self.offset_starts.append(part.source_offsets.start)
            self.offset_ends.append(part.source_offsets.end)

    def to_manifest_entry(self, index: int) -> DocumentChunkManifestEntry:
        text = "\n\n".join(self.texts)
        chunk_id = f"chunk-{index + 1:06d}"
        source_offsets = None
        if self.offset_starts and self.offset_ends:
            source_offsets = {"start": min(self.offset_starts), "end": max(self.offset_ends)}
        return DocumentChunkManifestEntry(
            chunk_id=chunk_id,
            chunk_index=index,
            text=text,
            chunk_hash=_content_hash(text),
            source_element_ids=list(self.source_element_ids),
            heading_path=list(self.heading_path),
            page_start=min(self.pages) if self.pages else None,
            page_end=max(self.pages) if self.pages else None,
            source_offsets=source_offsets,
        )

    def clear(self) -> None:
        self.texts = []
        self.source_element_ids = []
        self.heading_path = []
        self.pages = []
        self.offset_starts = []
        self.offset_ends = []


def _split_element_if_needed(
    element: NormalizedElement,
    *,
    config: ChunkingConfig,
) -> list[_ChunkPart]:
    if len(element.text) <= config.max_chunk_chars:
        return [
            _ChunkPart(
                text=element.text,
                source_element_id=element.id,
                page=element.page,
                source_offsets=element.source_offsets,
            )
        ]

    parts: list[_ChunkPart] = []
    step = config.max_chunk_chars - config.overlap_chars
    if step <= 0:
        step = config.max_chunk_chars
    start = 0
    while start < len(element.text):
        end = min(start + config.max_chunk_chars, len(element.text))
        offset = None
        if element.source_offsets is not None:
            offset = SourceOffsets(
                start=element.source_offsets.start + start,
                end=element.source_offsets.start + end,
            )
        parts.append(
            _ChunkPart(
                text=element.text[start:end],
                source_element_id=element.id,
                page=element.page,
                source_offsets=offset,
            )
        )
        if end == len(element.text):
            break
        start += step
    return parts


def _content_hash(text: str) -> str:
    return "sha256:" + sha256(text.encode("utf-8")).hexdigest()
