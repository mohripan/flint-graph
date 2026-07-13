# Agent Handoff Guide

## Project Snapshot

AtlasRAG is an early GraphRAG platform. Through Milestone 05 it implements the ingestion control plane, a real Temporal-backed content pipeline, provenance-rich staged extraction proposals, and a resolved knowledge graph with reviewable, reversible merges.

Implemented path:

```text
API intake -> immutable raw object in MinIO
    -> durable ingestion job + outbox message
    -> outbox relay -> Temporal ingestion workflow
    -> worker: verify hash -> parse -> chunk -> extract staged proposals
    -> verify exact evidence spans + persist extraction run/invocation/staged records
    -> proposal candidates
    -> per-tenant staged resolution (auto attach / review / new entity)
    -> aggregate relationships
    -> project resolved graph into Neo4j
```

PostgreSQL is the system of record for the control plane, extraction provenance, staged proposals, and the resolved graph. Neo4j is an idempotent, rebuildable projection. MinIO stores immutable raw and derived artifacts. The API serves the entity, review-queue, merge/unmerge, and audit endpoints; dedicated extraction inspection endpoints are deferred.

Earlier milestones (durable dispatch, content pipeline) remain in place; see `docs/milestones/`.

## Ground Rules

- Document durable decisions and completed milestone behavior under `docs/`.
- Use `notes/` for scratch planning, manual test notes, and working handoff context. `notes/` is gitignored.
- Add or update tests before changing implementation behavior.
- Prefer focused changes that preserve the current modular shape.
- Do not treat `X-Tenant-ID` as authentication. It is only local tenant routing until real identity and authorization exist.
- Do not revert unrelated user changes in the working tree.

## Useful Commands

```powershell
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
docker compose up --build
docker compose down -v
```

Convenience make targets exist for Unix-like shells:

```bash
make test
make lint
make typecheck
make check
make relay
make worker
```

On Windows PowerShell, running the `uv` and `docker compose` commands directly is usually clearer than relying on `make`.

## Local Services

Docker Compose exposes:

- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Temporal Web UI: `http://localhost:8233`
- Grafana: `http://localhost:3000`
- Neo4j browser: `http://localhost:7474` (user `neo4j`, password `atlaspassword`)
- PostgreSQL host port: `localhost:55432`
- Temporal gRPC host port: `localhost:7233`
- Neo4j Bolt host port: `localhost:7687`

The `temporal` compose service uses `temporalio/temporal:latest` with `server start-dev --ip 0.0.0.0 --namespace default`. Temporal's development server includes a Web UI by default.

## Key Files

- `src/atlas_rag/api/routes/documents.py`: document, ingestion job, cancellation, and job event endpoints.
- `src/atlas_rag/application/services/ingestion_jobs.py`: transactional document-version/job/event/outbox creation.
- `src/atlas_rag/application/services/job_transitions.py`: explicit job state transition rules.
- `src/atlas_rag/application/services/job_cancellation.py`: API-side cancellation and cancellation outbox creation.
- `src/atlas_rag/application/services/outbox.py`: outbox append helper and trace-context capture.
- `src/atlas_rag/application/services/outbox_relay.py`: pending outbox polling and Temporal dispatch.
- `src/atlas_rag/infrastructure/temporal.py`: Temporal client adapter.
- `src/atlas_rag/workflows/ingestion.py`: `IngestDocumentWorkflow`.
- `src/atlas_rag/worker/activities/ingestion.py`: worker activities that mutate job state.
- `src/atlas_rag/processes/outbox_relay.py`: long-running relay process.
- `src/atlas_rag/processes/ingestion_worker.py`: long-running Temporal worker.
- `src/atlas_rag/infrastructure/db/models.py`: SQLAlchemy models.
- `migrations/versions/0002_outbox_messages.py`: outbox migration.
- `docs/runbooks/durable-ingestion-dispatch.md`: durable dispatch runbook.
- `docs/architecture/object-storage-contract.md`: future object-storage contract.
- `docs/adr/0003-transactional-outbox-and-temporal.md`: durable dispatch ADR.

Milestone 04 knowledge graph:

