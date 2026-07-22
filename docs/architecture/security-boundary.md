# Current Security Boundary

FlintGraph now has an MVP identity boundary suitable for controlled internal
evaluation with untrusted end users.

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

Local-development boundary:

- `FLINT_GRAPH_AUTH_MODE=dev` is the default for local and test environments.
  It is not real authentication.
- `env=staging` and `env=production` reject dev auth unless
  `FLINT_GRAPH_ALLOW_UNSAFE_DEV_AUTH=true` is deliberately set.

Still outside the boundary:

- Workspace creation is allowed for any authenticated user.
- Workspace membership is not synchronized from OIDC groups or SCIM.
- FlintGraph does not own password policy, MFA, account recovery, or IdP
  session controls.
- Compose credentials and local service defaults are development-only.
- Public deployment still needs TLS termination, production secrets, explicit
  CORS policy, rate limiting, request/body limit review, audit-log hardening,
  image pinning, backup/restore validation, and non-development Temporal and
  object-storage posture.
