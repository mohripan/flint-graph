# Current Security Boundary

FlintGraph now has a controlled deployment boundary suitable for a first
public or internal-company deployment with untrusted authenticated users.

Implemented boundary:

- `FLINT_GRAPH_AUTH_MODE=oidc` requires `Authorization: Bearer <token>` and
  validates the token issuer, audience, signature, and time claims against the
  configured OIDC issuer/JWKS.
- Keycloak realms work with `FLINT_GRAPH_OIDC_ISSUER` and
  `FLINT_GRAPH_OIDC_AUDIENCE`; `FLINT_GRAPH_OIDC_JWKS_URL` can override the
  derived realm certs URL.
- Authenticated users are persisted by OIDC issuer plus subject.
- Workspace membership and role authorization are stored in PostgreSQL.
- `X-Tenant-ID` remains the workspace selector, but tenant-scoped dependencies
  authorize that workspace against the current authenticated user before the
  route handler runs.
- Role tiers are `viewer`, `member`, `admin`, and `owner`.
- CORS and trusted-host validation are explicit in staging and production.
- `FLINT_GRAPH_REQUIRE_TLS=true` enables HTTPS redirect middleware for deployed
  profiles.
- Upload and URL intake have configurable byte limits before work enters object
  storage or background jobs.
- URL intake blocks private, loopback, link-local, and multicast targets by
  default to reduce SSRF risk.
- Expensive endpoints are protected by a fixed-window rate limiter keyed by
  user and workspace when enabled.

Local-development boundary:

- `FLINT_GRAPH_AUTH_MODE=dev` is the default for local and test environments.
  It is not real authentication.
- `env=staging` and `env=production` reject dev auth unless
  `FLINT_GRAPH_ALLOW_UNSAFE_DEV_AUTH=true` is deliberately set.
- Local URL intake permits private addresses so developers can test against
  local fileservers.

Still outside the boundary:

- Workspace creation is allowed for any authenticated user.
- Workspace membership is not synchronized from OIDC groups or SCIM.
- FlintGraph does not own password policy, MFA, account recovery, or IdP
  session controls.
- Compose credentials and local service defaults are development-only.
- Distributed rate limiting, audit export, image pinning policy, and
  non-development Temporal/object-storage posture remain deployment-specific.
