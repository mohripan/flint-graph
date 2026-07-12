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

## Current limitations

- No relay polls or publishes outbox messages yet.
- No Temporal client, workflow, or worker exists yet.
- Retry behavior is only implemented for repeated job-state transition activity calls.
- Cancellation behavior is not active yet.
- Object-storage access remains a contract only; no worker reads content yet.

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

Useful commands:

```powershell
uv run pytest tests\integration\test_outbox.py
uv run pytest tests\integration\test_job_transitions.py
uv run pytest tests\integration\test_vertical_slice.py
uv run pytest tests\unit
uv run ruff check .
uv run mypy
uv run pytest
```
