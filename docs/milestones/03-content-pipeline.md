# Milestone 03: Content pipeline

## Status

In progress. Phases 1, 2, and 3 are implemented. The rest of this document describes the approved milestone target and should be updated as later phases land.

## Phase 1 Completed Behavior

Implemented storage and configuration foundation:

- Docker Compose includes MinIO and a `minio-init` bucket creation service.
- Local bucket name is `atlas-rag`.
- Host-local object-store endpoint is `http://localhost:9000`.
- Container object-store endpoint is `http://minio:9000`.
- Settings expose `ATLAS_OBJECT_STORE_*` variables for S3-compatible storage.
- `atlas_rag.infrastructure.object_store` defines the object-store interface, S3 URI helpers, deterministic raw/artifact key generation, and an S3-compatible implementation.
- Object URIs use internal `s3://<bucket>/<key>` references.

## Phase 2 Completed Behavior

Implemented raw-source intake:

- `POST /v1/documents/uploads` accepts multipart file uploads.
- `POST /v1/documents/from-url` fetches URL content through the API.
- Both intake endpoints require `Idempotency-Key`.
- The API computes `sha256:<hex>` over raw source bytes.
- The API writes raw source bytes to object storage before creating the durable ingestion intent.
- Intake creates the document, first document version, ingestion job, `job.queued` event, and `ingestion.job_queued` outbox message.
- `document_versions.object_uri`, `document_versions.content_hash`, and `document_versions.metadata` are populated for intake-created versions.
- Replaying the same tenant/idempotency key with the same request returns the existing document/version/job with HTTP 200.
- Reusing an idempotency key with different source bytes or materially different intake metadata returns HTTP 409.

The existing metadata-first document and explicit job endpoints still exist for Milestone 2 compatibility. They may still create document versions without `object_uri` and `content_hash`; the new intake endpoints are the preferred path for real source ingestion.

## Phase 3 Completed Behavior

Implemented document-version lifecycle semantics:

- `document_versions.status` now includes `cancelled`.
- Document-version changes go through `activate_document_version`, `fail_document_version`, and `cancel_document_version`.
- Completing an ingestion job activates its document version.
- Failing an ingestion job marks its document version `failed`.
- Cancelling an ingestion job marks its document version `cancelled`.
- Activating a new version supersedes any previous active version for the same document.
- Failed and cancelled newer versions do not disturb the current active version.
- Job events are listed with deterministic lifecycle ordering when timestamps tie.

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
