# Milestone 11: Document Lifecycle Correctness

Milestone 11 makes document replacement and deletion safe for the MVP.
PostgreSQL remains authoritative; Neo4j and OpenSearch are treated as
retryable, rebuildable projections.

Implemented behavior:

- Document deletion is exposed at `DELETE /v1/documents/{document_id}`.
- Deleted documents mark live document versions as `deleted`.
- Deleted documents also receive a logical document tombstone (`deleted_at`),
  so future ingestion jobs cannot create replacement versions for a deleted
  logical document.
- Activating a replacement version marks the previous active version
  `superseded`.
- Deletion and replacement create durable lifecycle records in
  `document_lifecycle_events`.
- Every recorded retrieval index coverage identity for stale versions creates
  durable cleanup records in `document_projection_cleanups`, including partial,
  failed and cancelled attempts with zero recorded counters.
- Cleanup status is inspectable through
  `GET /v1/documents/{document_id}/projection-cleanups`.
- Failed or pending cleanup can be requeued through
  `POST /v1/documents/{document_id}/projection-cleanups/retry`.
- The `projection-cleanup` compose service drains pending cleanup rows, deletes
  stale OpenSearch chunk documents and Neo4j chunk vector nodes, invalidates
  graph relationship provenance for the stale version, and reconciles the tenant
  graph projection.
- Primitive lexical/vector search and query streaming filter projection hits
  against active PostgreSQL document versions, so stale projection rows cannot
  be packed or cited while cleanup is pending.
- Context packing revalidates chunk candidates and graph relationship
  candidates against active PostgreSQL document-version support, closing the
  delete-after-retrieval race.
- Citation provenance for old query runs remains inspectable and includes the
  current source document/document-version status plus an active/inactive flag.
- Staged graph relationship rebuilds only use accepted staged evidence from
  active document versions, so later rebuilds cannot reintroduce deleted or
  superseded evidence.
- Indexing plan, begin, batch, and completion paths reject deleted or otherwise
  terminal document versions; late failure callbacks leave cancelled coverage
  untouched.
- Search readiness ignores deleted and superseded versions.
- The frontend Documents page exposes document deletion, cleanup status, and
  cleanup retry controls.

Operational notes:

- Projection cleanup is intentionally idempotent. If OpenSearch or Neo4j cleanup
  fails, the row remains `failed` with error details and can be retried.
- Existing query-run provenance remains inspectable from PostgreSQL after a
  source document is deleted; new queries cannot use deleted or superseded chunk
  projections.
- Raw object hard deletion is still out of scope.

## Interrupted indexing cleanup

[Issue #67](https://github.com/mohripan/flint-graph/issues/67) extends cleanup to
partial attempts and guards projection replay with Document-first lifecycle locks.
Running coverage is cancelled on deletion or supersession. Cleanup targets all
persisted chunk identities rather than trusting incomplete batch counters;
reported cleanup counts are target counts, not measured physical deletions.
Completed-coverage reconciliation selects only active, non-deleted sources and
direct stale-source replay fails before writing. See the
[verification report](../reports/2026-10-10-partial-projection-cleanup.md) and
[runbook](../runbooks/partial-projection-cleanup.md).
