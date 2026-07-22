# Provenance Extraction QA Guide

## Status

Milestone 05 is implemented. This guide describes manual validation for the
provenance-rich extraction path. Dedicated extraction inspection APIs are
deferred, so the inspection steps use PostgreSQL plus existing graph APIs.

## Audience

This guide is for QA, project managers, and other semi-technical users who can run Docker and PowerShell commands.

## Local Services

Start the application:

```powershell
docker compose up --build
```

The default local provider is Ollama. For repeatable smoke testing without a
model call, start the worker with:

```powershell
$env:FLINT_GRAPH_LLM_PROVIDER = "deterministic"
docker compose up -d --build ingestion-worker
```

Restore the default provider afterward:

```powershell
Remove-Item Env:\FLINT_GRAPH_LLM_PROVIDER -ErrorAction SilentlyContinue
docker compose up -d --build ingestion-worker
```

Useful pages:

- API docs: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`
- Temporal Web UI: `http://localhost:8233`
- Neo4j browser: `http://localhost:7474`

## Scenario: Evidence-Backed Extraction

Create a tenant:

```powershell
$tenant = curl.exe -sS -X POST http://localhost:8000/v1/tenants `
  -H "Content-Type: application/json" `
  -d '{"name":"QA Provenance Extraction"}' | ConvertFrom-Json
```

Create a small Markdown document:

```powershell
@"
# Acme Corporation

Acme Corporation is headquartered in Berlin.
Jane Doe founded Acme Corporation in 2020.
"@ | Set-Content -Encoding utf8 .\provenance-acme.md
```

Upload it:

```powershell
$upload = curl.exe -sS -X POST http://localhost:8000/v1/documents/uploads `
  -H "X-Tenant-ID: $($tenant.id)" -H "Idempotency-Key: qa-provenance-acme" `
  -F "title=Provenance Acme" -F "external_id=qa-provenance-acme" `
  -F "file=@provenance-acme.md;type=text/markdown" | ConvertFrom-Json
```

Poll the job:

```powershell
curl.exe -sS "http://localhost:8000/v1/ingestion-jobs/$($upload.ingestion_job_id)" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Expected:

- the ingestion job reaches `completed`;
- extraction run records are visible in PostgreSQL;
- staged entities, relations, or claims have verified evidence spans;
- canonical graph records are created only after staged proposals are validated and resolved.

## What To Inspect

Extraction runs should show provider, model, schema, status, counts, warnings, and errors:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select id, status, model_provider, model_name, accepted_entity_count, accepted_relation_count, accepted_claim_count, errors from extraction_runs where document_version_id = '$($upload.document_version_id)' order by created_at desc;"
```

Provider invocations should show request/response hashes, latency, and input/output sizes:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select status, request_hash, response_hash, latency_ms, input_char_count, output_char_count, error_message from extraction_invocations where extraction_run_id in (select id from extraction_runs where document_version_id = '$($upload.document_version_id)') order by created_at;"
```

Evidence spans should show:

- chunk ID;
- exact offsets;
- span hash;
- a quote that appears verbatim in the stored chunk text.

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select chunk_id, start_offset, end_offset, span_hash from evidence_spans where document_version_id = '$($upload.document_version_id)' order by created_at;"
```

Candidate records should show:

- the staged entity being evaluated;
- the candidate target;
- score;
- reasons or feature vector;
- status.

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select source_extracted_entity_id, target_kind, score, outcome, status, reasons from entity_resolution_candidates where document_version_id = '$($upload.document_version_id)' order by created_at;"
```

Canonical entities and Neo4j projection should reflect accepted/resolved staged proposals, not raw model output.

```powershell
curl.exe -sS "http://localhost:8000/v1/entities" -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
docker compose exec neo4j cypher-shell -u neo4j -p flintgraphpassword "MATCH (e:Entity {tenant_id: '$($tenant.id)'}) RETURN properties(e)"
```

## Negative Checks

Automated tests cover:

- a quote absent from the chunk is rejected;
- repeated quotes without a valid start hint are rejected;
- unknown entity references are rejected;
- duplicate local IDs are rejected;
- tenant isolation on existing graph endpoints.

Dedicated extraction inspection endpoints are not available yet, so
foreign-tenant extraction inspection 404s are a post-milestone API-hardening
item rather than a QA check for this milestone.

## Clean Reset

```powershell
docker compose down -v
```
