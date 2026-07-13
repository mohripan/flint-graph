# Agent Handoff Guide

## Project Snapshot

AtlasRAG is an early GraphRAG platform. The current implementation is the ingestion control plane plus durable dispatch from the API to a Temporal-backed stub ingestion worker.

Implemented dispatch path:

```text
API transaction
    -> create document version
    -> create ingestion job
    -> append job event
    -> insert outbox message
    -> outbox relay
    -> Temporal workflow
    -> ingestion worker
```

The worker does not parse, chunk, embed, index, or read object storage yet. It only proves durable job dispatch, state transitions, cancellation, retry behavior, and process boundaries.

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
- PostgreSQL host port: `localhost:55432`
- Temporal gRPC host port: `localhost:7233`

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

## Temporal Notes

- Workflow name: `IngestDocumentWorkflow`.
- Task queue: configured by `ATLAS_TEMPORAL_TASK_QUEUE`, default `ingestion`.
- Workflow ID: `ingestion-job-{job_id}`.
- Workflow memo stores `trace_context` from outbox headers.
- Workflow start uses duplicate-safe Temporal policies so retrying the relay does not create duplicate workflows.
- Cancellation dispatch uses the same workflow ID and calls Temporal workflow cancellation.

## Known Limitations

- Ingestion is still a stub.
- Object storage is contract-only; there is no storage client yet.
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
