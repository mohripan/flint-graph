# FlintGraph

A production-oriented GraphRAG platform. The current implementation provides the ingestion control plane, a Temporal-backed content pipeline that materializes source bytes, parses supported formats, chunks content, records lineage, persists provenance-rich extraction proposals, builds a resolved knowledge graph with reviewable, reversible merges, maintains rebuildable retrieval indexes, exposes LangGraph-backed query orchestration with streamed, faithfulness-checked, citation-bearing answers and provenance APIs, includes real-model defaults plus an offline evaluation quality gate, adds an OIDC-backed workspace access boundary for MVP use, and hardens the public API boundary for controlled deployments. PostgreSQL is the system of record; Neo4j and OpenSearch are idempotent projections.

See the [roadmap](docs/ROADMAP.md) for useful-answer reliability, embeddings,
agent strategies, whole-corpus CAG, delegated research, production delivery,
and the platform/developer-experience tracks (Milestones 24–26).

## Why these milestones come first

The early milestones establish durable identities, tenant boundaries, version semantics, idempotency, inspectable job state, a safe asynchronous dispatch path, canonical graph mutation, retrieval primitives, and query-time orchestration. LangGraph orchestrates query execution; it does not replace the ingestion or indexing control planes.

## Requirements

- Docker with Compose, or PostgreSQL 17+
- `uv`
- Python 3.12
- Node.js 20.19+ or 22.12+ for the frontend

## Run locally with Docker

```bash
docker compose up --build
```

Then open:

- API documentation: `http://localhost:8000/docs`
- Frontend: run `cd frontend && npm run dev`, then open `http://localhost:5173`
- MinIO console: `http://localhost:9001`
- Grafana: `http://localhost:3000`
- Temporal Web UI: `http://localhost:8233`
- Neo4j browser: `http://localhost:7474`
- Liveness: `http://localhost:8000/health/live`
- Readiness: `http://localhost:8000/health/ready`

## Run locally without containerizing the API

```bash
cp .env.example .env
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn flint_graph.main:app --reload
```

In another shell, run Temporal locally and then start the outbox relay:

```bash
temporal server start-dev
make relay
make worker
```

## Authentication and workspaces

Local development defaults to `FLINT_GRAPH_AUTH_MODE=dev`, which creates a fixed
development user automatically. This preserves the simple curl examples below
without an `Authorization` header.

For Keycloak or another OIDC provider, configure the API with:

```powershell
$env:FLINT_GRAPH_AUTH_MODE = "oidc"
$env:FLINT_GRAPH_OIDC_ISSUER = "http://localhost:8080/realms/flintgraph"
$env:FLINT_GRAPH_OIDC_AUDIENCE = "flintgraph-api"
```

In staging and production, `auth_mode=dev` is rejected unless
`FLINT_GRAPH_ALLOW_UNSAFE_DEV_AUTH=true` is explicitly set.

## Deployment hardening

Staging and production require explicit public exposure settings before the API
will start:

```powershell
$env:FLINT_GRAPH_PUBLIC_BASE_URL = "https://api.example.com"
$env:FLINT_GRAPH_ALLOWED_ORIGINS = "https://app.example.com"
$env:FLINT_GRAPH_TRUSTED_HOSTS = "api.example.com"
$env:FLINT_GRAPH_REQUIRE_TLS = "true"
$env:FLINT_GRAPH_RATE_LIMIT_ENABLED = "true"
```

Uploads and URL intake are bounded by `FLINT_GRAPH_MAX_UPLOAD_BYTES` and
`FLINT_GRAPH_MAX_URL_INTAKE_BYTES`. URL intake blocks private and local network
targets outside local development unless `FLINT_GRAPH_ALLOW_PRIVATE_URL_INTAKE`
is explicitly enabled. See `.env.production.example` and
`docs/runbooks/deployment-hardening.md`.

The frontend OIDC settings are:

```powershell
$env:VITE_FLINT_GRAPH_AUTH_MODE = "oidc"
$env:VITE_FLINT_GRAPH_OIDC_AUTHORITY = "http://localhost:8080/realms/flintgraph"
$env:VITE_FLINT_GRAPH_OIDC_CLIENT_ID = "flintgraph-frontend"
```

