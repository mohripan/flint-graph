# Provenance Extraction Developer Runbook

## Purpose

Use this runbook when implementing or debugging Milestone 05 provenance-rich extraction proposals, evidence verification, staged records, and the refactored canonical-resolution input path.

For semi-technical validation, use `docs/runbooks/provenance-extraction-qa-guide.md`.

## Target Flow

```text
upload or URL intake
    -> raw object in MinIO
    -> parser and chunker
    -> persisted document_chunks
    -> extraction activity
        -> bounded batch assembly
        -> structured provider call
        -> schema/reference validation
        -> exact-quote evidence verification
        -> stable ID derivation
        -> manifest write
        -> staged-record transaction
    -> candidate generation
    -> canonical resolution
    -> Neo4j projection
```

## Development Checks

Start the local stack:

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
```

## Database Checks

Expected Milestone 05 tables:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "\dt *extraction*"
docker compose exec postgres psql -U atlas -d atlas -c "\dt *evidence*"
```

Recent extraction runs:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select id, document_version_id, status, schema_version, extractor_version, model_name, created_at from extraction_runs order by created_at desc limit 20;"
```

Evidence spans:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select chunk_id, start_offset, end_offset, span_hash from evidence_spans order by created_at desc limit 20;"
```

Candidate records:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select source_extracted_entity_id, target_kind, score, outcome, status from entity_resolution_candidates order by created_at desc limit 20;"
```

## Failure Modes

- Provider timeout: run records a bounded provider error and the activity fails.
- Invalid schema: invocation is recorded, invalid output is rejected, and the run fails or completes with warnings according to configuration.
- Missing quote: the affected proposal is rejected; other valid proposals may continue.
- Repeated quote without valid `start_hint`: evidence is rejected as ambiguous.
- Cancellation: unfinished extraction run is marked failed with `cancelled`.
- Retry after ready run: activity reuses the ready run and manifest rather than duplicating staged rows.

## Verification Commands

Run before ending behavior-changing work:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

For phases touching provider adapters or live projection, also run a Docker Compose ingestion smoke test and record results in `notes/milestone-05/02-manual-testing-provenance-extraction.md`.
