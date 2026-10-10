# Deletion during ingestion

Deleting a document now settles queued/running ingestion jobs and writes their
durable cancellation dispatch atomically. Late completion/failure callbacks do
not reactivate deleted versions or overturn an already-cancelled deleted job.
Readiness/retrieval continue to exclude deleted content. See [ADR 20](../adr/0020-document-first-lifecycle-locking.md).

For an old job stuck running under a deleted document:

1. Verify the authorized workspace, exact document/version/job IDs and committed
   deletion marker using API inspection and the authoritative ledger.
2. An authorized caller can use `POST /v1/ingestion-jobs/{id}/cancel` under that
   workspace. This settles the job and dispatches cancellation, without restoring
   document content. Do not change PostgreSQL statuses manually.
3. Inspect job events for one cancellation outcome and inspect outbox publication
   / Temporal terminal state. The API job state and Temporal execution state are
   distinct inspection sources; a historically failed workflow is not restarted.
4. Check tenant readiness and source visibility. Raw data/provenance remain under
   existing retention policy. Partial physical projections are separate cleanup
   work (#67), not a reason to restore or reindex deleted content.

Deletion may wait for an in-progress document transaction, which currently can
include model calls. Treat lock duration and cancellation delivery as operations
metrics; immediate cancellation latency is not guaranteed. Do not stop shared
workers, delete volumes or reupload a private source to diagnose this condition.
Queued starts and cancellations remain dispatched by the existing outbox relay.

The regression suite exercises both automatic-flush modes because the production
session factory disables autoflush. SQLite cannot prove lock ordering: run the
PostgreSQL-enabled lifecycle tests for stale-session/concurrent-row-lock checks.
Live tests should use new synthetic workspaces and logical deletion only, never
the user's already-deleted private document.
