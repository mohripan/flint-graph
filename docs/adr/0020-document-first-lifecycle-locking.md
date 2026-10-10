# ADR 0020: Document-first lifecycle locking

- Status: accepted; implemented for ingestion/version/index lifecycle mutations
- Date: 2026-10-10
- Issue: [#58](https://github.com/mohripan/flint-graph/issues/58)

## Decision

Take the authorized owning document's PostgreSQL row lock before locking or
mutating ingestion jobs, versions and index coverage. All participating paths
serialize on that first lock, avoiding job/coverage-first inversions with
deletion. Refresh locked ORM rows to observe other sessions' committed state.
Explicitly flush already-locked deletion markers before calling refreshing
transition helpers: runtime sessions use `autoflush=False`.

Deletion writes its tombstone, settles queued/running jobs as cancelled, appends
the cancellation event and durable dispatch in the same transaction. Repeated
cancellation reuses the existing outbox message. Late worker notifications for a
deleted cancelled job are no-ops; a legacy nonterminal job under a deleted
document can settle as cancelled without mutating a deleted version. Completed
jobs remain completed history, not retroactively cancelled.

Content persistence takes the document lock before derived-object writes and
foreign-key row locks. If deletion wins, the source/persistence guard refuses new
pipeline output. If persistence wins, deletion waits for that transaction before
tombstoning its committed result. Index/version/coverage mutations use the same
document-first order and refresh state before publication/completion. Raw-source
retention and historical provenance are unchanged.

## Consequences and limits

This intentionally serializes one document's mutations while preserving parallel
work across different documents. The current pipeline transaction can include
model IO, so deletion may wait for an ongoing content/model/index transaction.
This ADR does not claim instantaneous cancellation or a hard transaction-latency
bound. Transaction shortening and measured lock/queue/payload budgets coordinate
with [#63](https://github.com/mohripan/flint-graph/issues/63) and durable activity
boundaries in Milestone 18. Do not remove the lock without replacing the atomic
publication/deletion guard.

Logical deletion prevents authoritative retrieval; partial physical projection
cleanup remains [#67](https://github.com/mohripan/flint-graph/issues/67). Raw
objects and prior records are retained, not securely erased. Existing orphaned
jobs are not automatically repaired by this code deployment. Use authorized
public cancellation after verifying the precise deleted document/job identity;
never reactivate a deleted source to repair a job status.

Acceptance evidence covers queued/running deletion, late completion/failure,
repeated dispatch, runtime autoflush settings, stale PostgreSQL sessions and live
Temporal cancellation; see [the delivery report](../reports/2026-10-10-ingestion-deletion-race.md).
