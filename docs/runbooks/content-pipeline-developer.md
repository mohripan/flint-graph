# Content Pipeline Developer Runbook

## Purpose

Use this runbook when changing or debugging the Milestone 03 content pipeline. It focuses on developer-level checks for the API, outbox relay, Temporal worker, object storage, parser, chunking, extraction, and document-version lifecycle.

For semi-technical manual validation, use `docs/runbooks/content-pipeline-qa-guide.md`.

## Local Stack

Start the complete stack:

```powershell
docker compose up --build
```

Reset local state:

```powershell
docker compose down -v
```

Useful service logs:

```powershell
docker compose logs -f api
docker compose logs -f outbox-relay
docker compose logs -f ingestion-worker
docker compose logs -f temporal
docker compose logs -f minio
```

## Pipeline Path

Current worker path:

```text
upload or URL intake
    -> raw object in MinIO
    -> document version with object_uri and content_hash
    -> ingestion job + job.queued event
    -> ingestion.job_queued outbox message
    -> outbox relay starts Temporal workflow
    -> worker marks job running
    -> worker reads raw object and verifies sha256 hash
    -> bounded parser subprocess
    -> normalized.json artifact
    -> chunks.json artifact
    -> document_chunks rows
    -> extraction.json artifact
    -> job completed or failed
    -> version active or failed
```

The metadata-first document endpoint is compatibility-only for this milestone. It can create versions without `object_uri` and `content_hash`; those jobs are expected to fail in the real worker pipeline.

## Configuration

Important worker settings:

```env
ATLAS_OBJECT_STORE_ENDPOINT_URL=http://minio:9000
ATLAS_OBJECT_STORE_BUCKET=atlas-rag
ATLAS_PARSER_TIMEOUT_SECONDS=30
ATLAS_PARSER_MAX_RAW_BYTES=10485760
ATLAS_PARSER_MAX_NORMALIZED_BYTES=5242880
ATLAS_PARSER_MAX_ELEMENTS=10000
ATLAS_CHUNKING_MAX_CHUNK_CHARS=1200
ATLAS_CHUNKING_OVERLAP_CHARS=120
ATLAS_EXTRACTION_ENABLED=true
ATLAS_EXTRACTION_MODE=optional
ATLAS_LLM_PROVIDER=ollama
ATLAS_OLLAMA_BASE_URL=http://host.docker.internal:11434
ATLAS_OLLAMA_MODEL=gemma3:1b
ATLAS_EXTRACTION_TIMEOUT_SECONDS=60
```

Default extraction is optional. If Ollama is unavailable, ingestion can still complete and `extraction.json` records failure provenance.

## Upload Smoke Test

Create a tenant and upload Markdown:

```powershell
$tenant = curl.exe -sS -X POST http://localhost:8000/v1/tenants `
  -H "Content-Type: application/json" `
  -d '{"name":"Developer Content Pipeline"}' | ConvertFrom-Json

@"
# Developer Smoke

AtlasRAG should parse this markdown, chunk it, and record extraction provenance.
"@ | Set-Content -Encoding utf8 .\developer-smoke.md

$upload = curl.exe -sS -X POST http://localhost:8000/v1/documents/uploads `
  -H "X-Tenant-ID: $($tenant.id)" `
  -H "Idempotency-Key: developer-smoke-md-001" `
  -F "title=Developer Smoke" `
  -F "external_id=developer-smoke-md-001" `
  -F "file=@developer-smoke.md;type=text/markdown" | ConvertFrom-Json
```

Poll the job:

```powershell
curl.exe -sS "http://localhost:8000/v1/ingestion-jobs/$($upload.ingestion_job_id)" `
  -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

## Database Checks

Latest job and version:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select j.id as job_id, j.status as job_status, v.id as version_id, v.status as version_status, j.error_code, j.error_message from ingestion_jobs j join document_versions v on v.id = j.document_version_id order by j.created_at desc limit 5;"
```

Job events:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select e.event_type, e.from_status, e.to_status, e.details from ingestion_job_events e join ingestion_jobs j on j.id = e.job_id order by e.created_at desc limit 10;"
```

Artifacts:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select artifact_type, schema_version, metadata, object_uri from document_artifacts order by created_at desc limit 10;"
```

Chunks:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select chunk_index, left(text, 120) as preview, heading_path, source_element_ids from document_chunks order by created_at desc, chunk_index limit 10;"
```

## MinIO Checks

Open the MinIO console:

```text
http://localhost:9001
```

Expected objects for a processed version:

```text
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/raw/source
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/artifacts/normalized.json
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/artifacts/chunks.json
tenants/<tenant_id>/documents/<document_id>/versions/<version_id>/artifacts/extraction.json
```

## Failure Modes

Optional extraction failure:

- Set `ATLAS_EXTRACTION_MODE=optional`.
- Point `ATLAS_OLLAMA_BASE_URL` to an unavailable host.
- Expected: job `completed`, version `active`, extraction artifact status `failed`.

Required extraction failure:

- Set `ATLAS_EXTRACTION_MODE=required`.
- Point `ATLAS_OLLAMA_BASE_URL` to an unavailable host.
- Expected: job `failed`, version `failed`, extraction artifact status `failed`.

Raw hash mismatch:

- Indicates the raw object changed after intake or the persisted hash is wrong.
- Expected: job `failed`, version `failed`, no activation.

Parser failure:

- Unsupported binary input, scanned PDFs, parser timeout, and parser output limit failures are controlled ingestion failures.
- Expected: job `failed`, version `failed`, no activation.

## Verification Commands

Run before ending behavior-changing work:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

For phases touching the worker path, also run at least one real Docker Compose upload smoke test and record results in `notes/milestone-03/02-manual-testing-content-pipeline.md`.
