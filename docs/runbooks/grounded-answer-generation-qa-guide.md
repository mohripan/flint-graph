# Grounded Answer Generation QA Guide

## Purpose

Use this guide to validate Milestone 08 from a user and operator perspective:
grounded answers, citation repair, support checking, abstention, streaming
events, and provenance inspection.

## Preconditions

- Docker Compose stack is running.
- Migrations are applied.
- A tenant has at least one active retrieval index version.
- Indexed content contains a known answer for the positive scenario.
- Deterministic providers are acceptable for smoke tests; Ollama is optional for
  live generated-answer checks.

Run deterministic eval coverage with:

```powershell
uv run pytest tests\unit\test_query_orchestration_eval_fixtures.py
```

## Smoke Scenarios

### Grounded Factoid

Ask a narrow question that is answered by indexed content.

Expected:

- stream includes `answer.delta`, at least one `answer.citation`,
  `support.checked`, `answer.finalized`, and `query.completed`;
- final answer cites only packed context;
- `supported_claim_count` is greater than zero;
- provenance returns the claim, citation, packed context text, and source IDs.

### Unsupported Question

Ask a question that the indexed content does not support.

Expected:

- answer says the available context is insufficient;
- run status is `completed`, not `failed`;
- `abstained` is true and `abstain_reason` is present;
- stream includes `answer.abstained`;
- final citations are empty.

### Citation Inspection

Resolve a citation from a completed answer.

Expected:

- `GET /v1/query-runs/{id}/citations/{citation_id}` returns the packed context
  record and the claims that cite it;
- an unknown citation ID returns 404;
- using another tenant ID returns 404.

### Streaming With Ollama

When Ollama is configured for answer generation:

Expected:

- provisional `answer.delta` events can appear before final verification;
- final `answer.delta` has `provisional = false`;
- persisted answer text matches `answer.finalized`, not an unverified draft.

## API Commands

Create a query run:

```powershell
$run = curl.exe -sS -X POST http://localhost:8000/v1/query-runs `
  -H "X-Tenant-ID: <tenant-id>" -H "Content-Type: application/json" `
  -d '{"query":"Where is Acme headquartered?"}' | ConvertFrom-Json
```

Stream events:

```powershell
curl.exe -N "http://localhost:8000/v1/query-runs/$($run.id)/events/stream" `
  -H "X-Tenant-ID: <tenant-id>"
```

Inspect run and provenance:

```powershell
curl.exe -sS "http://localhost:8000/v1/query-runs/$($run.id)" `
  -H "X-Tenant-ID: <tenant-id>"

curl.exe -sS "http://localhost:8000/v1/query-runs/$($run.id)/provenance" `
  -H "X-Tenant-ID: <tenant-id>"

curl.exe -sS "http://localhost:8000/v1/query-runs/$($run.id)/citations/c1" `
  -H "X-Tenant-ID: <tenant-id>"
```

## Pass Criteria

- Query APIs remain tenant-scoped.
- Every final answer citation resolves to a context-pack record.
- Every persisted answer claim carries support status, score, reason, and
  method.
- Abstention completes safely without fabricated citations.
- Provenance explains why each cited claim is grounded.
- Manual results are recorded under `notes/milestone-08/`.
