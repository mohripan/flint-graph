# AtlasRAG

A production-oriented GraphRAG platform. The current implementation provides the ingestion control plane plus a Temporal-backed content pipeline that materializes source bytes, parses supported formats, chunks content, records lineage, and persists extraction provenance.

## Why these milestones come first

The early milestones establish durable identities, tenant boundaries, version semantics, idempotency, inspectable job state, and a safe asynchronous dispatch path before retrieval and graph mutation are introduced. LangGraph will later orchestrate query execution; it will not replace the ingestion control plane.

## Requirements

- Docker with Compose, or PostgreSQL 17+
- `uv`
- Python 3.12

## Run locally with Docker

```bash
docker compose up --build
```

Then open:

- API documentation: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`
- Grafana: `http://localhost:3000`
- Temporal Web UI: `http://localhost:8233`
- Liveness: `http://localhost:8000/health/live`
- Readiness: `http://localhost:8000/health/ready`

## Run locally without containerizing the API

```bash
cp .env.example .env
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn atlas_rag.main:app --reload
```

In another shell, run Temporal locally and then start the outbox relay:

```bash
temporal server start-dev
make relay
make worker
```

## Exercise the vertical slice

Create a tenant:

```bash
curl -sS -X POST http://localhost:8000/v1/tenants \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme Research"}'
```

Use the returned tenant ID to upload source material:

```bash
curl -sS -X POST http://localhost:8000/v1/documents/uploads \
  -H 'X-Tenant-ID: <tenant-id>' \
  -H 'Idempotency-Key: upload-note-001' \
  -F 'title=Uploaded Note' \
  -F 'external_id=uploaded-note-001' \
  -F 'file=@note.md;type=text/markdown'
```

Or materialize a URL:

```bash
curl -sS -X POST http://localhost:8000/v1/documents/from-url \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-ID: <tenant-id>' \
  -H 'Idempotency-Key: url-note-001' \
  -d '{"title":"Example Page","source_url":"https://example.org/","external_id":"example-page"}'
```

Both intake endpoints create the document, document version, ingestion job, and outbox message in one durable path. Repeating the same request with the same idempotency key returns the same document/version/job with HTTP 200 rather than creating another version.

With the relay and worker running, the job should move from `queued` to `running` to `completed`. The worker verifies the raw object hash, runs the bounded parser, writes `normalized.json`, `chunks.json`, and `extraction.json`, persists queryable chunk lineage, and activates the document version. If Ollama is unavailable in default optional extraction mode, extraction provenance records the failure and the job can still complete.

Fetch a job:

```bash
curl -sS http://localhost:8000/v1/ingestion-jobs/<job-id> \
  -H 'X-Tenant-ID: <tenant-id>' \
```

Fetch job events:

```bash
curl -sS http://localhost:8000/v1/ingestion-jobs/<job-id>/events \
  -H 'X-Tenant-ID: <tenant-id>' \
```

Cancel a queued or running job:

```bash
curl -sS -X POST \
  http://localhost:8000/v1/ingestion-jobs/<job-id>/cancel \
  -H 'X-Tenant-ID: <tenant-id>'
```

## Quality commands

```bash
make check
```

## Implemented invariants

1. Every document belongs to exactly one tenant.
2. Tenant-scoped reads deliberately return 404 for foreign resources.
3. Every ingestion attempt targets a distinct immutable document version.
4. Version numbers are allocated while locking the document row.
5. An idempotency key is unique within a tenant.
6. The initial `job.queued` transition is written in the same transaction as the job.
7. New jobs and cancellations write transactional outbox messages before leaving the API transaction.
8. The outbox relay marks messages published only after Temporal accepts the operation.
9. Job state changes go through explicit transition rules and append events.
10. Completed jobs activate their document version.
11. Failed jobs fail their document version.
12. Cancelled jobs cancel their document version.
13. Activating a version supersedes any previous active version for the same document.
14. Failed or cancelled newer versions do not disturb the current active version.
15. API errors use `application/problem+json` and include a request ID.
16. Upload and URL intake materialize immutable raw objects before queuing ingestion.
17. The worker verifies raw content hashes before parsing.
18. Normalized, chunk-manifest, and extraction artifacts are stored in object storage.
19. Queryable chunk lineage is persisted in PostgreSQL.
20. Optional extraction failure records provenance without blocking version activation.
21. Required extraction failure records provenance and fails the job/version.

## Current milestone boundary

Milestone 03 stops before embeddings, vector indexes, graph mutation, and query-time orchestration. The next major work should introduce retrieval/indexing contracts on top of the persisted chunks and artifact lineage.

## Security status

This milestone is for local development. `X-Tenant-ID` is a tenant-routing input, not authentication or authorization. Do not expose this API publicly until trusted identity, tenant membership checks, role enforcement, and production secret management are implemented. See `docs/architecture/security-boundary.md`.

## Learning notes

Milestone notes:

- Foundation: `docs/milestones/01-foundation.md`
- Durable ingestion dispatch: `docs/milestones/02-durable-ingestion-dispatch.md`
- Content pipeline: `docs/milestones/03-content-pipeline.md`
- Local dispatch runbook: `docs/runbooks/durable-ingestion-dispatch.md`
- Content pipeline developer runbook: `docs/runbooks/content-pipeline-developer.md`
- Content pipeline QA guide: `docs/runbooks/content-pipeline-qa-guide.md`
