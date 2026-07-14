# Retrieval Index Developer Runbook

## Purpose

Use this runbook when implementing or debugging Milestone 06 retrieval indexes:
embedding generation, retrieval index versions, Neo4j vector projection,
OpenSearch lexical projection, primitive retrieval APIs, and backfills.

## Target Flow

```text
ingestion completes chunks and graph state
    -> indexing workflow starts
    -> load persisted chunks
    -> embed chunk batches
    -> persist chunk_embeddings
    -> project vectors to Neo4j
    -> upsert lexical records to OpenSearch
    -> mark index coverage
```

Backfill uses the same embedding and projection services against existing active
document versions.

## Local Services

Milestone 06 should add OpenSearch to Docker Compose alongside existing
services:

- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Temporal Web UI: `http://localhost:8233`
- Neo4j browser: `http://localhost:7474`
- OpenSearch: expected local port `9200`
- Grafana: `http://localhost:3000`

Start the stack:

```powershell
docker compose up --build
```

Reset local state:

```powershell
docker compose down -v
```

Useful logs:

```powershell
docker compose logs -f ingestion-worker
docker compose logs -f api
docker compose logs -f opensearch
```

## Phase 1 Configuration

Phase 1 adds the embedding contract and settings but does not start indexing.
Relevant environment variables use the `ATLAS_` prefix:

- `ATLAS_INDEXING_MODE`: `disabled`, `optional`, or `required`;
- `ATLAS_EMBEDDING_PROVIDER`: `deterministic`, `ollama`, or
  `openai_compatible`;
- `ATLAS_EMBEDDING_MODEL`;
- `ATLAS_EMBEDDING_DIMENSIONS`;
- `ATLAS_EMBEDDING_BATCH_SIZE`;
- `ATLAS_EMBEDDING_TIMEOUT_SECONDS`;
- `ATLAS_EMBEDDING_OLLAMA_BASE_URL`;
- `ATLAS_EMBEDDING_OPENAI_BASE_URL`;
- `ATLAS_EMBEDDING_OPENAI_API_KEY`;
- `ATLAS_ACTIVE_RETRIEVAL_INDEX_VERSION_ID`;
- `ATLAS_INDEX_BACKFILL_BATCH_SIZE`;
- `ATLAS_OPENSEARCH_URL`.

The default provider is deterministic so unit and local contract tests do not
require a live embedding service. `openai_compatible` requires both a base URL
and API key at settings validation time.

## Database Checks

Milestone 06 Phase 2 tables:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "\dt *retrieval*"
docker compose exec postgres psql -U atlas -d atlas -c "\dt *embedding*"
docker compose exec postgres psql -U atlas -d atlas -c "\dt *backfill*"
```

Index versions:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select id, status, embedding_provider, embedding_model, vector_dimension, lexical_schema_version, created_at from retrieval_index_versions order by created_at desc limit 20;"
```

Chunk embedding coverage:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select retrieval_index_version_id, tenant_id, count(*) from chunk_embeddings group by retrieval_index_version_id, tenant_id order by count desc;"
```

Backfill jobs:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select id, status, processed_count, failed_count, last_error from index_backfill_jobs order by created_at desc limit 20;"
```

Backfill checkpoints:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select id, status, total_count, processed_count, failed_count, checkpoint, last_error from index_backfill_jobs order by created_at desc limit 20;"
```

Document index coverage:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select document_version_id, retrieval_index_version_id, status, chunk_count, embedded_count, vector_count, lexical_count, error_code from document_index_coverages order by created_at desc limit 20;"
```

Active-version invariant:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select scope, tenant_id, count(*) from retrieval_index_versions where status = 'active' group by scope, tenant_id;"
```

Expected:

- at most one row with `scope = global` and `tenant_id` empty;
- at most one active row for each tenant.

Chunk embedding idempotency key:

```text
retrieval_index_version_id + document_version_id + chunk_id + chunk_hash
```

If a chunk hash changes, the old embedding remains tied to the old hash and
must not be reused for the new chunk.

## Indexing Workflow Checks

Phase 5 adds `IndexDocumentVersionWorkflow` and registers it in the ingestion
worker. The workflow is started by ingestion according to `ATLAS_INDEXING_MODE`:

- `disabled`: no indexing workflow starts;
- `optional`: ingestion completes, then the workflow starts as follow-up;
- `required`: ingestion waits for indexing before completing.

Temporal workflow IDs use:

```text
index-document-version-<document_version_id>-<retrieval_index_version_id>
```

In Temporal Web UI, inspect `http://localhost:8233` and search for
`IndexDocumentVersionWorkflow` after ingesting a document with an active
retrieval index version.

Required-mode failures happen before `job.completed`, so the ingestion job and
document version fail through the normal ingestion transition path. Optional
mode failures should leave ingestion completed and mark
`document_index_coverages.status = 'failed'`.

## Backfill And Reconcile Checks

Phase 6 adds `IndexBackfillWorkflow`. Backfill jobs are stored in
`index_backfill_jobs`. Phase 7 adds API creation and status endpoints.

Workflow name:

```text
IndexBackfillWorkflow
```

Backfill workflow payload:

```json
{"backfill_job_id":"<index_backfill_jobs.id>"}
```

Start a tenant-scoped backfill through the API:

