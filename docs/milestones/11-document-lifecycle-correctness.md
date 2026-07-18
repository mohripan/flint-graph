# Milestone 11: Document Lifecycle Correctness

Milestone 11 makes document replacement and deletion safe for the MVP.
PostgreSQL remains authoritative; Neo4j and OpenSearch are treated as
retryable, rebuildable projections.

Implemented behavior:

- Document deletion is exposed at `DELETE /v1/documents/{document_id}`.
- Deleted documents mark live document versions as `deleted`.
- Activating a replacement version marks the previous active version
  `superseded`.
- Deletion and replacement create durable lifecycle records in
  `document_lifecycle_events`.
- Completed retrieval index coverage for stale versions creates durable cleanup
  records in `document_projection_cleanups`.
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
