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
    -> real content pipeline activity
```

The current worker reads raw source objects, verifies hashes, parses, chunks, writes artifacts, records extraction provenance, and then completes or fails the job. The older metadata-first document endpoint remains for compatibility, but jobs created from that path do not have raw object materialization and are expected to fail in the real pipeline. Use upload or URL intake for successful content-pipeline runs.

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
- `ingestion-worker`: runs `IngestDocumentWorkflow` and the content pipeline activity
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
2. Upload a source file or create a document from URL with an `Idempotency-Key`.
3. Capture the returned ingestion job ID.
4. Confirm the API returns `queued`.
5. Confirm an `outbox_messages` row exists with status `pending`.
6. Let the relay run.
7. Confirm the outbox message changes to `published`.
8. Open Temporal Web UI and confirm a workflow with ID `ingestion-job-{job_id}` exists.
9. Let the worker run.
10. Confirm the job status changes to `completed`.
11. Fetch job events and confirm `job.queued`, `job.started`, and `job.completed`.

Example upload request:

```powershell
$tenant = curl -sS -X POST http://localhost:8000/v1/tenants `
  -H "Content-Type: application/json" `
  -d '{"name":"Runbook Tenant"}' | ConvertFrom-Json

@"
# Runbook Document

This file exercises durable dispatch through the real content pipeline.
"@ | Set-Content -Encoding utf8 .\runbook.md

$upload = curl -sS -X POST http://localhost:8000/v1/documents/uploads `
  -H "X-Tenant-ID: $($tenant.id)" `
  -H "Idempotency-Key: runbook-upload-1" `
  -F "title=Runbook Document" `
  -F "external_id=runbook-document" `
  -F "file=@runbook.md;type=text/markdown" | ConvertFrom-Json

curl -sS "http://localhost:8000/v1/ingestion-jobs/$($upload.ingestion_job_id)" `
  -H "X-Tenant-ID: $($tenant.id)"

curl -sS "http://localhost:8000/v1/ingestion-jobs/$($upload.ingestion_job_id)/events" `
  -H "X-Tenant-ID: $($tenant.id)"
```

## Cancellation

Cancel a queued or running job:

```powershell
curl -sS -X POST http://localhost:8000/v1/ingestion-jobs/<job-id>/cancel `
  -H "X-Tenant-ID: <tenant-id>"
```

Expected result:

- The job status becomes `cancelled`.
- A `job.cancelled` event is appended.
- An `ingestion.job_cancelled` outbox message is appended.
- The relay sends a Temporal workflow cancellation request for `ingestion-job-{job_id}`.
- Foreign tenant cancellation attempts return 404.
- Completed or failed jobs return conflict.

## Trace Correlation

The API stores W3C trace context in the outbox message headers. The relay passes those headers to Temporal, and the Temporal starter writes them into workflow memo as `trace_context`.

In Temporal Web UI, inspect the workflow memo to correlate a workflow execution back to the originating API trace. Automatic span continuation inside workflow and activity execution is not implemented yet.

## Troubleshooting

- If messages stay `pending`, check the `outbox-relay` logs.
- If `attempt_count` increases, inspect `last_error`.
- If Temporal cannot be reached, verify `ATLAS_TEMPORAL_ADDRESS`.
- In Docker Compose, the relay uses `temporal:7233`; outside Docker, use `localhost:7233`.
- If a workflow exists but the job remains `queued`, check `ingestion-worker` logs and verify it is using the `ingestion` task queue.
- If cancellation status changes but Temporal does not cancel, check for a pending `ingestion.job_cancelled` outbox message.
