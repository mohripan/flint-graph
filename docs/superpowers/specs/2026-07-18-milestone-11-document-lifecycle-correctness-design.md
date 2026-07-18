# Milestone 11 Document Lifecycle Correctness Design

## Status

Approved planning design. Locked direction: lifecycle ledger plus retryable
cleanup/reconcile workflows for document updates and deletes.

## Summary

Milestone 11 makes document replacement and deletion safe enough for MVP. After
Milestone 10, users can ingest local documents, wait for search readiness, and
ask citation-bearing questions. The remaining trust gap is lifecycle
correctness: changed or deleted content must not continue to appear in retrieval
results, context packs, citations, provenance, or graph projections.

The milestone adds a durable document lifecycle control plane:

```text
document update/delete request
    -> PostgreSQL lifecycle mutation record
    -> document/version status transition
    -> outbox cleanup message
    -> worker cleanup/reconcile workflow
    -> stale chunk projection removal
    -> graph evidence invalidation
    -> tenant graph projection reconcile
    -> inspectable cleanup status
```

PostgreSQL remains authoritative. Neo4j and OpenSearch continue to be
idempotent, rebuildable projections. The API records intent and durable state;
background workers perform projection cleanup and graph reconciliation.

## Goals

- Deleted documents are not queryable, citable, or shown as active sources.
- Superseded document versions stop contributing retrieval chunks and graph
  evidence after cleanup.
- Cleanup failures are visible and retryable.
- Reconcile commands can repair stale projections from PostgreSQL truth.
- Existing ingestion, indexing, query orchestration, and provenance contracts
  stay intact.

## Non-goals

- Fine-grained semantic diffing of changed sections.
- Partial chunk re-use across document versions.
- Restore from deleted state.
- Production authentication or authorization.
- Hard deletion of raw objects from object storage.

## Architecture

Milestone 11 introduces durable lifecycle mutations rather than direct
best-effort deletes. The mutation record is the durable bridge between document
state and cleanup work.

Recommended new PostgreSQL concepts:

- `document_lifecycle_events`:
  tenant, document, optional document version, event type, actor metadata,
  reason, payload, and monotonic creation time.
- `document_projection_cleanups`:
  tenant, document, document version, retrieval index version, cleanup status,
  counts, error details, attempt metadata, and timestamps.

The lifecycle event describes what changed. The cleanup record describes what
projection work remains or failed. Keeping them separate prevents a deleted
document from looking fully cleaned up before OpenSearch, Neo4j chunk vectors,
and graph evidence have converged.

Document versions continue using the existing status enum. `deleted` becomes an
active lifecycle state, not just an unused value. `superseded` remains the state
for prior active versions after a replacement succeeds.

## API Surface

Add:

```text
DELETE /v1/documents/{document_id}
GET    /v1/documents/{document_id}/lifecycle-events
GET    /v1/documents/{document_id}/projection-cleanups
POST   /v1/documents/{document_id}/projection-cleanups/retry
```

`DELETE /v1/documents/{document_id}` marks the logical document deleted and
creates cleanup work for every indexed version visible to the tenant. It should
return after the database transaction commits, not after projections are fully
cleaned.

Existing upload and from-URL endpoints already create new document versions.
Milestone 11 extends the activation path so when a new version becomes active,
the old active version receives cleanup work because it was superseded.

Tenant filtering remains mandatory on all reads and mutations. `X-Tenant-ID`
continues to be local tenant routing, not authentication.

## Data Flow

### Replacement

1. User uploads a new version for an existing document.
2. Ingestion completes and activates the new version.
3. The previous active version is marked `superseded`.
4. A lifecycle event records the version replacement.
5. Cleanup records are created for the superseded version across completed
   retrieval index coverages.
6. The cleanup worker removes stale chunk projections and invalidates graph
   evidence sourced only from the superseded version.
7. Search readiness and retrieval consider only active versions.

### Deletion

1. User calls `DELETE /v1/documents/{document_id}`.
2. The document is marked deleted through its active versions and lifecycle
   event records.
3. Pending/running ingestion and indexing work for that document is cancelled
   where possible, or made harmless through active-version checks before write.
4. Cleanup records are created for all completed projection coverage rows.
5. The cleanup worker deletes OpenSearch chunk records and Neo4j chunk vector
   nodes for those document versions.
6. Graph evidence from deleted versions is removed or marked inactive.
7. Tenant graph projection is reconciled.
8. Query APIs and provenance APIs no longer expose deleted content as active
   evidence.

## Projection Cleanup

