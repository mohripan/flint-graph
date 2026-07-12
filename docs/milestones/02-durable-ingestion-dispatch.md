# Milestone 02: Durable ingestion dispatch

## Phase 1 outcome

Queued ingestion jobs now create a transactional outbox message in the same database transaction as the document version, ingestion job, and initial `job.queued` event.

This phase does not start Temporal workflows yet. It establishes the durable handoff record that a later outbox relay will poll and publish.

## Transaction boundary

The API request transaction now contains:

1. Create the immutable document version.
2. Create the ingestion job.
3. Append the `job.queued` event.
4. Insert one `outbox_messages` row with topic `ingestion.job_queued`.

If any step fails, the whole transaction rolls back. A queued job should therefore never exist without the corresponding durable dispatch intent.

Idempotent job replay still returns the existing job and does not append a second outbox message.

## Outbox contract

The initial outbox message uses:

- `topic`: `ingestion.job_queued`
- `aggregate_type`: `ingestion_job`
- `aggregate_id`: the ingestion job ID
- `tenant_id`: the tenant that owns the job
- `status`: `pending`
- `attempt_count`: `0`

The payload contains string IDs so it can cross process boundaries safely:

- `tenant_id`
- `document_id`
- `document_version_id`
- `ingestion_job_id`
- `idempotency_key`
- `source_type`
- `source_uri`
- `trace_context`

The same trace context is also stored in `headers`. Later relay and worker phases will use these headers to continue traces across process boundaries.

## Schema

`outbox_messages` includes fields needed by the relay phase:

- publish topic and aggregate identity
- JSON payload and headers
- message status
- attempt count
- availability time
- lock owner and lock time
- publish time
- last error
- timestamps

Indexes are present for pending-message polling and aggregate lookup.

## Phase 3 outcome

The outbox relay can now safely move pending outbox messages to Temporal.

The relay:

- Polls pending `ingestion.job_queued` messages.
- Locks each selected message with a relay ID.
- Starts a Temporal workflow with deterministic workflow ID `ingestion-job-{job_id}`.
- Uses the configured Temporal task queue.
- Marks the message `published` only after workflow start returns successfully.
- Skips already-published messages on later relay passes.
- Records failure details for retry by incrementing `attempt_count`, clearing the lock, storing `last_error`, and delaying `available_at`.

Temporal is behind a small workflow-starter interface. Tests use a fake starter, while local runtime uses the real Temporal Python SDK client.

Local Docker Compose now includes:

- `temporal`: Temporal development server on `localhost:7233` with Web UI on `localhost:8233`
- `outbox-relay`: long-running relay process

## Phase 4 outcome

Temporal can now execute the stub ingestion workflow.

`IngestDocumentWorkflow`:

1. Runs `mark_ingestion_job_running`.
2. Runs `run_stub_ingestion`.
3. Runs `mark_ingestion_job_completed`.
4. If stub ingestion fails, runs `mark_ingestion_job_failed` and re-raises the workflow failure.

The workflow invokes activities by name so workflow code does not import database modules. Activity implementations own all database writes and call the explicit job-transition service from Phase 2.

The worker process runs:

```powershell
uv run python -m atlas_rag.processes.ingestion_worker
```

Docker Compose now includes `ingestion-worker` on the same `ingestion` Temporal task queue as the relay.

## Current limitations

- Retry behavior is only implemented for repeated job-state transition activity calls.
- Object-storage access remains a contract only; the worker does not read content yet.
- Ingestion is a stub; parsing, chunking, embedding, indexing, and graph writes are not implemented.

## Phase 5 outcome

Cancellation and trace propagation are now explicit.

Cancellation behavior:

- `POST /v1/ingestion-jobs/{job_id}/cancel` transitions a tenant-scoped queued or running job to `cancelled`.
- Cancellation appends an `ingestion.job_cancelled` outbox message in the same request transaction.
- The outbox relay cancels the deterministic Temporal workflow execution for that job.
- Foreign jobs still return not found.
- Completed and failed jobs cannot be cancelled.
- Repeated cancellation of an already-cancelled job is an idempotent no-op through the transition service.
- If a Temporal workflow receives a cancellation while running, it schedules `mark_ingestion_job_cancelled` before re-raising the cancellation.

Trace propagation behavior:

- The API captures W3C trace context when it creates the outbox message.
- The relay passes outbox headers to the Temporal starter.
- The Temporal starter stores the trace context in workflow memo as `trace_context`.

Temporal Python does not automatically continue spans from workflow memo into worker activities in this implementation. The memo preserves correlation data for inspection and for a future interceptor-based propagation pass.

## Phase 2 outcome

Job status changes now go through an explicit transition service instead of ad hoc assignment.

`transition_ingestion_job`:

- Locks the tenant-scoped ingestion job row.
- Returns 404-style `NotFoundError` for foreign or missing jobs.
- Validates transitions through the domain transition rules.
- Rejects invalid transitions with `ConflictError`.
- Updates `started_at` when a job enters `running`.
- Updates `completed_at` when a job enters a terminal state.
- Stores error code and message when a job enters `failed`.
- Appends a job event in the same transaction as the status update.
- Treats repeated attempts to apply the already-current status as idempotent no-ops.

That idempotent no-op is intentionally narrow. It exists so a retried workflow activity can safely repeat a transition that already committed. It does not allow moving a terminal job back to an earlier state.

## Verification

Phase 1 is covered by integration tests that prove:

- Creating a new ingestion job appends exactly one outbox message.
- Replaying the same idempotency key returns the same job and does not append another outbox message.
- The existing vertical slice still works with the extra transactional write.

Phase 2 is covered by integration tests that prove:

- A valid transition updates job state and appends an event.
- Repeating the same transition is idempotent and does not append a duplicate event.
- Invalid transitions are rejected.
- Failed transitions set terminal error fields.
- Tenant boundaries are preserved for transition attempts.

Phase 3 is covered by integration tests that prove:

- Pending outbox messages are started as Temporal workflows and marked published.
- Already-published messages are skipped by later relay passes.
- Failed workflow starts leave the message pending and record retry state.

Phase 4 is covered by tests that prove:

- The workflow schedules the running, stub ingestion, and completed activities in order.
- The workflow schedules the failed transition activity if stub ingestion fails.
- Activity helpers move jobs to `running`, `completed`, and `failed` through the transition service.

Phase 5 is covered by tests that prove:

- The cancel endpoint moves queued jobs to `cancelled` and appends `job.cancelled`.
- Cancellation writes a durable cancellation outbox message.
- The relay publishes cancellation messages by calling Temporal workflow cancellation.
- Tenant boundaries are preserved for cancellation.
- Completed jobs cannot be cancelled.
- Workflow cancellation schedules the cancellation transition activity.
- Trace context is preserved in the Temporal workflow memo.

Useful commands:

```powershell
uv run pytest tests\integration\test_outbox.py
uv run pytest tests\integration\test_outbox_relay.py
uv run pytest tests\integration\test_ingestion_activities.py
uv run pytest tests\integration\test_job_cancellation.py
uv run pytest tests\integration\test_job_transitions.py
uv run pytest tests\unit\test_ingestion_workflow.py
uv run pytest tests\unit\test_temporal_adapter.py
uv run pytest tests\integration\test_vertical_slice.py
uv run pytest tests\unit
uv run ruff check .
uv run mypy
uv run pytest
```