```powershell
curl.exe -sS -X POST http://localhost:8000/v1/index-backfills `
  -H "X-Tenant-ID: <tenant-id>" -H "Content-Type: application/json" `
  -d '{"retrieval_index_version_id":"<index-version-id>"}'
```

Optional `document_id` and `document_version_id` fields narrow the backfill
scope. Foreign tenant documents, document versions, index versions, and jobs
return 404.

Backfill eligibility includes missing coverage, incomplete coverage,
count-mismatched coverage, and stale chunk hashes where current chunks do not
have matching `chunk_embeddings` rows for the target retrieval index version.

Reconcile completed retrieval projections without re-embedding:

```powershell
$env:ATLAS_DATABASE_URL='postgresql+asyncpg://atlas:atlas@localhost:55432/atlas'
$env:ATLAS_NEO4J_URI='bolt://localhost:7687'
$env:ATLAS_NEO4J_USER='neo4j'
$env:ATLAS_NEO4J_PASSWORD='atlaspassword'
$env:ATLAS_NEO4J_DATABASE='neo4j'
$env:ATLAS_OPENSEARCH_URL='http://localhost:9200'
uv run python -m atlas_rag.processes.retrieval_index_reconcile
```

Expected reconcile behavior:

- completed coverage rows are replayed to Neo4j and OpenSearch;
- embeddings are loaded from PostgreSQL `chunk_embeddings`;
- missing current embeddings fail reconcile and should be repaired by backfill;
- no embedding provider call is made.

## OpenSearch Checks

Phase 3 adds the local OpenSearch service and projection adapter. The service is
available at `http://localhost:9200` from the host and
`http://opensearch:9200` inside Compose.

List indexes and aliases:

```powershell
curl.exe -sS http://localhost:9200/_cat/indices?v
curl.exe -sS http://localhost:9200/_cat/aliases?v
```

Create a smoke-test index:

```powershell
curl.exe -sS -X PUT http://localhost:9200/atlas_chunks_smoke `
  -H "Content-Type: application/json" `
  -d '{"settings":{"index":{"number_of_shards":1,"number_of_replicas":0}},"mappings":{"properties":{"tenant_id":{"type":"keyword"},"text":{"type":"text"}}}}'
```

Run a tenant-filtered lexical smoke query:

```powershell
curl.exe -sS -X POST http://localhost:9200/atlas_chunks_active/_search `
  -H "Content-Type: application/json" `
  -d '{"query":{"bool":{"must":[{"match":{"text":"acme"}}],"filter":[{"term":{"tenant_id":"<tenant-id>"}}]}},"size":5}'
```

## Neo4j Checks

List Neo4j indexes:

```powershell
docker compose exec neo4j cypher-shell -u neo4j -p atlaspassword "SHOW INDEXES YIELD name, type, labelsOrTypes, properties RETURN name, type, labelsOrTypes, properties"
```

Expected Phase 4 indexes include:

- `chunk_id_unique`;
- `chunk_tenant_index_version`;
- `chunk_document_version`;
- `chunk_embedding_default`.

Check vector-bearing retrieval records:

```powershell
docker compose exec neo4j cypher-shell -u neo4j -p atlaspassword "MATCH (c:Chunk {tenant_id: '<tenant-id>'}) RETURN c.id, c.chunk_id, c.retrieval_index_version_id, keys(c) LIMIT 20"
```

## API Checks

Phase 7 primitive checks:

```powershell
curl.exe -sS http://localhost:8000/v1/index-versions -H "X-Tenant-ID: <tenant-id>"
curl.exe -sS http://localhost:8000/v1/index-coverage -H "X-Tenant-ID: <tenant-id>"
curl.exe -sS http://localhost:8000/v1/index-backfills/<job-id> -H "X-Tenant-ID: <tenant-id>"
```

Lexical search:

```powershell
curl.exe -sS -X POST http://localhost:8000/v1/search/lexical `
  -H "X-Tenant-ID: <tenant-id>" -H "Content-Type: application/json" `
  -d '{"query":"acme","limit":5,"filters":{"source_type":"upload"}}'
```

Vector search:

```powershell
curl.exe -sS -X POST http://localhost:8000/v1/search/vector `
  -H "X-Tenant-ID: <tenant-id>" -H "Content-Type: application/json" `
  -d '{"query":"where is acme headquartered","limit":5}'
```

Graph neighborhood:

```powershell
curl.exe -sS "http://localhost:8000/v1/entities/<entity-id>/neighborhood?depth=1&limit=25" `
  -H "X-Tenant-ID: <tenant-id>"
```

Search defaults to the tenant active retrieval index version, then the active
global version. Add `retrieval_index_version_id` to the search request body to
query an explicit active version visible to the tenant.

## Failure Modes

- Embedding provider timeout: record bounded error metadata; required indexing
  fails, optional indexing leaves coverage incomplete.
- Dimension mismatch: fail the index version or job; do not write mixed vectors
  under one version.
- OpenSearch unavailable: leave lexical projection incomplete and retry.
- Neo4j unavailable: leave vector projection incomplete and retry.
- Stale chunk hash: do not reuse old embeddings for the new chunk hash.
- Backfill interruption: resume from checkpoint.

## Verification Commands

Run before ending behavior-changing work:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

For phases touching live OpenSearch or Neo4j vector projection, also run gated
integration tests and record a Docker Compose smoke test in
`notes/milestone-06/02-manual-testing-retrieval-indexes.md`.
