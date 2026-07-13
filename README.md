# AtlasRAG

A production-oriented GraphRAG platform. The current implementation provides the ingestion control plane plus durable dispatch from the API to a Temporal-backed stub ingestion worker.

## Why these milestones come first

LLM frameworks are intentionally absent. Before extraction or retrieval exists, the system needs durable identities, tenant boundaries, version semantics, idempotency, inspectable job state, and a safe asynchronous dispatch path. LangGraph will later orchestrate query execution; it will not replace the ingestion control plane.

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

Use the returned tenant ID:

```bash
curl -sS -X POST http://localhost:8000/v1/documents \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-ID: <tenant-id>' \
  -d '{
    "title":"Graph Retrieval Architecture",
    "source_type":"url",
    "source_uri":"https://example.org/architecture",
    "external_id":"architecture-001"
  }'
```

Queue ingestion with a retry-safe key:

```bash
curl -sS -X POST \
  http://localhost:8000/v1/documents/<document-id>/ingestion-jobs \
  -H 'X-Tenant-ID: <tenant-id>' \
  -H 'Idempotency-Key: architecture-001-ingest-1'
```

Repeating the same request returns the same job with HTTP 200 rather than creating another version. A new idempotency key creates the next immutable document version.

With the relay and worker running, the job should move from `queued` to `running` to `completed`.

Milestone 03 adds preferred raw-source intake endpoints that materialize immutable source bytes before queuing ingestion:

```bash
curl -sS -X POST http://localhost:8000/v1/documents/uploads \
  -H 'X-Tenant-ID: <tenant-id>' \
  -H 'Idempotency-Key: upload-note-001' \
  -F 'title=Uploaded Note' \
  -F 'file=@note.md;type=text/markdown'
```

```bash
curl -sS -X POST http://localhost:8000/v1/documents/from-url \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-ID: <tenant-id>' \
  -H 'Idempotency-Key: url-note-001' \
  -d '{"title":"Example Page","source_url":"https://example.org/"}'
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
10. API errors use `application/problem+json` and include a request ID.

## Next milestone

Introduce real content ingestion:

- object-storage upload and retrieval implementation
- content hashing and size limits
- parser selection and controlled parse failures
- chunking contracts
- first persistence model for parsed artifacts
- PostgreSQL concurrency tests for version allocation and relay locking

## Security status

This milestone is for local development. `X-Tenant-ID` is a tenant-routing input, not authentication or authorization. Do not expose this API publicly until trusted identity, tenant membership checks, role enforcement, and production secret management are implemented. See `docs/architecture/security-boundary.md`.

## Learning notes

Milestone notes:

- Foundation: `docs/milestones/01-foundation.md`
- Durable ingestion dispatch: `docs/milestones/02-durable-ingestion-dispatch.md`
- Local dispatch runbook: `docs/runbooks/durable-ingestion-dispatch.md`
