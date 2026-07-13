# Content Pipeline QA Guide

## Status

In progress for Milestone 03. Phase 2 upload and URL intake endpoints exist, Phase 3 document-version lifecycle semantics are implemented, Phase 4 parser contracts are implemented in code, Phase 5 chunking plus artifact persistence services are implemented in code, and Phase 6 extraction plus provenance services are implemented in code. Worker integration and end-to-end artifact creation remain planned until Phase 7.

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
- `postgres`: stores tenants, documents, versions, jobs, outbox messages, document artifacts, and document chunks. Chunk rows and extraction provenance are written by Phase 5 and 6 services, but the worker does not call them yet.
- `minio`: stores raw source objects. The Phase 5 and 6 services can write normalized, chunk-manifest, and extraction artifacts, but the worker does not call them yet.
- `outbox-relay`: starts Temporal workflows from durable outbox messages.
- `temporal`: runs workflow orchestration.
- `ingestion-worker`: currently runs the stub ingestion activity. Job completion activates the document version, but worker parser integration, chunk persistence, extraction, and required-extraction failure handling are planned for Phase 7.

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

Response fields to note:

- `document_id`
- `document_version_id`
- `ingestion_job_id`
- `object_uri`
- `content_hash`
- `job_status`

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

- With the stub worker, job status can move to `completed` if the relay and worker are running.
- Document version status changes from `pending` to `active` when the job completes.
- Events include `job.queued`; with relay and worker running, they can also include `job.started` and `job.completed`.

Database effect during worker processing:

- `outbox_messages.status` changes from `pending` to `published`.
- `ingestion_jobs.status` changes from `queued` to `running` to `completed`.
- `document_versions.status` changes from `pending` to `active`.
- Phase 5 service tests validate normalized artifact writes, chunk-manifest writes, and chunk rows in code.
- Phase 6 service tests validate extraction artifacts and success/failure provenance in code.
- These artifacts, chunk rows, and extraction provenance are not written during worker execution yet.

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

Expected Phase 2 object:

```text
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/raw/source
```

The Phase 5 and 6 services write these derived artifacts when invoked by code, but the worker will not create them end-to-end until Phase 7:

```text
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/artifacts/normalized.json
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/artifacts/chunks.json
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
- Phase 4 supports HTML parsing in code.
- Phase 5 supports chunk rows and chunk-manifest artifacts in code.
- Phase 6 supports extraction artifacts and provenance in code.
- Worker integration is planned for Phase 7, so URL intake does not produce derived artifacts end-to-end yet.

## Step 7: Test Optional Extraction Failure

This is a Phase 7 end-to-end check. In Phase 6, automated service tests already prove that optional extraction failure writes failure provenance and returns a non-blocking result.

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

This is a Phase 7 end-to-end check. In Phase 6, automated service tests already prove that required extraction failure writes failure provenance and returns a blocking result.

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
- Job terminal state and document-version terminal state stay aligned.

## Clean Reset

This deletes local database, MinIO, and observability volumes:

```powershell
docker compose down -v
```

Use this when manual testing gets confusing and a clean state is easier.
