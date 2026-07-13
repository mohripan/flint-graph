# Content Artifact Contract

## Purpose

AtlasRAG parser output is an Atlas-owned normalized artifact. It is not a LangChain loader object, a PDF library object, or an HTML parser object. Later chunking, extraction, and lineage code should consume this contract.

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

## Subprocess Boundary

`BoundedParserRunner` executes parser code in a subprocess and enforces:

- Maximum raw source bytes.
- Parser timeout.
- Maximum normalized output bytes.
- Maximum element count.

Workflow code must not run parsers directly. Later worker activities should call the parser runner after reading and verifying raw source bytes.

## Current Limitation

Phase 4 implements parser contracts and parser tests. The Temporal worker still runs the stub ingestion activity until Phase 7 wires the real pipeline into worker activities.
