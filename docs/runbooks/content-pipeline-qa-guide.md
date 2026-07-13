# Content Pipeline QA Guide

## Status

Planned for Milestone 03. The commands in this guide describe the intended manual acceptance path after the content pipeline is implemented. Some endpoints and tables do not exist yet.

## Audience

This guide is for QA, project managers, and other semi-technical users who can run Docker and PowerShell commands but do not need to understand the code internals.

The goal is to show:

- What action to perform.
- What should happen in the application.
- Which database tables should change.
- Which MinIO objects should appear.
- Which job events should prove the pipeline ran.

## Local Services

Start the application:

```powershell
docker compose up --build
```

Useful local pages:

- API docs: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`
- Temporal Web UI: `http://localhost:8233`
- Grafana: `http://localhost:3000`

Expected services:

- `api`: accepts uploads and URL intake.
- `postgres`: stores tenants, documents, versions, jobs, chunks, and provenance.
- `minio`: stores raw and derived content artifacts.
- `outbox-relay`: starts Temporal workflows from durable outbox messages.
- `temporal`: runs workflow orchestration.
- `ingestion-worker`: parses, chunks, extracts, and activates versions.

## Step 1: Create A Tenant

Run:

```powershell
$tenant = curl.exe -sS -X POST http://localhost:8000/v1/tenants `
  -H "Content-Type: application/json" `
  -d '{"name":"QA Content Pipeline"}' | ConvertFrom-Json

$tenant.id
```

What this does:

- Creates a tenant identity used to route later requests.

Database effect:

- Inserts one row into `tenants`.

Check:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select id, name, created_at from tenants order by created_at desc limit 5;"
```

## Step 2: Upload A Text File

Create a small test file:

```powershell
@"
# AtlasRAG QA Note

AtlasRAG stores raw source material, parses it, chunks it, and records lineage.
"@ | Set-Content -Encoding utf8 .\qa-note.md
```

Upload it:

```powershell
$upload = curl.exe -sS -X POST http://localhost:8000/v1/documents/uploads `
  -H "X-Tenant-ID: $($tenant.id)" `
  -H "Idempotency-Key: qa-upload-md-001" `
  -F "title=QA Markdown Upload" `
  -F "external_id=qa-upload-md-001" `
  -F "file=@qa-note.md;type=text/markdown" | ConvertFrom-Json

$upload
```

What this does:

- Sends a real file through the AtlasRAG API.
- The API writes the raw file to MinIO.
- The API creates a document, document version, ingestion job, job event, and outbox message.

Database effect:

- Inserts one row into `documents`.
- Inserts one row into `document_versions` with status `pending`.
- Inserts one row into `ingestion_jobs` with status `queued`.
- Inserts one `job.queued` row into `ingestion_job_events`.
- Inserts one `ingestion.job_queued` row into `outbox_messages`.

MinIO effect:

- Creates a raw source object under a tenant/document/version key.

Check the DB:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select id, title, source_type, source_uri from documents order by created_at desc limit 5;"
docker compose exec postgres psql -U atlas -d atlas -c "select id, document_id, status, content_hash, object_uri from document_versions order by created_at desc limit 5;"
docker compose exec postgres psql -U atlas -d atlas -c "select id, status, document_version_id from ingestion_jobs order by created_at desc limit 5;"
docker compose exec postgres psql -U atlas -d atlas -c "select topic, aggregate_id, status, attempt_count, last_error from outbox_messages order by created_at desc limit 5;"
```

## Step 3: Watch The Job Complete

Fetch the job:

```powershell
curl.exe -sS "http://localhost:8000/v1/ingestion-jobs/$($upload.ingestion_job_id)" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Fetch job events:

```powershell
curl.exe -sS "http://localhost:8000/v1/ingestion-jobs/$($upload.ingestion_job_id)/events" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Expected final status:

- Job status is `completed`.
- Document version status is `active`.
- Events include `job.queued`, `job.started`, and `job.completed`.

Database effect during worker processing:

- `outbox_messages.status` changes from `pending` to `published`.
- `ingestion_jobs.status` changes from `queued` to `running` to `completed`.
- `document_versions.status` changes from `pending` to `active`.
- `document_artifacts` receives normalized and chunk-manifest artifact rows.
- `document_chunks` receives one or more chunk lineage rows.
- Extraction provenance is inserted if extraction is enabled.

