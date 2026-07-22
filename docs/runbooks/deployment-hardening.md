# Deployment Hardening Runbook

Use this checklist before exposing FlintGraph beyond a trusted developer
machine.

## Required API Settings

Set:

```powershell
$env:FLINT_GRAPH_ENV = "production"
$env:FLINT_GRAPH_AUTH_MODE = "oidc"
$env:FLINT_GRAPH_PUBLIC_BASE_URL = "https://api.example.com"
$env:FLINT_GRAPH_ALLOWED_ORIGINS = "https://app.example.com"
$env:FLINT_GRAPH_TRUSTED_HOSTS = "api.example.com"
$env:FLINT_GRAPH_REQUIRE_TLS = "true"
$env:FLINT_GRAPH_RATE_LIMIT_ENABLED = "true"
```

Also configure OIDC issuer/audience, object-store credentials, database,
Neo4j, OpenSearch, Temporal, and model-provider credentials. Do not use the
local defaults from `.env.example` for any externally reachable deployment.

## Network Boundary

- Terminate TLS at a proxy or load balancer.
- Forward only the API port and frontend origin required by the deployment.
- Keep PostgreSQL, MinIO, Neo4j, OpenSearch, Temporal, and observability
  services private to the deployment network.
- Configure `FLINT_GRAPH_TRUSTED_HOSTS` to the public API hostnames only.
- Configure `FLINT_GRAPH_ALLOWED_ORIGINS` to the frontend origins only.

## Request And Intake Limits

- Set `FLINT_GRAPH_MAX_UPLOAD_BYTES` to the largest file size the deployment
  intentionally supports.
- Set `FLINT_GRAPH_MAX_URL_INTAKE_BYTES` separately if URL intake should be
  smaller than upload intake.
- Keep `FLINT_GRAPH_ALLOW_PRIVATE_URL_INTAKE=false` outside local development.
- Test that oversized uploads return 413 and private URL targets return a 4xx
  problem response before launch.

## Rate Limits

The built-in limiter is fixed-window and in-memory. It is suitable for local
testing and controlled single-process deployments only.

- For a single API process, set `FLINT_GRAPH_ALLOW_IN_MEMORY_RATE_LIMIT=true`
  after choosing `FLINT_GRAPH_RATE_LIMIT_REQUESTS` and
  `FLINT_GRAPH_RATE_LIMIT_WINDOW_SECONDS`.
- For multiple API replicas, put rate limiting at the ingress/proxy layer or
  replace the backend with a shared store before scaling out.

## Secrets

- Rotate local Compose defaults before deployment.
- Store model API keys, database passwords, object-store keys, and OIDC client
  secrets in the deployment secret manager.
- Never commit real `.env` files.
- Review logs to ensure secrets are not emitted in startup failures or provider
  errors.

## Pre-Launch Smoke

Run:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
cd frontend; npm run build
```

Then perform a live workspace smoke: authenticate, create a workspace, prepare
search, upload a document, wait for searchable readiness, ask a question,
verify citations, verify a viewer is denied a mutation, and verify delete
cleanup.

