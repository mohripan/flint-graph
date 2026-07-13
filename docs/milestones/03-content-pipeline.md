# Milestone 03: Content pipeline

## Status

Planned. This document describes the approved milestone target. It should be updated after implementation to describe completed behavior.

## Outcome Target

Milestone 03 turns the existing Temporal-backed stub worker into the first real content pipeline.

Target flow:

```text
verified upload or URL
    -> immutable source materialization in MinIO
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

The milestone intentionally stops before embeddings, vector indexes, graph mutation, and query execution.

## Scope

Included:

- MinIO-backed S3-compatible object storage.
- Multipart upload through the AtlasRAG API.
- URL materialization through the AtlasRAG API.
- Immutable raw source objects with size and `sha256:` hash metadata.
- Parser interfaces for text, Markdown, HTML, and text-based PDF.
- Bounded parser subprocess execution.
- Normalized document artifact schema.
- Structural chunking.
- Chunk-manifest artifact.
- PostgreSQL chunk lineage.
- Configurable structured LLM extraction using Ollama.
- Extraction schema validation and provenance.
- Document-version activation, failure, and cancellation semantics.
- Semi-technical QA guide for end-to-end local validation.

Out of scope:

- OCR for scanned PDFs.
- Embeddings.
- Vector search.
- Graph construction.
- Query-time LangGraph orchestration.
- Production authentication and authorization.
- Production object lifecycle management.

## Durable Boundaries

The API performs intake and durable command recording. It does not parse, chunk, extract, embed, or activate document versions.

The worker performs content processing through Temporal activities. Workflow code remains deterministic and does not import database or object-storage infrastructure directly.

MinIO stores immutable raw and derived artifacts. PostgreSQL stores queryable identities, status, lineage, and provenance.

## Version Semantics

Document versions use explicit terminal states:

```text
pending
active
superseded
failed
cancelled
deleted
```

A completed job activates its version. A failed job fails its version. A cancelled job cancels its version. Activating a new version supersedes any previous active version for that document.

## Extraction Defaults

Extraction is on by default but optional by default:

```env
ATLAS_EXTRACTION_ENABLED=true
ATLAS_EXTRACTION_MODE=optional
ATLAS_LLM_PROVIDER=ollama
ATLAS_OLLAMA_BASE_URL=http://host.docker.internal:11434
ATLAS_OLLAMA_MODEL=gemma3:1b
```

If Ollama is unavailable in optional mode, the extraction failure is recorded and the document version can still activate.

## Exit Criteria

- Upload and URL intake work through real API calls.
- Raw source objects are visible in MinIO.
- The worker reads raw bytes from MinIO and verifies hashes.
- Text, Markdown, HTML, and text-based PDF fixtures produce normalized artifacts.
- Chunk manifests are written to MinIO.
- Chunk lineage is queryable in PostgreSQL.
- Extraction provenance is persisted for success and failure cases.
- Optional extraction failure does not block activation.
- Required extraction failure fails the job and version.
- Cancellation marks both job and version cancelled.
- Manual QA guide steps can be run by a semi-technical user.
- Automated verification passes or any failures are clearly documented.

