# AtlasRAG

A production-oriented GraphRAG platform. The current implementation provides the ingestion control plane, a Temporal-backed content pipeline that materializes source bytes, parses supported formats, chunks content, records lineage, and persists extraction provenance, and a resolved knowledge graph built from extracted entities and claims with reviewable, reversible merges. PostgreSQL is the system of record; Neo4j is an idempotent projection of the resolved graph.

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
- Neo4j browser: `http://localhost:7474`
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

## Explore the knowledge graph

After a document is ingested, per-tenant entity resolution turns extracted entities and claims into canonical entities and relationships, then projects them into Neo4j. Inspect the resolved graph through the API:

```bash
# Canonical entities (deduplicated across documents; support_count reflects cross-doc support)
curl -sS http://localhost:8000/v1/entities -H 'X-Tenant-ID: <tenant-id>'

# One entity with its aliases, mentions, and relationships
curl -sS http://localhost:8000/v1/entities/<entity-id> -H 'X-Tenant-ID: <tenant-id>'

# Pending merge-review queue for ambiguous matches
curl -sS http://localhost:8000/v1/merge-reviews -H 'X-Tenant-ID: <tenant-id>'

# Resolve a review item (accept attaches to the candidate; reject creates a distinct entity)
curl -sS -X POST http://localhost:8000/v1/merge-reviews/<candidate-id>/decision \
  -H 'X-Tenant-ID: <tenant-id>' -H 'Content-Type: application/json' \
  -d '{"decision":"accept","reason":"same company"}'

# Manual, reversible merge and unmerge
curl -sS -X POST http://localhost:8000/v1/entities/<source-id>/merge \
  -H 'X-Tenant-ID: <tenant-id>' -H 'Content-Type: application/json' \
  -d '{"target_entity_id":"<target-id>","reason":"duplicate"}'
curl -sS -X POST http://localhost:8000/v1/entities/<source-id>/unmerge \
  -H 'X-Tenant-ID: <tenant-id>' -H 'Content-Type: application/json' -d '{"reason":"was not a duplicate"}'

# Merge decision audit log
curl -sS http://localhost:8000/v1/merge-decisions -H 'X-Tenant-ID: <tenant-id>'
```

The resolved graph is visible in the Neo4j browser at `http://localhost:7474`. A stronger local extraction model such as `llama3.2` produces cleaner relationship triples than the default `gemma3:1b`.

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
22. Entity mentions and claims are derived from extraction with provenance and persisted idempotently per version.
23. Entity resolution runs one writer per tenant via a PostgreSQL advisory lock.
24. Resolution applies banded decisions: auto-attach, review queue, or new entity.
25. Every merge decision is recorded and reviewable; merges are soft and reversible.
26. Relationships aggregate from claims whose subject and object both resolve to entities.
27. PostgreSQL is authoritative; Neo4j is an idempotent projection rebuildable from PostgreSQL.

## Current milestone boundary

Milestone 04 builds the resolved knowledge graph and its projection into Neo4j. The planned Milestone 05 work refactors the extraction-to-resolution boundary so canonical resolution consumes provenance-rich staged proposals with verified evidence spans instead of the current transitional mention/claim bridge. Retrieval, embeddings, vector indexes, and query-time orchestration remain later work.

## Security status

This milestone is for local development. `X-Tenant-ID` is a tenant-routing input, not authentication or authorization. Do not expose this API publicly until trusted identity, tenant membership checks, role enforcement, and production secret management are implemented. See `docs/architecture/security-boundary.md`.

## Learning notes

Milestone notes:

- Foundation: `docs/milestones/01-foundation.md`
- Durable ingestion dispatch: `docs/milestones/02-durable-ingestion-dispatch.md`
- Content pipeline: `docs/milestones/03-content-pipeline.md`
- Knowledge graph: `docs/milestones/04-knowledge-graph.md`
- Provenance-rich extraction plan: `docs/milestones/05-provenance-rich-extraction.md`
- Local dispatch runbook: `docs/runbooks/durable-ingestion-dispatch.md`
- Content pipeline developer runbook: `docs/runbooks/content-pipeline-developer.md`
- Content pipeline QA guide: `docs/runbooks/content-pipeline-qa-guide.md`
- Knowledge graph developer runbook: `docs/runbooks/knowledge-graph-developer.md`
- Knowledge graph QA guide: `docs/runbooks/knowledge-graph-qa-guide.md`
- Knowledge graph contract: `docs/architecture/knowledge-graph-contract.md`
- Extraction proposal contract: `docs/architecture/extraction-proposal-contract.md`