Check:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select id, status, started_at, completed_at, error_code, error_message from ingestion_jobs order by created_at desc limit 5;"
docker compose exec postgres psql -U atlas -d atlas -c "select id, status, content_hash, object_uri from document_versions order by created_at desc limit 5;"
docker compose exec postgres psql -U atlas -d atlas -c "select artifact_type, object_uri, content_hash, schema_version from document_artifacts order by created_at desc limit 10;"
docker compose exec postgres psql -U atlas -d atlas -c "select chunk_index, left(text, 80) as preview, heading_path, page_start, page_end from document_chunks order by created_at desc, chunk_index limit 10;"
```

## Step 4: Inspect Temporal

Open:

```text
http://localhost:8233/namespaces/default/workflows
```

Look for:

```text
ingestion-job-<job-id>
```

What this proves:

- The API did not run ingestion inline.
- The outbox relay dispatched the durable message.
- Temporal ran the ingestion workflow.
- The worker completed the content activities.

## Step 5: Inspect MinIO

Open:

```text
http://localhost:9001
```

Expected objects:

```text
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/raw/source
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/artifacts/normalized.json
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/artifacts/chunks.json
```

If extraction is enabled and succeeds or records a failure artifact:

```text
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/artifacts/extraction.json
```

What this proves:

- Raw input is immutable.
- Derived artifacts are separate from database rows.
- PostgreSQL stores searchable lineage, while MinIO stores full artifact payloads.

## Step 6: Test URL Intake

Run:

```powershell
$urlDoc = curl.exe -sS -X POST http://localhost:8000/v1/documents/from-url `
  -H "Content-Type: application/json" `
  -H "X-Tenant-ID: $($tenant.id)" `
  -H "Idempotency-Key: qa-url-html-001" `
  -d '{"title":"QA URL HTML","source_url":"https://example.org/","external_id":"qa-url-html-001"}' | ConvertFrom-Json
```

What this does:

- The API fetches URL bytes with controlled timeout and size limits.
- The API stores those bytes as an immutable raw object.
- The same ingestion pipeline processes the materialized object.

Expected result:

- Same table changes as upload intake.
- Raw object appears in MinIO.
- HTML parser produces a normalized artifact.
- Chunk rows appear in `document_chunks`.

## Step 7: Test Optional Extraction Failure

Set extraction optional and point Ollama to an unavailable host, then restart the API and worker:

```env
ATLAS_EXTRACTION_ENABLED=true
ATLAS_EXTRACTION_MODE=optional
ATLAS_OLLAMA_BASE_URL=http://host.docker.internal:59999
```

Upload another small file.

Expected result:

- Job still reaches `completed`.
- Version becomes `active`.
- Extraction provenance records failure details.
- Job events or artifact metadata show extraction failed in optional mode.

What this proves:

- Content parsing and chunking are not blocked by optional LLM availability.

## Step 8: Test Required Extraction Failure

Set extraction required with the same unavailable Ollama URL:

```env
ATLAS_EXTRACTION_ENABLED=true
ATLAS_EXTRACTION_MODE=required
ATLAS_OLLAMA_BASE_URL=http://host.docker.internal:59999
```

Upload another small file.

Expected result:

- Job becomes `failed`.
- Version becomes `failed`.
- Chunk artifacts may exist, but the version is not active.
- Previous active version for the same document remains active.

What this proves:

- Required extraction is a real quality gate.

## Step 9: Test Cancellation

Stop the worker:

```powershell
docker compose stop ingestion-worker
```

Upload a file so the job remains queued or unprocessed. Cancel it:

```powershell
curl.exe -sS -X POST "http://localhost:8000/v1/ingestion-jobs/<job-id>/cancel" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Expected result:

- Job becomes `cancelled`.
- Document version becomes `cancelled`.
- `job.cancelled` appears in `ingestion_job_events`.
- `ingestion.job_cancelled` appears in `outbox_messages`.

Restart the worker when done:

```powershell
docker compose up -d ingestion-worker
```

## Step 10: Test New Version Activation

Upload a successful first version for a document. Then upload a second successful version for the same document.

Expected result:

- First version becomes `superseded`.
- Second version becomes `active`.
- Only one active version exists for the document.

Check:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select document_id, version_number, status from document_versions order by document_id, version_number;"
```

What this proves:

- Successful activation is atomic.
- Failed or cancelled newer versions do not replace a known-good active version.

## Clean Reset

This deletes local database, MinIO, and observability volumes:

```powershell
docker compose down -v
```

Use this when manual testing gets confusing and a clean state is easier.

