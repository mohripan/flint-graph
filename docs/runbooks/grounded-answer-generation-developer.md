# Grounded Answer Generation Developer Runbook

## Purpose

Use this runbook when implementing or debugging Milestone 08 grounded answer
generation, citation repair, support checking, abstention, streaming answer
events, faithfulness persistence, and answer provenance APIs.

## Target Flow

```text
context.packed
    -> draft answer generation
    -> citation repair
    -> support checking
    -> abstention policy
    -> persist verified answer and answer claims
    -> answer.delta / answer.citation / support.checked / answer.finalized
    -> provenance APIs
```

## Configuration

Deterministic providers remain the default path for local tests:

```text
FLINT_GRAPH_QUERY_ANSWER_PROVIDER=deterministic
FLINT_GRAPH_QUERY_SUPPORT_PROVIDER=deterministic
```

Ollama answer generation is opt-in:

```text
FLINT_GRAPH_QUERY_ANSWER_PROVIDER=ollama
FLINT_GRAPH_QUERY_ANSWER_MODEL=llama3.2
FLINT_GRAPH_QUERY_ANSWER_TIMEOUT_SECONDS=180
FLINT_GRAPH_QUERY_ANSWER_TEMPERATURE=0.0
FLINT_GRAPH_QUERY_ANSWER_MAX_TOKENS=1024
FLINT_GRAPH_QUERY_ANSWER_STREAM_TOKENS=true
```

Support thresholds:

```text
FLINT_GRAPH_QUERY_MIN_SUPPORTED_CLAIM_RATIO=0.5
FLINT_GRAPH_QUERY_MIN_CONTEXT_RELEVANCE=0.0
```

`FLINT_GRAPH_QUERY_SUPPORT_PROVIDER=ollama` is reserved for the future LLM support
judge; the implemented provider is deterministic.

## Key Files

- `src/flint_graph/application/query_orchestration.py`: answer, claim,
  support-check, and stream-event contracts.
- `src/flint_graph/application/query_faithfulness.py`: pure citation repair,
  deterministic support checking, and abstention policy helpers.
- `src/flint_graph/application/services/query_faithfulness.py`: runtime
  draft-to-verified-answer pipeline.
- `src/flint_graph/application/services/query_answering.py`: answer generation,
  verified event emission, persistence, and completion.
- `src/flint_graph/application/services/query_runs.py`: query-run transition and
  answer-claim persistence helpers.
- `src/flint_graph/application/services/query_provenance.py`: answer-to-source
  provenance reader.
- `src/flint_graph/infrastructure/ollama.py`: Ollama answer generation and
  streaming adapter.
- `src/flint_graph/infrastructure/answer_generator_factory.py`: answer and
  support provider selection.
- `src/flint_graph/api/routes/query.py`: query stream, replay, inspection, and
  provenance endpoints.
- `migrations/versions/0011_answer_faithfulness.py`: answer faithfulness schema.

## Database Checks

Inspect answer summary columns:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select id, status, abstained, abstain_reason, supported_claim_count, unsupported_claim_count, support_method, answer_provider from query_runs order by created_at desc limit 10;"
```

Inspect persisted answer claims:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select query_run_id, claim_index, support_status, support_score, citation_ids, text from query_answer_claims order by created_at desc limit 20;"
```

Inspect answer events:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select sequence, event_type, payload from query_run_events where query_run_id = '<query-run-id>' order by sequence;"
```

Expected successful answer tail:

```text
answer.delta
answer.citation
support.checked
answer.finalized
query.completed
```

Expected abstention tail:

```text
answer.delta
support.checked
answer.abstained
answer.finalized
query.completed
```

## API Checks

Create and stream a query run:

```powershell
$run = curl.exe -sS -X POST http://localhost:8000/v1/query-runs `
  -H "X-Tenant-ID: <tenant-id>" -H "Content-Type: application/json" `
  -d '{"query":"Where is Acme headquartered?"}' | ConvertFrom-Json

curl.exe -N "http://localhost:8000/v1/query-runs/$($run.id)/events/stream" `
  -H "X-Tenant-ID: <tenant-id>"
```

Inspect provenance:

```powershell
curl.exe -sS "http://localhost:8000/v1/query-runs/$($run.id)/provenance" `
  -H "X-Tenant-ID: <tenant-id>"

curl.exe -sS "http://localhost:8000/v1/query-runs/$($run.id)/citations/c1" `
  -H "X-Tenant-ID: <tenant-id>"
```

## Debugging Checklist

- Confirm the query run has a context pack before debugging answer generation.
- Confirm every final citation ID exists in `query_context_pack_records`.
- Confirm `query_answer_claims` has one row per checked claim.
- Confirm `support.checked` counts match `query_runs` summary columns.
- Confirm abstained runs complete with no final citations and a non-null
  `abstain_reason`.
- Confirm provenance endpoints return 404 for a foreign `X-Tenant-ID`.
- For Ollama, confirm `/api/generate` is reachable and the configured model is
  pulled before debugging adapter behavior.

## Verification Commands

```powershell
uv run pytest tests\unit\test_query_faithfulness.py tests\unit\test_query_faithfulness_service.py tests\unit\test_ollama_answer_generator.py tests\integration\test_query_answering.py tests\integration\test_query_api.py
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

For endpoint changes, run a Docker Compose smoke and record results in
`notes/milestone-08/02-manual-verification-results.md`.
