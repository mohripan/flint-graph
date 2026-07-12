# Durable ingestion dispatch runbook

## Purpose

Use this runbook to exercise the durable dispatch path locally.

Current implemented path:

```text
API transaction
    -> outbox_messages row
    -> outbox relay
    -> Temporal workflow start request
    -> ingestion worker
    -> stub ingestion activities
```

The current worker executes stub ingestion only. It proves dispatch and state transitions without parsing, chunking, embedding, indexing, or object-storage reads.

## Docker Compose

Start the local stack:

```powershell
docker compose up --build
```

Useful URLs:

- API docs: `http://localhost:8000/docs`
- Temporal Web UI: `http://localhost:8233`
- Grafana: `http://localhost:3000`

Relevant services:

- `api`: records jobs and outbox messages
- `outbox-relay`: polls `outbox_messages` and starts Temporal workflows
- `ingestion-worker`: runs `IngestDocumentWorkflow` and stub activities
- `temporal`: local Temporal development server
- `postgres`: application database

## Local processes

Run infrastructure:

```powershell
docker compose up -d postgres observability temporal
```

Run migrations:

```powershell
uv run alembic upgrade head
```

Run the API:

```powershell
uv run uvicorn atlas_rag.main:app --reload
```

Run the relay:

```powershell
uv run python -m atlas_rag.processes.outbox_relay
```

Run the worker:

```powershell
uv run python -m atlas_rag.processes.ingestion_worker
```

## Manual verification

1. Create a tenant.
2. Create a document.
3. Create an ingestion job with an `Idempotency-Key`.
4. Confirm the API returns `queued`.
5. Confirm an `outbox_messages` row exists with status `pending`.
6. Let the relay run.
7. Confirm the outbox message changes to `published`.
8. Open Temporal Web UI and confirm a workflow with ID `ingestion-job-{job_id}` exists.
9. Let the worker run.
10. Confirm the job status changes to `completed`.
11. Fetch job events and confirm `job.queued`, `job.started`, and `job.completed`.

## Troubleshooting

- If messages stay `pending`, check the `outbox-relay` logs.
- If `attempt_count` increases, inspect `last_error`.
- If Temporal cannot be reached, verify `ATLAS_TEMPORAL_ADDRESS`.
- In Docker Compose, the relay uses `temporal:7233`; outside Docker, use `localhost:7233`.