- `src/atlas_rag/application/entity_resolution/`: pure normalization and scoring.
- `src/atlas_rag/application/services/candidate_generation.py`: pg_trgm blocking.
- `src/atlas_rag/application/services/resolution.py`: banded resolution + advisory lock + relationship aggregation.
- `src/atlas_rag/application/services/entity_merge.py`: soft merge with undo log + unmerge.
- `src/atlas_rag/application/services/review.py`: review-queue decisions.
- `src/atlas_rag/application/services/graph_projection.py`: Neo4j projection/reconcile.
- `src/atlas_rag/workflows/resolution.py` and `src/atlas_rag/worker/activities/resolution.py`: per-tenant resolution workflow/activities.
- `src/atlas_rag/api/routes/graph.py`: entity, review, merge/unmerge, and audit endpoints.
- `src/atlas_rag/infrastructure/neo4j.py` and `neo4j_migrations.py`: Neo4j client and Cypher migration runner.
- `migrations/versions/0005_knowledge_graph.py` and `migrations/neo4j/`: graph schema.
- `docs/milestones/04-knowledge-graph.md`, `docs/adr/0004-postgres-authoritative-resolution-neo4j-projection.md`, `docs/architecture/knowledge-graph-contract.md`, `docs/runbooks/knowledge-graph-*.md`.
Milestone 05 provenance-rich extraction:

- `src/atlas_rag/application/extraction_proposals.py`: provider-neutral proposal models and deterministic provider.
- `src/atlas_rag/application/extraction_evidence.py`: exact quote evidence resolver.
- `src/atlas_rag/application/services/provenance_extraction.py`: transactional extraction run, invocation, evidence, staged-record, and manifest persistence.
- `src/atlas_rag/application/services/proposal_candidate_generation.py`: non-destructive proposal candidate generation.
- `src/atlas_rag/application/services/staged_resolution.py`: canonical resolution over staged proposals.
- `src/atlas_rag/infrastructure/ollama.py`: Ollama proposal adapter at the infrastructure edge.
- `migrations/versions/0006_provenance_extraction.py` and `0007_staged_resolution_state.py`: provenance and staged-resolution schema.
- `docs/milestones/05-provenance-rich-extraction.md`, `docs/adr/0005-staged-extraction-proposals-before-canonical-resolution.md`, `docs/architecture/extraction-proposal-contract.md`, `docs/runbooks/provenance-extraction-*.md`.

## Current Invariants

- A document belongs to one tenant.
- Tenant-scoped reads return 404 for foreign resources.
- Every new ingestion attempt creates one immutable document version.
- Reusing an idempotency key in the same tenant returns the existing job.
- The initial `job.queued` event and `ingestion.job_queued` outbox message are written in the same API transaction as the job.
- Cancellation writes `job.cancelled` plus `ingestion.job_cancelled` before leaving the API transaction.
- The relay marks an outbox message `published` only after Temporal accepts the start or cancellation request.
- Job state changes go through explicit transition rules and append events.
- The relay prioritizes queued workflow-start messages before cancellation messages when both are available.
- Model output is staged and evidence-verified before it can affect canonical graph state.
- Accepted staged entities, relations, and claims retain at least one verified evidence span.
- Canonical graph mutation happens in deterministic resolution services, not provider adapters.

## Temporal Notes

- Workflow name: `IngestDocumentWorkflow`.
- Task queue: configured by `ATLAS_TEMPORAL_TASK_QUEUE`, default `ingestion`.
- Workflow ID: `ingestion-job-{job_id}`.
- Workflow memo stores `trace_context` from outbox headers.
- Workflow start uses duplicate-safe Temporal policies so retrying the relay does not create duplicate workflows.
- Cancellation dispatch uses the same workflow ID and calls Temporal workflow cancellation.

## Known Limitations

- Small local extraction models can produce sparse or noisy proposals; the pipeline validates evidence and persists accepted output faithfully.
- Dedicated extraction inspection APIs are not implemented yet; use PostgreSQL queries in the provenance extraction runbook.
- `unmerge` reverses the most recent merge and assumes no conflicting interleaved graph changes.
- Neo4j projection re-reconciles the whole tenant subgraph after each resolution rather than applying deltas.
- Trace context is captured and carried into Temporal memo, but automatic distributed span continuation inside workflows and activities is not complete.
- The local Temporal dev server is not production Temporal.
- The compose Temporal service currently uses the `latest` image tag, which is convenient for early local development but should be pinned before production-like environments.

## Before Ending A Change

Run the narrowest meaningful verification, and prefer the full set when behavior changed:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

Tell the user exactly which commands passed and which were skipped.
