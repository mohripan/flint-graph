# Milestone 12: MVP Bootstrap And Access Boundary

Milestone 12 makes FlintGraph usable by authenticated workspace users instead
of relying on a locally selected tenant ID alone. It adds a Keycloak-compatible
OIDC boundary, PostgreSQL-backed workspace membership, MVP setup actions, and
server-backed frontend state for documents and query history.

Implemented behavior:

- API authentication is controlled by `FLINT_GRAPH_AUTH_MODE`.
- `dev` auth remains the default for local development and tests. It creates a
  fixed development principal and auto-grants owner membership to existing
  workspaces so older local flows keep working.
- `oidc` auth validates `Authorization: Bearer <token>` using the configured
  issuer, audience, and JWKS. If `FLINT_GRAPH_OIDC_JWKS_URL` is omitted, the
  API derives the Keycloak realm certs endpoint from the issuer.
- `env=staging` and `env=production` reject `auth_mode=dev` unless
  `FLINT_GRAPH_ALLOW_UNSAFE_DEV_AUTH=true` is explicitly set.
- OIDC principals are persisted in `users` and matched by issuer plus subject.
- Workspace membership is persisted in `workspace_memberships` with
  `owner`, `admin`, `member`, and `viewer` roles.
- Workspace APIs are available at `GET /v1/workspaces`,
  `POST /v1/workspaces`, and `POST /v1/workspaces/{workspace_id}/members`.
- Tenant-scoped routes require an authenticated user and active workspace
  membership. Missing membership returns 403.
- Viewer access can inspect workspace-scoped data and ask questions.
- Member access can create documents and ingestion jobs.
- Admin and owner access can manage members, delete documents, retry projection
  cleanup, bootstrap retrieval indexes, start active-index backfills, and apply
  graph review or merge decisions.
- `POST /v1/retrieval-index/bootstrap` idempotently creates or reuses an active
  retrieval index version from the current embedding configuration.
- `POST /v1/retrieval-index/backfill-active` queues a tenant backfill for the
  active index and starts the Temporal backfill workflow.
- `GET /v1/index-backfills` lists workspace backfill jobs for setup visibility.
- `GET /v1/system-readiness` reports auth mode, provider settings, embedding
  settings, and tenant search readiness.
- `GET /v1/documents` lists durable backend documents with latest-version
  summary state.
- `GET /v1/query-runs` lists recent tenant query runs.
- The frontend now has an auth gate, server-backed workspace listing/creation,
  a setup page for readiness/index/backfill operations, backend document lists,
  and recent query history.

Keycloak-oriented configuration:

```powershell
$env:FLINT_GRAPH_AUTH_MODE = "oidc"
$env:FLINT_GRAPH_OIDC_ISSUER = "http://localhost:8080/realms/flintgraph"
$env:FLINT_GRAPH_OIDC_AUDIENCE = "flintgraph-api"
```

For the frontend:

```powershell
$env:VITE_FLINT_GRAPH_AUTH_MODE = "oidc"
$env:VITE_FLINT_GRAPH_OIDC_AUTHORITY = "http://localhost:8080/realms/flintgraph"
$env:VITE_FLINT_GRAPH_OIDC_CLIENT_ID = "flintgraph-frontend"
```

Operational notes:

- The frontend uses `oidc-client-ts` and sends access tokens through the shared
  API client and SSE `fetch()` stream.
- `X-Tenant-ID` is still the workspace selector. In OIDC mode it is authorized
  against server-side membership before tenant-scoped handlers run.
- Workspace creation is currently open to any authenticated user. This is a
  pragmatic MVP default for internal deployment; a stricter install can add an
  invitation or system-admin bootstrap policy later.
- Group-claim to workspace-role synchronization is not implemented. Workspace
  membership is managed in FlintGraph PostgreSQL.
- There is no SCIM/user lifecycle sync, password management, MFA policy, or
  session management in FlintGraph. Those remain responsibilities of the OIDC
  provider.
- Public exposure still requires production secrets, TLS, CORS policy, rate
  limits, request/body limits review, audit hardening, and non-development
  backing services.

Supersession note: Milestone 13 implements the first controlled public API
boundary for TLS, CORS, host validation, request and intake limits, URL-intake
SSRF controls, and rate limiting. The remaining deployment-specific work is
tracked in `docs/milestones/13-production-exposure-hardening.md` and
`docs/runbooks/deployment-hardening.md`.
