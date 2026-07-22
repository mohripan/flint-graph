# Milestone 13: Production Exposure Hardening

Milestone 13 hardens FlintGraph for a first controlled deployment with
untrusted authenticated users. Milestone 12 established identity, workspace
membership, and role checks; this milestone adds the public API boundary around
that authenticated app.

Implemented behavior:

- Staging and production require explicit public exposure settings:
  `FLINT_GRAPH_PUBLIC_BASE_URL`, `FLINT_GRAPH_ALLOWED_ORIGINS`,
  `FLINT_GRAPH_TRUSTED_HOSTS`, `FLINT_GRAPH_REQUIRE_TLS=true`, OIDC settings,
  non-default object-store credentials, and enabled rate limiting.
- Local and test environments keep developer-friendly defaults for localhost,
  dev auth, private URL intake, and disabled rate limiting.
- CORS is explicit. Browser callers must match configured origins.
- Host validation rejects unexpected `Host` headers.
- TLS redirect middleware is enabled when `FLINT_GRAPH_REQUIRE_TLS=true`.
- Request-size middleware rejects oversized body-bearing requests with
  `413 application/problem+json`.
- Upload intake uses `FLINT_GRAPH_MAX_UPLOAD_BYTES` and returns 413 for
  oversized files before object-store persistence.
- URL intake uses `FLINT_GRAPH_MAX_URL_INTAKE_BYTES`, accepts only `http` and
  `https`, blocks private, loopback, link-local, and multicast targets by
  default, and revalidates redirect targets.
- A fixed-window in-memory rate limiter protects expensive endpoints:
  uploads, URL intake, query creation and streaming, lexical/vector search,
  retrieval bootstrap, active-index backfill, and backfill creation/listing.
- Rate limit keys include user identity when available plus `X-Tenant-ID`, so
  one workspace cannot exhaust another workspace's local quota.
- In-memory rate limiting is local/single-process only. Staging and production
  reject it unless `FLINT_GRAPH_ALLOW_IN_MEMORY_RATE_LIMIT=true` is explicitly
  set for a controlled single-replica deployment.
- Production docs now include a hardening runbook, backup/restore runbook, and
  `.env.production.example`.

Operational notes:

- Distributed rate limiting is intentionally deferred until a concrete
  deployment target chooses Redis or another shared backend.
- TLS termination can live in a proxy/load balancer, but the API should still
  receive correct forwarded scheme/host behavior before enabling
  `FLINT_GRAPH_REQUIRE_TLS`.
- Compose remains local-development oriented and still contains development
  service credentials. Production deployments must replace all secrets and
  pin/review externally exposed service images.

