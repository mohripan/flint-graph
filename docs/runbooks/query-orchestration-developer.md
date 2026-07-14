# Query Orchestration Developer Runbook

## Purpose

Use this runbook when implementing or debugging Milestone 07 query
orchestration: LangGraph state, query classification, entity linking, parallel
retrievers, fusion, graph expansion, reranking, context packing, and streaming
answers.

## Target Flow

```text
POST /v1/query-runs
    -> create query_runs row
    -> run LangGraph state machine
    -> append query_run_events
    -> call lexical/vector/graph retrieval services
    -> pack citation-ready context
    -> stream answer events
    -> inspect final query run
```

## Configuration

Implemented Phase 1 settings:

- query orchestration enabled/disabled;
- classifier provider;
- reranker provider;
- answer generator provider;
- default and maximum candidate limits;
- graph expansion depth;
- context token budget;
- maximum context records;
- SSE heartbeat interval.

Deterministic providers should be the default in tests and local smoke paths
that do not require live LLM services.

The current environment variables are:

```text
ATLAS_QUERY_ENABLED
ATLAS_QUERY_CLASSIFIER_PROVIDER
ATLAS_QUERY_RERANKER_PROVIDER
ATLAS_QUERY_ANSWER_PROVIDER
ATLAS_QUERY_DEFAULT_CANDIDATE_LIMIT
ATLAS_QUERY_MAX_CANDIDATE_LIMIT
ATLAS_QUERY_CONTEXT_TOKEN_BUDGET
ATLAS_QUERY_MAX_CONTEXT_RECORDS
ATLAS_QUERY_GRAPH_DEPTH
ATLAS_QUERY_STREAM_HEARTBEAT_SECONDS
```

## Database Checks

Implemented query-run tables:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "\dt *query*"
```

Inspect recent runs:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select id, tenant_id, status, classification_label, created_at, completed_at, error_code from query_runs order by created_at desc limit 20;"
```

Inspect stream events:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select query_run_id, sequence, event_type, created_at from query_run_events order by created_at desc, sequence desc limit 50;"
```

Inspect candidates:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select query_run_id, source, candidate_type, rank, fusion_score, rerank_score from query_run_candidates order by created_at desc limit 50;"
```

Inspect context packs:

```powershell
docker compose exec postgres psql -U atlas -d atlas -c "select query_run_id, pack_version, token_budget, token_count, created_at from query_context_packs order by created_at desc limit 20;"
```

During Phase 2, these tables are populated through
`atlas_rag.application.services.query_runs`. Public query APIs are still planned
for a later phase.

## API Checks

Create a run:

```powershell
curl.exe -sS -X POST http://localhost:8000/v1/query-runs `
  -H "X-Tenant-ID: <tenant-id>" -H "Content-Type: application/json" `
  -d '{"query":"Where is Acme headquartered?","limits":{"candidates":10}}'
```

Stream events:

```powershell
curl.exe -N http://localhost:8000/v1/query-runs/<query-run-id>/events `
  -H "X-Tenant-ID: <tenant-id>"
```

Inspect final state:

```powershell
curl.exe -sS http://localhost:8000/v1/query-runs/<query-run-id> `
  -H "X-Tenant-ID: <tenant-id>"
```

## Debugging Checklist

- Confirm an active retrieval index version is visible to the tenant.
- Confirm lexical and vector primitive searches work for the same tenant.
- Confirm canonical entities exist before debugging graph expansion.
- Check query-run events for the last successful node.
- Compare raw retriever ranks to fusion and rerank scores.
- Inspect context-pack truncation reasons before changing answer prompts.
- Confirm every answer citation maps to a packed context record.

## Failure Modes

- No active index version: query creation or initialization fails.
- Entity linking ambiguity: graph expansion should stay conservative.
- Retriever unavailable: run may degrade only if strategy allows partial
  retrieval.
- Context budget too small: answer should report insufficient context or cite
  the limited pack.
- Generator failure: terminal `query.failed` event and bounded error metadata.
- Client disconnect: server should record whether graph execution completed,
  failed, or was cancelled.

## Verification Commands

Run before ending behavior-changing work:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

For phases touching streaming behavior, also run an SSE manual smoke and record
results under `notes/milestone-07/`.
