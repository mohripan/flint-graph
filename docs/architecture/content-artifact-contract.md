# Content Artifact Contract

## Purpose

AtlasRAG parser output is an Atlas-owned normalized artifact. It is not a LangChain loader object, a PDF library object, or an HTML parser object. Chunking consumes this contract directly, and extraction consumes chunk manifests rather than parser-specific objects.

## Supported Source Formats

Phase 4 supports:

- Plain text.
- Markdown.
- HTML.
- Text-based PDF.

Scanned PDF OCR is out of scope. A PDF with no extractable text is a controlled parser failure.

## Normalized Document

Normalized artifacts use schema version `1`:

```json
{
  "schema_version": "1",
  "source": {
    "document_id": "11111111-1111-4111-8111-111111111111",
    "document_version_id": "22222222-2222-4222-8222-222222222222",
    "content_hash": "sha256:..."
  },
  "format": "markdown",
  "title": "Example",
  "elements": [
    {
      "id": "element-000001",
      "type": "heading",
      "text": "Example",
      "level": 1,
      "source_offsets": {"start": 0, "end": 9}
    }
  ],
  "warnings": []
}
```

## Element Types

Phase 4 element types:

- `heading`
- `paragraph`
- `list_item`
- `code_block`

Element IDs are deterministic within an artifact and use `element-000001` style numbering. Element text must be non-empty.

Headings include `level` from 1 through 6. PDF elements may include a 1-based `page`. Text and Markdown elements include source offsets where the parser can produce them deterministically.

## Format Detection

Format detection uses:

- PDF magic bytes.
- Content type.
- Filename extension.
- HTML leading markup.
- UTF-8 text fallback.

Unknown binary content is rejected with a controlled parser error.

## Chunk Manifest

Chunk manifests use schema version `1` and are derived from normalized artifacts:

```json
{
  "schema_version": "1",
  "source": {
    "document_id": "11111111-1111-4111-8111-111111111111",
    "document_version_id": "22222222-2222-4222-8222-222222222222",
    "content_hash": "sha256:..."
  },
  "chunking_config": {
    "max_chunk_chars": 1200,
    "overlap_chars": 120
  },
  "chunks": [
    {
      "chunk_id": "chunk-000001",
      "chunk_index": 0,
      "text": "Chunk text",
      "chunk_hash": "sha256:...",
      "source_element_ids": ["element-000002"],
      "heading_path": ["Example"],
      "page_start": 1,
      "page_end": 1,
      "source_offsets": {"start": 10, "end": 42},
      "metadata": {}
    }
  ]
}
```

Chunking is deterministic for the same normalized artifact and chunking config. Heading elements update the current heading path; they do not become standalone chunks. Paragraph, list item, and code block elements are preserved as structural units when they fit inside the configured maximum. Oversized elements split into bounded-overlap chunks.

## Queryable Lineage

Phase 5 persists durable artifact and chunk lineage:

- `document_artifacts` records artifact type, object URI, content hash, size, schema version, and metadata for a document version.
- `document_chunks` records chunk identity, chunk order, text, hash, source element IDs, heading path, page range, source offsets, and metadata.

The service writes `artifacts/normalized.json` and `artifacts/chunks.json` to object storage and stores queryable rows in PostgreSQL. Re-running the service for the same document version replaces normalized/chunk-manifest artifact rows and chunk rows for that version.

## Extraction Artifact

Extraction artifacts use schema version `1` and are derived from chunk manifests:

```json
{
  "schema_version": "1",
  "source": {
    "document_id": "11111111-1111-4111-8111-111111111111",
    "document_version_id": "22222222-2222-4222-8222-222222222222",
    "chunk_manifest_hash": "sha256:..."
  },
  "status": "succeeded",
  "extraction": {
    "title": "Example",
    "summary": "Short summary.",
    "topics": ["content pipeline"],
    "entities": [
      {"name": "AtlasRAG", "type": "concept"}
    ]
  },
  "provenance": {
    "provider": "ollama",
    "model": "gemma3:1b",
    "prompt_version": "builtin-summary-v1",
    "schema_version": "1",
    "input_manifest_hash": "sha256:...",
    "prompt_hash": "sha256:...",
    "response_hash": "sha256:...",
    "status": "succeeded"
  }
}
```

The built-in extraction schema requires `summary` and accepts optional `title`, string `topics`, and `entities` with `person`, `organization`, `place`, `concept`, or `other` types. LLM output must parse as JSON and validate against this schema.

Failed extraction attempts are also persisted. In that case, `status` is `failed`, `extraction` is `null`, and provenance includes `error_code` and `error_message`. Optional failures are non-blocking. Required failures return a blocking service result so the worker can fail the job and document version.

Skipped extraction attempts can be persisted with `status` set to `skipped` when extraction is disabled.

## Subprocess Boundary

`BoundedParserRunner` executes parser code in a subprocess and enforces:

- Maximum raw source bytes.
- Parser timeout.
- Maximum normalized output bytes.
- Maximum element count.

Workflow code must not run parsers directly. The ingestion worker activity calls the parser runner after reading and verifying raw source bytes.

## Current Limitation

Phase 7 wires parser, chunking, artifact persistence, chunk-lineage, extraction, and extraction-provenance contracts into the Temporal worker. The milestone still stops before embeddings, vector indexes, graph mutation, and query execution.
