# Durable ingestion dispatch runbook

## Purpose

Use this runbook to exercise the durable dispatch path locally.

Current implemented path:

```text
API transaction
    -> outbox_messages row
    -> outbox relay
    -> Temporal workflow start request
```

The workflow and worker are added in the next phase. Until then, the relay can connect to Temporal and start the configured workflow type, but no worker will complete it.

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

## Manual verification

1. Create a tenant.
2. Create a document.
3. Create an ingestion job with an `Idempotency-Key`.
4. Confirm the API returns `queued`.
5. Confirm an `outbox_messages` row exists with status `pending`.
6. Let the relay run.
7. Confirm the outbox message changes to `published`.
8. Open Temporal Web UI and confirm a workflow with ID `ingestion-job-{job_id}` exists.

Until Phase 4 is implemented, the workflow will not be processed by a worker.

## Troubleshooting

- If messages stay `pending`, check the `outbox-relay` logs.
- If `attempt_count` increases, inspect `last_error`.
- If Temporal cannot be reached, verify `ATLAS_TEMPORAL_ADDRESS`.
- In Docker Compose, the relay uses `temporal:7233`; outside Docker, use `localhost:7233`.