OpenSearch cleanup uses the existing bulk delete document format, extended with
a service that loads the stale `DocumentChunk` rows for a document version and
emits delete operations against the associated retrieval index version.

Neo4j chunk cleanup uses the existing `delete_chunk_vectors` helper. Cleanup
must target tenant, retrieval index version, document version, and chunk node
IDs so one tenant or index version cannot delete another.

PostgreSQL chunk, embedding, artifact, extraction, and provenance rows should
not be hard-deleted in Milestone 11. They are audit history and repair inputs.
Query-time services must filter inactive/deleted versions instead.

## Graph Invalidation

Graph invalidation should be evidence-driven:

- Staged extraction records from deleted or superseded versions are no longer
  eligible to support canonical graph facts.
- Canonical entities and relationships keep support from remaining active
  evidence.
- Relationships with no active support become deprecated or are removed from
  the active projection.
- Entity deprecation is limited to entities whose only active support came from
  deleted or superseded versions and that are not merge targets for remaining
  active evidence.

After invalidation, run the existing tenant graph projection reconcile so Neo4j
matches PostgreSQL active graph truth.

## Query and Retrieval Guardrails

Primitive retrieval, query retrieval, context packing, citation provenance, and
answer provenance must only treat active document versions as active sources.
Even if stale projection rows still exist temporarily, query services should
join or validate against PostgreSQL active-version state before packing context
records.

This guardrail is required because projection cleanup is asynchronous and can
fail temporarily. A deleted document should stop being answerable as soon as the
PostgreSQL delete transaction commits.

## Error Handling

Cleanup records use explicit states:

```text
pending -> running -> completed
pending/running -> failed
failed -> pending
running -> cancelled
```

Projection delete failures store provider, operation, retryable flag, error
code, and truncated message. Retrying cleanup is idempotent: deleting an already
deleted OpenSearch record or Neo4j chunk node is success.

If graph invalidation fails after chunk cleanup succeeds, the cleanup remains
failed until graph reconciliation succeeds. The UI must not present the document
as fully cleaned until all required cleanup steps are complete.

## Frontend

The Documents page should add:

- delete action with confirmation;
- deleted/superseded/cleanup-pending/cleanup-failed states;
- retry cleanup action for failed cleanup records;
- clear warning when a document is deleted but projection cleanup is still
  running.

The Ask page can keep using search readiness, but readiness should ignore
deleted documents and superseded versions.

## Testing

Minimum automated coverage:

- Deleting a document marks active versions deleted and creates lifecycle and
  cleanup records.
- Replacing a document supersedes the old active version and creates cleanup
  records for completed index coverage.
- Primitive lexical/vector retrieval excludes deleted and superseded versions,
  even if projection records still exist.
- Query context packs exclude deleted and superseded versions.
- Existing query provenance remains inspectable, but citations whose source
  document was deleted are marked with inactive/deleted source metadata. New
  queries must not pack or cite deleted content.
- Cleanup worker deletes stale OpenSearch and Neo4j chunk projections
  idempotently.
- Graph invalidation removes relationships with no active evidence and retains
  relationships with remaining active evidence.
- Retry endpoint requeues failed cleanup and does not duplicate completed work.
- Tenant-boundary tests cover delete, cleanup inspection, retry, retrieval, and
  provenance.

Manual Docker/Ollama smoke:

1. Start Compose and Ollama.
2. Create a tenant and compatible active retrieval index.
3. Upload a small markdown document and wait for searchable readiness.
4. Ask a question and verify the document can be cited.
5. Delete the document.
6. Verify readiness no longer counts it as searchable.
7. Verify the same question cannot cite deleted content.
8. Verify cleanup records complete and projections reconcile.
9. Upload a replacement version and verify old-version chunks are not cited.

Required gates:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run atlas-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
cd frontend
npm run build
```

## Acceptance Criteria

Milestone 11 is complete when:

- deleting a document immediately prevents future queries from using its
  content;
- replacing a document version prevents old-version chunks from being packed or
  cited;
- stale OpenSearch and Neo4j chunk projections are removed by retryable cleanup
  work;
- graph facts unsupported by active evidence are no longer active;
- lifecycle events and cleanup status are inspectable through APIs;
- failed cleanup is visible and retryable;
- reconcile commands can repair projections from PostgreSQL truth;
- all required automated gates and one Docker/Ollama lifecycle smoke pass.

## Deferred

- Fine-grained section diffing and partial re-embedding.
- Restore deleted documents.
- Object-store garbage collection.
- Multi-user authorization around delete permissions.
- Background durable query workflows.
- Production-grade retention policies.
