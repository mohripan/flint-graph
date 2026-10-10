# Read-only developer doctor

Implemented for [#48](https://github.com/mohripan/flint-graph/issues/48), under
[ADR 15](../adr/0015-reproducible-developer-experience.md).

## Usage

Install the existing project tooling with `uv sync --all-groups`. These commands
work in PowerShell and Unix shells:

```text
uv run flint-graph-doctor --offline
uv run flint-graph-doctor --base-url http://localhost:8000 --workspace-id YOUR-WORKSPACE-UUID
uv run flint-graph-doctor --base-url https://api.example.com --workspace-id YOUR-WORKSPACE-UUID --token-env FLINT_GRAPH_API_TOKEN --json
```

Replace the workspace placeholder with an existing UUID from the workspace UI.
For OIDC, securely populate the named environment variable with an existing
bearer token; do not put tokens in command-line arguments or URLs. The tenant
header selects a workspace, not an authentication method. Viewer membership is
sufficient. HTTPS is required except for loopback HTTP. Credential-bearing URLs,
query strings and fragments are rejected; redirects are not followed and ambient
HTTP proxy credentials are not used. `--timeout` controls HTTP operation timeouts
(default 20 seconds, greater than zero and at most 120).

Offline mode checks Python runtime and whether `uv`, `docker` and `node` are on
PATH. It does **not** run Docker, validate executable versions, contact services,
load credential-validating application settings or claim live readiness. A
missing optional developer tool is a warning, not a remote API outage. It does
not run the evaluation gate; run that separately when qualifying code changes.

## Live report and next steps

Live mode makes only GET requests to four public API endpoints:

| Endpoint | Evidence |
| --- | --- |
| `/health/live` | API process is responding |
| `/health/ready` | Configured dependency probes, including details of a 503 report |
| `/v1/system-readiness` | Authorized effective provider/model/dimension configuration, active index and recent coverage |
| `/v1/model-readiness` | Authorized cheap model inventory checks for embedding, answer and support roles |

The model endpoint uses Ollama's documented read-only
[`GET /api/tags`](https://docs.ollama.com/api/tags), deduplicating checks against
the same endpoint within one request. Bare names accept the `:latest` alias;
explicit tags must match. Empty inventories mean missing, not healthy. Each
inventory has an overall deadline from `readiness_probe_timeout_seconds` and a
2 MiB response limit. Redirects, malformed reports, HTTP errors and timeouts
become `unavailable` without exposing provider URLs or exception bodies.
Hosted providers return `unknown`: no paid calls are used to prove availability.
Deterministic providers return `offline`, with a warning that fixtures do not
establish real-model answer quality. Installed models are not proof of inference
capacity or useful answer quality; use an explicitly approved live evaluation.

Local API readiness normally probes only PostgreSQL. Doctor explicitly marks
other services as not checked instead of implying they are healthy. Configure
the API's readiness-required/optional dependencies to cover desired services.
The CLI never contacts internal databases, inference servers or operator tools
directly, and never changes those settings.

Index compatibility compares provider, model and dimensions with the effective
embedding configuration. Mismatches require a compatible index and explicit
backfill, **not** deleting documents or resetting volumes. Coverage counters
describe the readiness API's recent-document window, not whole-corpus totals.
Missing coverage points to Setup; failed recent coverage is highlighted even
when another document is searchable.

Doctor ignores document titles/content, issuer URLs, unknown response fields,
raw dependency details and provider error payloads. Live responses are limited
to 2 MiB each. Output contains approved nonsecret configuration, UUIDs, counts,
fixed diagnostic messages and concrete next steps. There are no workspace/index
creation, upload, deletion, model pull or inference requests. The normal API
authentication dependency can still perform its existing user/membership
bookkeeping (including dev-mode auto-membership); doctor does not bypass or
replace that server behavior.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Checks passed within the declared scope; warnings can remain |
| 1 | A blocking service/model/search/auth/response failure occurred |
| 2 | Invalid command arguments |
| 3 | No blocking failure, but a configured model/dependency remains unverified |

`--json` produces the same redacted report with an `exit_code` field. Offline
exit 0 means only local tooling inspection completed. A 404 on model readiness
requires an API upgrade, not assuming model availability. Reports can observe
changing configuration between requests; inconsistent model snapshots fail
safely and should be retried after deployment settles.
