# Partial retrieval projection cleanup

Deletion and supersession schedule one durable cleanup per recorded
tenant/document/version/index/stale-reason identity. Failed, cancelled and running
coverage can have external records even when PostgreSQL counters are zero. Cleanup
therefore targets every stored chunk ID for that version/index, not a counter-sized
prefix. Running coverage is cancelled under the owning Document lock.

1. Inspect the exact authorized document's
   `GET /v1/documents/{id}/projection-cleanups` records.
2. Ensure the `projection-cleanup` service is running. It drains pending records.
   Failed records require an explicit admin/owner retry through
   `POST /v1/documents/{id}/projection-cleanups/retry`.
3. Inspect persisted cleanup status and bounded errors. Partial OpenSearch bulk
   failures are failures even with HTTP 200; already-missing deletes are safe.
4. Verify exact physical tenant/version/index identities in Neo4j/OpenSearch when
   checking retention. Cleanup counts describe attempted targets, not actual
   physical deletions. Authoritative retrieval filters exclude stale sources
   while physical cleanup is pending.

Do not repair by reindexing a tombstone. Reconciliation now rejects deleted or
superseded sources before external writes and holds the lifecycle lock throughout
publication. A concurrent change after scanner selection fails the replay; inspect
the failure and rerun the scanner against current active state.

This deployment does not automatically discover historical partial attempts
already deleted/superseded before the fix. For legacy records, inspect precise
identities and schedule an authorized scoped repair; do not reset global coverage,
restore a private source, drop indexes or delete volumes. Raw objects and historical
provenance remain retained. Records never represented in authoritative coverage
are outside this cleanup contract.

## Verification

Offline lifecycle tests exercise every coverage status, zero counters, all-chunk
targeting, retries and completed no-op behavior. PostgreSQL tests prove concurrent
replay cannot overtake committed deletion/supersession. Opt-in live tests use only
fresh fixture schemas, UUID-named synthetic OpenSearch indexes and UUID-scoped
Neo4j nodes:

```powershell
$env:FLINT_GRAPH_PG_INTEGRATION='1'
$env:FLINT_GRAPH_LIVE_PROJECTION_INTEGRATION='1'
uv run pytest tests/integration/test_document_version_lifecycle.py -k partial_projection_cleanup_live -q
```

The fixture removes its own temporary database schema and synthetic projections;
it does not modify project/public/private corpus records or make model calls.
