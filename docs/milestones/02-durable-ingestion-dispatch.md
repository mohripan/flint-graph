# Milestone 02: Durable ingestion dispatch

## Outcome

Queued ingestion jobs now leave the API process through a transactional outbox, an outbox relay, a Temporal workflow, and an ingestion worker.

The worker still performs stub ingestion only. This milestone proves the durable dispatch path, explicit job-state transitions, retry recording, cancellation plumbing, and trace correlation boundary before real document parsing is added.

Implemented flow:

```text
API transaction
    -> document version
    -> ingestion job
    -> job.queued event
    -> outbox message
    -> outbox relay
    -> Temporal workflow
    -> ingestion worker
    -> job.started/job.completed or job.failed/job.cancelled
```

## Transaction Boundary

The API request transaction for a new ingestion job contains:

1. Create the immutable document version.
2. Create the ingestion job.
3. Append the `job.queued` event.
4. Insert one `outbox_messages` row with topic `ingestion.job_queued`.

If any step fails, the whole transaction rolls back. A queued job should therefore never exist without a durable dispatch record.

Idempotent job replay returns the existing job and does not append a second outbox message.

## Outbox Messages

Implemented topics:

- `ingestion.job_queued`: starts a Temporal ingestion workflow.
- `ingestion.job_cancelled`: cancels the deterministic Temporal workflow for the job.

Outbox messages store:

- `topic`
- `aggregate_type`
- `aggregate_id`
- `tenant_id`
- JSON `payload`
- JSON `headers`
- `status`
- `attempt_count`
- `available_at`
- `locked_at`
- `locked_by`
- `published_at`
- `last_error`
- timestamps

Payload IDs are serialized as strings so messages can cross process boundaries safely. W3C trace context is stored in both payload and headers.

## Relay Semantics

The outbox relay:

- Polls pending supported topics.
- Locks selected rows with a relay ID.
- Starts or cancels Temporal workflows using deterministic workflow ID `ingestion-job-{job_id}`.
- Marks messages `published` only after Temporal accepts the operation.
- Skips already-published messages on later passes.
- On publish failure, leaves the message `pending`, increments `attempt_count`, clears lock fields, records `last_error`, and delays `available_at`.

## Temporal And Worker

Temporal integration includes:

- Temporal client factory.
- Outbox relay process.
- Ingestion worker process.
- `IngestDocumentWorkflow`.
- Activities for job transitions and stub ingestion.

Workflow code invokes activities by name and does not import database infrastructure. Database writes happen in activities through application services.

The workflow:

1. Runs `mark_ingestion_job_running`.
2. Runs `run_stub_ingestion`.
3. Runs `mark_ingestion_job_completed`.
4. On non-cancellation failure, runs `mark_ingestion_job_failed` and re-raises.
5. On cancellation, runs `mark_ingestion_job_cancelled` and re-raises.

## Job-State Transitions

Job status changes go through `transition_ingestion_job`.

The transition service:

- Locks the tenant-scoped job row.
- Returns `NotFoundError` for missing or foreign jobs.
- Validates transitions through domain rules.
- Rejects invalid transitions with `ConflictError`.
- Sets `started_at`, `completed_at`, and error fields consistently.
- Appends an event in the same transaction as the status update.
- Treats repeated attempts to apply the already-current status as idempotent no-ops.

That idempotent no-op is intentionally narrow. It supports retried workflow activities after a committed transition. It does not allow moving a terminal job backward.

## Cancellation

`POST /v1/ingestion-jobs/{job_id}/cancel`:

- Transitions a tenant-scoped queued or running job to `cancelled`.
- Appends `job.cancelled`.
- Writes an `ingestion.job_cancelled` outbox message in the same request transaction.
- Causes the relay to send a Temporal workflow cancellation request for `ingestion-job-{job_id}`.
- Returns not found for foreign jobs.
- Rejects completed or failed jobs.

## Trace Correlation

The API captures W3C trace context when it writes the outbox message. The relay passes outbox headers to the Temporal starter. The Temporal starter stores those headers in workflow memo as `trace_context`.

Temporal Python does not automatically continue spans from workflow memo into worker activities in this implementation. The memo preserves correlation data for inspection and future interceptor-based propagation.

## Object Storage

Object storage is a contract only in this milestone. The worker does not read `document_versions.object_uri`, compute `content_hash`, parse content, create chunks, write embeddings, or mutate a graph.

The contract is documented in `docs/architecture/object-storage-contract.md`.

## Local Processes

Docker Compose includes:

- `api`
- `migrate`
- `postgres`
- `temporal`
- `outbox-relay`
- `ingestion-worker`
- `observability`

Manual process commands:

```powershell
uv run uvicorn atlas_rag.main:app --reload
uv run python -m atlas_rag.processes.outbox_relay
uv run python -m atlas_rag.processes.ingestion_worker
```

## Verification

Automated tests cover:

- Atomic outbox creation with new ingestion jobs.
- Idempotent job replay without duplicate outbox messages.
- Outbox relay workflow start, cancellation, retry recording, and publish marking.
- Explicit job transitions, invalid transitions, terminal behavior, and tenant boundaries.
- Workflow activity ordering for success, failure, and cancellation paths.
- Activity helpers moving jobs to `running`, `completed`, `failed`, and `cancelled`.
- Cancellation endpoint behavior and cancellation outbox creation.
- Trace context preservation in Temporal workflow memo.
- Existing tenant/document/job vertical slice.

Useful commands:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

## Remaining Gaps

- Ingestion is still a stub.
- Object storage is not implemented.
- PostgreSQL concurrency tests for row locking are still missing.
- Automatic OpenTelemetry span continuation across Temporal workflow/activity execution is not implemented.
