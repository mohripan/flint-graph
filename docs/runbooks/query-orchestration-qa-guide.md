# Query Orchestration QA Guide

## Purpose

Use this guide to validate Milestone 07 query behavior from a user and operator
perspective.

## Preconditions

- Docker Compose stack is running.
- Migrations are applied.
- At least one retrieval index version is active for the tenant or globally.
- Test documents have completed ingestion, graph resolution, and indexing.
- The query providers are configured, or deterministic providers are enabled.

Deterministic eval fixtures live in
`tests/fixtures/query_orchestration_eval_cases.json`. Run them with:

```powershell
uv run pytest tests\unit\test_query_orchestration_eval_fixtures.py
```

## Smoke Scenarios

### Factoid Query

Ask a narrow question with a known answer.

Expected:

- query is classified as `factoid`;
- lexical and vector retrieval run;
- answer cites packed context;
- final run status is `completed`.

### Relationship Query

Ask how two known entities are connected.

Expected:

- query is classified as `relationship`;
- entity linking accepts the relevant canonical entities;
- graph expansion adds bounded relationships;
- answer cites graph-backed context.

### Summary Query

Ask for a short summary across a document set.

Expected:

- query is classified as `summary` or `exploratory`;
- context pack includes diverse chunks;
- answer avoids unsupported claims.

### Insufficient Context

Ask about a fact not present in the indexed documents.

Expected:

- answer says the available context is insufficient;
- citations are absent or limited to context explaining the uncertainty;
- run status is `completed`, not `failed`.

### Foreign Tenant Isolation

Use a query run ID from another tenant.

Expected:

- inspection and event endpoints return 404;
- no foreign tenant candidates or citations appear in results.

### Retriever Failure

Disable or mock one retriever.

Expected:

- run degrades only when the selected strategy allows partial retrieval;
- otherwise the run fails with bounded error metadata;
- stream includes a terminal failure event.

## SSE Event Expectations

The event stream should include a monotonic sequence ending in exactly one
terminal event:

- `query.completed`;
- `query.failed`;
- `query.cancelled`.

Answer text should arrive through `answer.delta` events. Citations should arrive
as `answer.citation` events or in the final completed payload.

The live SSE endpoint is:

```powershell
curl.exe -N http://localhost:8000/v1/query-runs/<query-run-id>/events/stream `
  -H "X-Tenant-ID: <tenant-id>"
```

## Pass Criteria

- All query APIs are tenant-scoped.
- Every answer citation maps to an inspectable packed context item.
- Query-run inspection explains classification, entity linking, retrieval
  sources, fusion/rerank movement, context packing, and terminal status.
- Deterministic-provider tests pass without live model services.
- Manual smoke results are recorded under `notes/milestone-07/`.
