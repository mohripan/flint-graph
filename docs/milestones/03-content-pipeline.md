# Milestone 03: Content pipeline

## Status

Complete. Phases 1 through 8 are implemented.

## Phase 1 Completed Behavior

Implemented storage and configuration foundation:

- Docker Compose includes MinIO and a `minio-init` bucket creation service.
- Local bucket name is `flint-graph`.
- Host-local object-store endpoint is `http://localhost:9000`.
- Container object-store endpoint is `http://minio:9000`.
- Settings expose `FLINT_GRAPH_OBJECT_STORE_*` variables for S3-compatible storage.
- `flint_graph.infrastructure.object_store` defines the object-store interface, S3 URI helpers, deterministic raw/artifact key generation, and an S3-compatible implementation.
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

## Phase 4 Completed Behavior

Implemented parser contracts:

- Format detection for plain text, Markdown, HTML, and PDF.
- FlintGraph-owned normalized artifact models with schema version `1`.
- Parser errors for unsupported formats, decode failures, execution failures, and limit failures.
- Plain text parser that emits paragraph elements.
- Markdown parser that emits heading, paragraph, list item, and code block elements.
- HTML parser that emits title, heading, paragraph, and list item elements.
- Text-based PDF parser backed by `pypdf`; scanned or empty-text PDFs fail with a controlled parser error.
- `BoundedParserRunner` that executes parsing in a subprocess and enforces raw-byte, timeout, normalized-output, and element-count limits.
- Parser contract documentation in `docs/architecture/content-artifact-contract.md`.

The parser contract landed before worker integration. Phase 7 wires these parser contracts into the Temporal worker.

## Phase 5 Completed Behavior

Implemented chunking and lineage services:

- `document_artifacts` records normalized, chunk-manifest, raw, and extraction artifact identities.
- `document_chunks` stores queryable chunk text, order, hashes, source element IDs, heading path, page range, offsets, and metadata.
- Structural chunking consumes normalized document artifacts and is deterministic for the same artifact and config.
- Heading elements are preserved as chunk context rather than standalone chunks.
- Small structural elements are kept intact when possible.
- Oversized elements split with bounded overlap.
- Normalized artifacts are written to `artifacts/normalized.json`.
- Chunk-manifest artifacts are written to `artifacts/chunks.json`.
- Persisted chunk rows can be replaced for a document version, keeping retries idempotent at the service layer.

Phase 7 wires these chunking and lineage services into the Temporal worker.

## Phase 6 Completed Behavior

Implemented structured extraction and provenance services:

- Settings expose `FLINT_GRAPH_EXTRACTION_*`, `FLINT_GRAPH_LLM_PROVIDER`, and `FLINT_GRAPH_OLLAMA_*` variables.
- `OllamaExtractionClient` calls Ollama's JSON generation API behind the application extraction protocol.
- The built-in extraction schema validates `title`, `summary`, `topics`, and typed `entities`.
- Extraction prompts are deterministic and include chunk IDs for provenance.
- `artifacts/extraction.json` is written for succeeded, failed, and skipped extraction attempts.
- The `document_artifacts` extraction row records provider, model, prompt version, schema version, input manifest hash, prompt hash, response hash, status, and failure details.
- Optional extraction failures persist provenance and return a non-blocking result.
- Required extraction failures persist provenance and return a blocking result for Phase 7 worker job/version failure handling.

Phase 7 wires these extraction and provenance services into the Temporal worker.

## Phase 7 Completed Behavior

Implemented the real worker pipeline:

- `IngestDocumentWorkflow` now executes `run_ingestion_pipeline` instead of the stub ingestion activity.
- The ingestion worker registers the real pipeline activity with Temporal.
- The pipeline activity loads the raw object URI and content hash from the document version.
- Raw source bytes are read from object storage and verified against the persisted `sha256:` hash before parsing.
- Parser execution uses `BoundedParserRunner` with configurable parser limits.
- Normalized and chunk-manifest artifacts are written to object storage.
- Queryable chunk lineage is persisted in PostgreSQL.
- Extraction runs through the configured extraction service and Ollama client.
- Optional extraction failure writes failure provenance and still allows job completion/version activation.
- Required extraction failure writes failure provenance, fails the workflow activity, and the workflow marks the job and version failed.
- Parser, hash, and raw-object contract failures fail the workflow activity before activation.
- Docker Compose passes parser, chunking, and extraction settings to the ingestion worker.

## Phase 8 Completed Behavior

Completed milestone documentation and manual verification:

- README describes the current real content pipeline and preferred upload/URL intake path.
- `docs/runbooks/content-pipeline-developer.md` documents developer-level pipeline checks and failure modes.
- `docs/runbooks/content-pipeline-qa-guide.md` documents semi-technical end-to-end QA steps.
- `docs/runbooks/durable-ingestion-dispatch.md` now uses upload intake for successful worker runs.
- `docs/architecture/object-storage-contract.md` and `docs/architecture/content-artifact-contract.md` describe current artifact and worker behavior.
- Manual verification results are recorded in `notes/milestone-03/02-manual-testing-content-pipeline.md`.

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
- Multipart upload through the FlintGraph API.
- URL materialization through the FlintGraph API.
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
FLINT_GRAPH_EXTRACTION_ENABLED=true
FLINT_GRAPH_EXTRACTION_MODE=optional
FLINT_GRAPH_LLM_PROVIDER=ollama
FLINT_GRAPH_OLLAMA_BASE_URL=http://host.docker.internal:11434
FLINT_GRAPH_OLLAMA_MODEL=gemma3:1b
FLINT_GRAPH_EXTRACTION_TIMEOUT_SECONDS=180
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
