# Milestone 03 Content Pipeline Design

## Status

Approved design. Implementation has not started.

This document records the agreed Milestone 03 shape before implementation. It is intentionally more specific than a roadmap and less final than completed milestone documentation.

## Goal

Implement the first real content pipeline:

```text
verified upload or URL
    -> immutable source materialization
    -> content-aware format detection
    -> bounded parser subprocess
    -> normalized document artifact
    -> structural chunking
    -> chunk-manifest artifact
    -> queryable chunk lineage
    -> optional structured LLM extraction
    -> schema validation and extraction provenance
    -> document-version activation
```

Milestone 03 extends the Milestone 02 durable dispatch path. The API still records durable intent and does not perform parser, chunker, extraction, or activation work inside HTTP request handlers.

## Architectural Boundaries

The API owns intake:

- Validate tenant routing.
- Accept multipart uploads.
- Fetch approved URLs.
- Materialize immutable raw source bytes into MinIO/S3-compatible object storage.
- Compute and persist raw content hash and size metadata.
- Create the document, document version, ingestion job, job event, and outbox message transactionally.

The worker owns content processing:

- Read raw objects from MinIO.
- Verify content hash and size.
- Detect content format.
- Execute parser code in a bounded subprocess.
- Write normalized and chunk-manifest artifacts.
- Persist queryable chunk lineage.
- Run structured LLM extraction if enabled.
- Validate extraction output.
- Persist extraction provenance.
- Activate, fail, or cancel the document version.

Temporal remains the orchestration boundary. Workflow code stays deterministic and thin. Activities perform I/O and database writes.

## Storage

Milestone 03 uses MinIO as the local S3-compatible object store. The production-facing storage boundary is an object-store interface with an S3-compatible implementation.

Object URIs use internal S3-style references:

```text
s3://<bucket>/tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/raw/source
s3://<bucket>/tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/artifacts/normalized.json
s3://<bucket>/tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/artifacts/chunks.json
s3://<bucket>/tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/artifacts/extraction.json
```

The bucket and client settings will be exposed through `FLINT_GRAPH_` environment variables and documented in `.env.example`.

## API Contract

The current metadata-first document endpoint is provisional. Milestone 03 should reshape the API around real source materialization.

Recommended endpoints:

```text
POST /v1/documents/uploads
POST /v1/documents/from-url
GET  /v1/documents/{document_id}
GET  /v1/documents/{document_id}/versions
GET  /v1/document-versions/{version_id}
POST /v1/document-versions/{version_id}/ingestion-jobs
GET  /v1/ingestion-jobs/{job_id}
GET  /v1/ingestion-jobs/{job_id}/events
POST /v1/ingestion-jobs/{job_id}/cancel
```

Intake endpoints create the first ingestion job immediately. A user who uploads a file or submits a URL normally expects ingestion to start.

Later version-intake endpoints should be explicit:

```text
POST /v1/documents/{document_id}/versions/uploads
POST /v1/documents/{document_id}/versions/from-url
```

Idempotency applies to intake. Replaying the same idempotency key returns the same document, version, and job. Reusing a key with materially different source metadata or bytes returns conflict.

## Parser Contract

Supported formats:

- Plain text.
- Markdown.
- HTML.
- Text-based PDF.

Scanned PDF OCR is out of scope. Empty text extraction from a PDF is a controlled failure.

Parser output is a FlintGraph-owned normalized artifact rather than a LangChain-native document object. LangChain and LangGraph can still be used above or behind FlintGraph interfaces, but durable ingestion contracts should not depend on framework-specific loader output.

Normalized artifact shape:

```json
{
  "schema_version": "1",
  "source": {
    "document_id": "...",
    "document_version_id": "...",
    "content_hash": "sha256:..."
  },
  "format": "pdf",
  "title": "...",
  "elements": [
    {
      "id": "element-000001",
      "type": "heading",
      "text": "...",
      "level": 1,
      "page": 3,
      "source_offsets": {"start": 120, "end": 240}
    }
  ],
  "warnings": []
}
```

Parser subprocess limits include timeout, max raw bytes, max normalized output bytes, and max element count.

## Chunking And Lineage

Chunking consumes the normalized artifact. It should be deterministic for the same artifact and chunking config.

Rules:

- Preserve heading hierarchy as chunk context.
- Prefer structural boundaries.
- Avoid splitting small paragraphs, list items, code blocks, and table cells.
- Split oversized elements with bounded overlap.
- Attach chunks to source element IDs and source positions where available.

Persistent lineage tables should make chunks inspectable without reading object storage. Initial tables:

```text
document_artifacts
document_chunks
```

`document_artifacts` records raw, normalized, chunk-manifest, and extraction artifacts.

`document_chunks` records text, chunk order, hashes, source element IDs, heading path, page range, offsets, and metadata.

Embeddings and retrieval indexes are out of scope for Milestone 03.

## Structured Extraction

Extraction is configurable and uses Ollama first.

Default settings should match `.env.example`:

```env
FLINT_GRAPH_EXTRACTION_ENABLED=true
FLINT_GRAPH_EXTRACTION_MODE=optional
FLINT_GRAPH_LLM_PROVIDER=ollama
FLINT_GRAPH_OLLAMA_BASE_URL=http://host.docker.internal:11434
FLINT_GRAPH_OLLAMA_MODEL=gemma3:1b
FLINT_GRAPH_EXTRACTION_TIMEOUT_SECONDS=60
```

Modes:

- `disabled`: no LLM extraction is attempted.
- `optional`: extraction failures are recorded, but the version can still activate.
- `required`: extraction failure fails the job and version.

Milestone 03 starts with one built-in extraction schema:

```json
{
  "title": "string|null",
  "summary": "string",
  "topics": ["string"],
  "entities": [
    {"name": "string", "type": "person|organization|place|concept|other"}
  ]
}
```

LLM output must parse as JSON and validate against the schema. Provenance records provider, model, prompt version, schema version, input manifest hash, response hashes, status, errors, and timestamps.

## Version Lifecycle

Add explicit document-version cancellation:

```text
pending
active
superseded
failed
cancelled
deleted
```

Invariants:

- A completed ingestion job points to an active document version.
- A failed ingestion job points to a failed document version.
- A cancelled ingestion job points to a cancelled document version.
- Only one version per document is active.
- Activating a new version supersedes the previous active version.
- Failed or cancelled newer versions do not disturb the current active version.

Version changes should use a small application service:

```text
activate_document_version(...)
fail_document_version(...)
cancel_document_version(...)
```

## Documentation And Verification

Durable docs to create or update during implementation:

- `docs/milestones/03-content-pipeline.md`
- `docs/architecture/object-storage-contract.md`
- `docs/architecture/content-artifact-contract.md`
- `docs/runbooks/content-pipeline.md`
- `docs/runbooks/content-pipeline-qa-guide.md`
- `docs/adr/0004-content-pipeline-artifacts.md`

Working notes:

- `notes/milestone-03/01-content-pipeline-plan.md`
- `notes/milestone-03/02-manual-testing-content-pipeline.md`
- `notes/milestone-03/03-code-flow-content-pipeline.md`
- `notes/milestone-03/04-parser-fixtures-and-edge-cases.md`

Required verification before ending behavior-changing phases:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

Phases that touch MinIO, Temporal, or Ollama should also include a real manual Docker Compose exercise.
