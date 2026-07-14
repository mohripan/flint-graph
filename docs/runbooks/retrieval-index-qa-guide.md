# Retrieval Index QA Guide

## Status

Planned for Milestone 06. This guide describes the intended manual validation
flow once retrieval indexing is implemented.

## Audience

This guide is for QA, project managers, and semi-technical users who can run
Docker and PowerShell commands.

## Local Services

Start the application:

```powershell
docker compose up --build
```

Useful pages:

- API docs: `http://localhost:8000/docs`
- Temporal Web UI: `http://localhost:8233`
- Neo4j browser: `http://localhost:7474`
- OpenSearch: `http://localhost:9200`
- Grafana: `http://localhost:3000`

## Scenario: Index A Document

Create a tenant:

```powershell
$tenant = curl.exe -sS -X POST http://localhost:8000/v1/tenants `
  -H "Content-Type: application/json" `
  -d '{"name":"QA Retrieval Indexes"}' | ConvertFrom-Json
```

Create a small Markdown document:

```powershell
@"
# Acme Corporation

Acme Corporation is headquartered in Berlin.
Jane Doe founded Acme Corporation in 2020.
The Berlin office leads graph retrieval research.
"@ | Set-Content -Encoding utf8 .\retrieval-acme.md
```

Upload it:

```powershell
$upload = curl.exe -sS -X POST http://localhost:8000/v1/documents/uploads `
  -H "X-Tenant-ID: $($tenant.id)" -H "Idempotency-Key: qa-retrieval-acme" `
  -F "title=Retrieval Acme" -F "external_id=qa-retrieval-acme" `
  -F "file=@retrieval-acme.md;type=text/markdown" | ConvertFrom-Json
```

Poll the ingestion job:

```powershell
curl.exe -sS "http://localhost:8000/v1/ingestion-jobs/$($upload.ingestion_job_id)" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Expected after Milestone 06 implementation:

- ingestion reaches `completed`;
- an indexing workflow runs for the document version;
- index coverage reports the document version as indexed for the active version;
- lexical search finds the document by exact terms;
- vector search finds semantically related chunks;
- graph neighborhood traversal works for resolved entities.

## Inspect Index State

List index versions:

```powershell
curl.exe -sS http://localhost:8000/v1/index-versions `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Expected:

- one active retrieval index version is visible;
- provider, model, dimension, OpenSearch index, and Neo4j vector index metadata
  are present.

Check coverage:

```powershell
curl.exe -sS "http://localhost:8000/v1/index-coverage?document_version_id=$($upload.document_version_id)" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Expected:

- the uploaded document version has chunk coverage for the active index version;
- failures, if any, include bounded error details.

## Lexical Search

```powershell
curl.exe -sS -X POST http://localhost:8000/v1/search/lexical `
  -H "X-Tenant-ID: $($tenant.id)" -H "Content-Type: application/json" `
  -d '{"query":"Berlin office","limit":5}' | ConvertFrom-Json
```

Expected:

- results belong only to the tenant;
- the uploaded document appears;
- returned records include chunk ID, score, text preview or text, document
  metadata, heading path, and page fields when available.

## Vector Search

```powershell
curl.exe -sS -X POST http://localhost:8000/v1/search/vector `
  -H "X-Tenant-ID: $($tenant.id)" -H "Content-Type: application/json" `
  -d '{"query":"Which office handles graph retrieval?","limit":5}' | ConvertFrom-Json
```

Expected:

- results belong only to the tenant;
- semantically related chunks from the uploaded document rank near the top;
- returned records include chunk ID, score, index version, and document metadata.

## Graph Neighborhood

Fetch entities:

```powershell
$entities = curl.exe -sS http://localhost:8000/v1/entities `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Traverse one entity:

```powershell
curl.exe -sS "http://localhost:8000/v1/entities/$($entities[0].id)/neighborhood?depth=1&limit=25" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Expected:

- returned nodes and relationships belong only to the tenant;
- depth and limit parameters bound the response;
- relationship predicates and support counts are visible.

## Backfill

Start a scoped backfill:

```powershell
$backfill = curl.exe -sS -X POST http://localhost:8000/v1/index-backfills `
  -H "X-Tenant-ID: $($tenant.id)" -H "Content-Type: application/json" `
  -d "{\"document_version_id\":\"$($upload.document_version_id)\"}" | ConvertFrom-Json
```

Poll it:

```powershell
curl.exe -sS "http://localhost:8000/v1/index-backfills/$($backfill.id)" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Expected:

- re-running the backfill is idempotent;
- processed counts do not create duplicate embeddings or duplicate
  OpenSearch/Neo4j projection records.

## Negative Checks

- Search with a different tenant ID must not return the uploaded document.
- Vector search with an unknown index version should fail validation or return a
  clear not-found response.
- Metadata filters should narrow results, not widen them.
- Disabling OpenSearch or Neo4j should leave coverage incomplete and retryable,
  not corrupt PostgreSQL index state.

## Clean Reset

```powershell
docker compose down -v
```