Workspace APIs:

```bash
curl -sS -X POST http://localhost:8000/v1/workspaces \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme Research"}'

curl -sS http://localhost:8000/v1/workspaces
```

## Observability, audit, and usage

`docker compose up -d` already runs an OTLP receiver plus Grafana on
<http://localhost:3000>. The API and the durable processes (ingestion worker,
outbox relay, projection cleanup) all export traces there, so one upload produces
one trace spanning the API request, the outbox publish, and the Temporal
activities.

```powershell
# Dependency-aware readiness: 503 names the dependency that is down.
curl -sS http://localhost:8000/health/ready

# Who did what in a workspace (admin/owner).
curl -sS "http://localhost:8000/v1/audit-events?limit=20" -H "X-Tenant-ID: $TENANT"

# What the model providers consumed (admin/owner).
curl -sS "http://localhost:8000/v1/usage?group_by=model" -H "X-Tenant-ID: $TENANT"
```

To rehearse a pull-based metrics deployment:

```powershell
$env:FLINT_GRAPH_METRICS_ENABLED = "true"
$env:FLINT_GRAPH_METRICS_TOKEN = "local-scrape-token"
docker compose --profile metrics up -d
# Prometheus: http://127.0.0.1:9090; Alertmanager: http://127.0.0.1:9093
# The default Alertmanager receiver sends nothing.
```

Cost requires pricing configuration; unpriced calls are recorded with a null cost
rather than a guessed one:

```powershell
$env:FLINT_GRAPH_USAGE_PRICING = '{"anthropic:claude-opus-4-8":{"input_per_million":15.0,"output_per_million":75.0}}'
```

