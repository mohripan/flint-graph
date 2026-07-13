# Provenance Extraction QA Guide

## Status

Milestone 05 is planned. This guide describes the manual behavior expected once the milestone is implemented.

## Audience

This guide is for QA, project managers, and other semi-technical users who can run Docker and PowerShell commands.

## Local Services

Start the application:

```powershell
docker compose up --build
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
curl.exe -sS -X POST http://localhost:8000/v1/documents/uploads `
  -H "X-Tenant-ID: $($tenant.id)" -H "Idempotency-Key: qa-provenance-acme" `
  -F "title=Provenance Acme" -F "external_id=qa-provenance-acme" `
  -F "file=@provenance-acme.md;type=text/markdown"
```

Expected:

- the ingestion job reaches `completed`;
- extraction run records are visible;
- staged entities, relations, or claims have verified evidence spans;
- canonical graph records are created only after staged proposals are validated and resolved.

## What To Inspect

Extraction runs should show provider, model, schema, status, counts, warnings, and errors.

Evidence spans should show:

- chunk ID;
- exact offsets;
- span hash;
- a quote that appears verbatim in the stored chunk text.

Candidate records should show:

- the staged entity being evaluated;
- the candidate target;
- score;
- reasons or feature vector;
- status.

Canonical entities and Neo4j projection should reflect accepted/resolved staged proposals, not raw model output.

## Negative Checks

Use deterministic or test-provider fixtures to verify:

- a quote absent from the chunk is rejected;
- repeated quotes without a valid start hint are rejected;
- unknown entity references are rejected;
- duplicate local IDs are rejected;
- foreign-tenant document versions return 404 from inspection endpoints.

## Clean Reset

```powershell
docker compose down -v
```
