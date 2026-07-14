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

## OpenSearch Checks

List indexes and aliases:

```powershell
curl.exe -sS http://localhost:9200/_cat/indices?v
curl.exe -sS http://localhost:9200/_cat/aliases?v
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

Check vector-bearing retrieval records:

```powershell
docker compose exec neo4j cypher-shell -u neo4j -p atlaspassword "MATCH (c {tenant_id: '<tenant-id>'}) WHERE c.chunk_id IS NOT NULL RETURN labels(c), c.chunk_id, keys(c) LIMIT 20"
```

## API Checks

After implementation, expected primitive checks:

```powershell
curl.exe -sS http://localhost:8000/v1/index-versions -H "X-Tenant-ID: <tenant-id>"
curl.exe -sS http://localhost:8000/v1/index-coverage -H "X-Tenant-ID: <tenant-id>"
```

Lexical search:

```powershell
curl.exe -sS -X POST http://localhost:8000/v1/search/lexical `
  -H "X-Tenant-ID: <tenant-id>" -H "Content-Type: application/json" `
  -d '{"query":"acme","limit":5}'
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