Grafana automatically provisions the [operations dashboard](http://localhost:3000/d/flint-graph-operations)
against LGTM's all-process metrics. The optional standalone scrape profile above
reads the API only. [Local Phoenix and trace fan-out](docs/runbooks/ai-observability.md)
adds AI trace inspection without model calls or changing provider defaults;
email delivery, ELK/log pipeline selection and vLLM qualification remain tracked
issues, not completed production features.

Logs redact prompts, answers, and document text by default.
`FLINT_GRAPH_LOG_PAYLOADS=true` exists for local prompt debugging only and is
rejected in staging and production. See
`docs/runbooks/operations-observability.md` and
`docs/architecture/observability-contract.md`.

## Exercise the vertical slice

Create a workspace:

```bash
curl -sS -X POST http://localhost:8000/v1/workspaces \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme Research"}'
```

Use the returned workspace ID as `X-Tenant-ID` to upload source material:

```bash
curl -sS -X POST http://localhost:8000/v1/documents/uploads \
  -H 'X-Tenant-ID: <tenant-id>' \
  -H 'Idempotency-Key: upload-note-001' \
  -F 'title=Uploaded Note' \
  -F 'external_id=uploaded-note-001' \
  -F 'file=@note.md;type=text/markdown'
```

Or materialize a URL:

```bash
curl -sS -X POST http://localhost:8000/v1/documents/from-url \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-ID: <tenant-id>' \
  -H 'Idempotency-Key: url-note-001' \
  -d '{"title":"Example Page","source_url":"https://example.org/","external_id":"example-page"}'
```

Both intake endpoints create the document, document version, ingestion job, and outbox message in one durable path. Repeating the same request with the same idempotency key returns the same document/version/job with HTTP 200 rather than creating another version.

With the relay and worker running, the job should move from `queued` to `running` to `completed`. The worker verifies the raw object hash, runs the bounded parser, writes normalized and chunk artifacts, persists queryable chunk lineage, runs provider-neutral proposal extraction, verifies exact evidence quotes, persists extraction runs and staged records, and activates the document version. If Ollama is unavailable in default optional extraction mode, extraction provenance records the failure and the job can still complete.

Fetch a job:

```bash
curl -sS http://localhost:8000/v1/ingestion-jobs/<job-id> \
  -H 'X-Tenant-ID: <tenant-id>' \
```

Fetch job events:

```bash
curl -sS http://localhost:8000/v1/ingestion-jobs/<job-id>/events \
  -H 'X-Tenant-ID: <tenant-id>' \
```

Cancel a queued or running job:

```bash
curl -sS -X POST \
  http://localhost:8000/v1/ingestion-jobs/<job-id>/cancel \
  -H 'X-Tenant-ID: <tenant-id>'
```

## Explore the knowledge graph

After a document is ingested, per-tenant entity resolution turns staged extracted proposals into canonical entities and relationships, then projects them into Neo4j. Inspect the resolved graph through the API:

```bash
# Canonical entities (deduplicated across documents; support_count reflects cross-doc support)
curl -sS http://localhost:8000/v1/entities -H 'X-Tenant-ID: <tenant-id>'

# One entity with its aliases, mentions, and relationships
curl -sS http://localhost:8000/v1/entities/<entity-id> -H 'X-Tenant-ID: <tenant-id>'

# Pending merge-review queue for ambiguous matches
curl -sS http://localhost:8000/v1/merge-reviews -H 'X-Tenant-ID: <tenant-id>'

# Resolve a review item (accept attaches to the candidate; reject creates a distinct entity)
curl -sS -X POST http://localhost:8000/v1/merge-reviews/<candidate-id>/decision \
  -H 'X-Tenant-ID: <tenant-id>' -H 'Content-Type: application/json' \
  -d '{"decision":"accept","reason":"same company"}'

# Manual, reversible merge and unmerge
curl -sS -X POST http://localhost:8000/v1/entities/<source-id>/merge \
  -H 'X-Tenant-ID: <tenant-id>' -H 'Content-Type: application/json' \
  -d '{"target_entity_id":"<target-id>","reason":"duplicate"}'
curl -sS -X POST http://localhost:8000/v1/entities/<source-id>/unmerge \
  -H 'X-Tenant-ID: <tenant-id>' -H 'Content-Type: application/json' -d '{"reason":"was not a duplicate"}'

# Merge decision audit log
curl -sS http://localhost:8000/v1/merge-decisions -H 'X-Tenant-ID: <tenant-id>'
```

The resolved graph is visible in the Neo4j browser at `http://localhost:7474`. Small local models such as the default `gemma3:1b` may produce sparse proposals; the pipeline records provider failures or rejected evidence without allowing raw model output to mutate the canonical graph.

## Ask streamed, citation-bearing queries

Before creating a query run, check workspace search readiness:

```bash
curl -sS http://localhost:8000/v1/search-readiness \
  -H 'X-Tenant-ID: <tenant-id>'
```

The query API rejects requests with HTTP 409 until at least one document version
has completed index coverage for the active retrieval index.

Create a query run:

```bash
curl -sS -X POST http://localhost:8000/v1/query-runs \
  -H 'X-Tenant-ID: <tenant-id>' \
  -H 'Content-Type: application/json' \
  -d '{"query":"Where is Acme headquartered?"}'
```

Stream the persisted event sequence and execute a queued run:

```bash
curl -N http://localhost:8000/v1/query-runs/<query-run-id>/events/stream \
  -H 'X-Tenant-ID: <tenant-id>'
```

Inspect the final run and replay persisted events:

```bash
curl -sS http://localhost:8000/v1/query-runs/<query-run-id> \
  -H 'X-Tenant-ID: <tenant-id>'
curl -sS http://localhost:8000/v1/query-runs/<query-run-id>/events \
  -H 'X-Tenant-ID: <tenant-id>'
```

The query-run response includes `query_diagnostics`, a compact summary of
retriever counts, failed retrievers, context packing, support decisions,
abstention reason, and provider metadata.

Inspect answer provenance:

```bash
curl -sS http://localhost:8000/v1/query-runs/<query-run-id>/provenance \
  -H 'X-Tenant-ID: <tenant-id>'
curl -sS http://localhost:8000/v1/query-runs/<query-run-id>/citations/c1 \
  -H 'X-Tenant-ID: <tenant-id>'
```

Grounded answer generation repairs model-emitted citation markers, checks each
claim against its cited context, abstains when support is weak, persists
per-claim support decisions, and streams authoritative final answer events after
verification.

## Quality commands

```bash
make check
```

`make check` runs lint, typecheck, tests, and the offline deterministic eval gate. On Windows
PowerShell, the direct commands are usually clearer:

```powershell
uv run ruff check .
uv run mypy
uv run pytest
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
```

Milestone 09 real-model defaults are env-aware: `FLINT_GRAPH_ENV=test` stays deterministic and
offline; non-test environments default to real providers unless explicitly overridden. For a
no-cost local query path, set `FLINT_GRAPH_QUERY_ANSWER_PROVIDER=deterministic`,
`FLINT_GRAPH_QUERY_SUPPORT_PROVIDER=deterministic`, and `FLINT_GRAPH_EMBEDDING_PROVIDER=deterministic`.

Milestone 10 adds an explicit local Ollama path for no-cost real answers:

```powershell
ollama pull nomic-embed-text
ollama pull llama3.2
$env:FLINT_GRAPH_EMBEDDING_PROVIDER = "ollama"
$env:FLINT_GRAPH_EMBEDDING_MODEL = "nomic-embed-text"
$env:FLINT_GRAPH_EMBEDDING_DIMENSIONS = "768"
$env:FLINT_GRAPH_QUERY_ANSWER_PROVIDER = "ollama"
$env:FLINT_GRAPH_QUERY_SUPPORT_PROVIDER = "ollama"
docker compose up --build
```

See `docs/runbooks/local-ollama-rag.md` for the retrieval-index/backfill and
discrete-math PDF smoke flow.

## Implemented invariants

1. Every document belongs to exactly one tenant.
2. Tenant-scoped reads deliberately return 404 for foreign resources.
3. Every ingestion attempt targets a distinct immutable document version.
4. Version numbers are allocated while locking the document row.
5. An idempotency key is unique within a tenant.
6. The initial `job.queued` transition is written in the same transaction as the job.
7. New jobs and cancellations write transactional outbox messages before leaving the API transaction.
8. The outbox relay marks messages published only after Temporal accepts the operation.
9. Job state changes go through explicit transition rules and append events.
10. Completed jobs activate their document version.
11. Failed jobs fail their document version.
12. Cancelled jobs cancel their document version.
13. Activating a version supersedes any previous active version for the same document.
14. Failed or cancelled newer versions do not disturb the current active version.
15. API errors use `application/problem+json` and include a request ID.
16. Upload and URL intake materialize immutable raw objects before queuing ingestion.
17. The worker verifies raw content hashes before parsing.
18. Normalized, chunk-manifest, and extraction artifacts are stored in object storage.
19. Queryable chunk lineage is persisted in PostgreSQL.
20. Optional extraction failure records provenance without blocking version activation.
21. Required extraction failure records provenance and fails the job/version.
22. Extraction produces provider-neutral staged proposals with verified evidence spans and queryable run/invocation provenance.
23. Entity resolution runs one writer per tenant via a PostgreSQL advisory lock.
24. Resolution applies banded decisions: auto-attach, review queue, or new entity.
25. Every merge decision is recorded and reviewable; merges are soft and reversible.
26. Relationships aggregate from resolved staged relations and entity-object claims whose endpoints both resolve to canonical entities.
27. PostgreSQL is authoritative; Neo4j is an idempotent projection rebuildable from PostgreSQL.
28. Query runs persist faithfulness summaries and per-claim support decisions.
29. Every final answer citation maps to a packed context record.
30. Unsupported answers abstain without fabricating citations.
31. Query provenance endpoints apply tenant filters.
32. Test and PR evaluation paths remain offline and deterministic.
33. Real provider selection without required credentials fails fast.
34. Evaluation baselines change only through an explicit reviewed update.
35. Staging and production require explicit public URL, CORS origins, trusted
    hosts, TLS, OIDC, non-default object-store credentials, and rate limiting.
36. Oversized request bodies and uploads are rejected before durable intake
    work is created.
37. URL intake only fetches HTTP(S) resources and blocks private/local network
    targets outside local development.
38. Expensive public endpoints can be rate-limited by user and workspace.

## Current milestone boundary

Milestone 13 added the controlled public API boundary around the Milestone 12
authenticated workspace model. The API fails closed in staging and production
unless deployment exposure settings are explicit, request and intake sizes are
bounded, URL intake is SSRF-aware, CORS and host validation are configured, TLS
redirect behavior is enabled, and rate limiting is turned on.

Milestone 14 makes that deployment operable: metrics and traces across every
process including the durable pipeline, dependency-aware readiness, an
append-only audit ledger written in the mutation's transaction, and per-workspace
token and cost accounting. Retention for audit and usage rows, distributed rate
limiting, and multi-replica scale-out remain open.

## Security status

`X-Tenant-ID` is still a workspace selector, not an identity proof. In OIDC mode
the API authorizes that workspace against server-side membership before
tenant-scoped handlers run. A controlled deployment still needs production
secrets, private backing services, a reviewed ingress/proxy configuration,
backup/restore practice, and deployment-specific rate-limit scaling decisions.
See `docs/architecture/security-boundary.md` and
`docs/runbooks/deployment-hardening.md`.

## Learning notes

Milestone notes:

- Foundation: `docs/milestones/01-foundation.md`
- Durable ingestion dispatch: `docs/milestones/02-durable-ingestion-dispatch.md`
- Content pipeline: `docs/milestones/03-content-pipeline.md`
- Knowledge graph: `docs/milestones/04-knowledge-graph.md`
- Provenance-rich extraction: `docs/milestones/05-provenance-rich-extraction.md`
- Retrieval indexes and backfills: `docs/milestones/06-retrieval-indexes.md`
- Local dispatch runbook: `docs/runbooks/durable-ingestion-dispatch.md`
- Content pipeline developer runbook: `docs/runbooks/content-pipeline-developer.md`
- Content pipeline QA guide: `docs/runbooks/content-pipeline-qa-guide.md`
- Knowledge graph developer runbook: `docs/runbooks/knowledge-graph-developer.md`
- Knowledge graph QA guide: `docs/runbooks/knowledge-graph-qa-guide.md`
- Knowledge graph contract: `docs/architecture/knowledge-graph-contract.md`
- Extraction proposal contract: `docs/architecture/extraction-proposal-contract.md`
- Retrieval index contract: `docs/architecture/retrieval-index-contract.md`
- Retrieval index developer runbook: `docs/runbooks/retrieval-index-developer.md`
- Retrieval index QA guide: `docs/runbooks/retrieval-index-qa-guide.md`
- Query orchestration: `docs/milestones/07-query-orchestration.md`
- Query orchestration contract: `docs/architecture/query-orchestration-contract.md`
- Query orchestration developer runbook: `docs/runbooks/query-orchestration-developer.md`
- Query orchestration QA guide: `docs/runbooks/query-orchestration-qa-guide.md`
- Grounded answer generation: `docs/milestones/08-grounded-answer-generation.md`
- Answer faithfulness contract: `docs/architecture/answer-faithfulness-contract.md`
- Grounded answer developer runbook: `docs/runbooks/grounded-answer-generation-developer.md`
- Grounded answer QA guide: `docs/runbooks/grounded-answer-generation-qa-guide.md`
- Real models and evaluation: `docs/milestones/09-real-models-and-evaluation.md`
- Local-first usable RAG: `docs/milestones/10-local-first-usable-rag.md`
- Document lifecycle correctness: `docs/milestones/11-document-lifecycle-correctness.md`
- MVP bootstrap and access boundary: `docs/milestones/12-mvp-bootstrap-and-access-boundary.md`
- Production exposure hardening: `docs/milestones/13-production-exposure-hardening.md`
- Operational readiness: `docs/milestones/14-operational-readiness.md`
- Evaluation contract: `docs/architecture/evaluation-contract.md`
- Real models developer runbook: `docs/runbooks/real-models-developer.md`
- Evaluation developer runbook: `docs/runbooks/evaluation-developer.md`
- Evaluation QA guide: `docs/runbooks/evaluation-qa-guide.md`
- Local Ollama RAG runbook: `docs/runbooks/local-ollama-rag.md`
- Frontend E2E QA guide: `docs/runbooks/frontend-e2e-qa-guide.md`
- Deployment hardening runbook: `docs/runbooks/deployment-hardening.md`
- Backup and restore runbook: `docs/runbooks/backup-restore.md`
- Operations, observability, audit, and usage runbook: `docs/runbooks/operations-observability.md`
- Observability contract: `docs/architecture/observability-contract.md`
