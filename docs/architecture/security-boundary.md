# Current security boundary

This milestone is safe for local development only.

`X-Tenant-ID` selects the tenant context used by database queries. It does not prove that the caller is entitled to act for that tenant. Before any shared or public deployment, the API must validate an OIDC access token, derive tenant membership and roles from trusted claims or an authorization store, and reject attempts to override tenant context through an untrusted header.

Local PostgreSQL credentials and Grafana settings in `compose.yaml` are development defaults. They must not be reused outside an isolated developer environment.
