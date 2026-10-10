# Developer doctor delivery: 2026-10-10

Delivered [#48](https://github.com/mohripan/flint-graph/issues/48) from
Milestone 26. `flint-graph-doctor` offers offline tooling inspection and live,
workspace-authorized read-only diagnostics, with redacted text/JSON and distinct
success, blocking failure, usage error and incomplete-verification exit codes.
The new viewer-authorized `/v1/model-readiness` endpoint checks Ollama inventories
with bounded GET requests; it never invokes models or downloads them. Hosted
models remain unverified. See the [runbook](../runbooks/developer-doctor.md).

Brainstorming kept this scoped to the existing public readiness APIs and CLI
pattern rather than adding a separate control plane. TDD added 40 tests before
their respective implementation changes: provider inventory behavior and
deadline/size bounds, CLI read-only/privacy/auth/error/index contracts, and OIDC
access for owners/viewers versus unauthenticated users/non-members.

## Verification passed

```text
uv run pytest -q
uv run pytest tests/integration/test_auth_api.py -k model_readiness -q
uv run ruff check .
uv run mypy
uv lock --check
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config --quiet
docker compose -f compose.yaml -f compose.ai-observability.yaml --profile metrics --profile ai-observability config --quiet
git diff --check
uv run flint-graph-doctor --offline --json
uv run flint-graph-doctor --base-url http://127.0.0.1:8010 --workspace-id b55da700-1aaf-409a-befb-965fc9f182b4 --json
```

The final full suite passed **581 tests**, with **6 opt-in tests skipped**, in
46.98 seconds. Mypy passed for 146 source files. Offline migration SQL used
explicit deterministic answer/support environment overrides; no database
migration was applied. The deterministic evaluation passed with unchanged
reviewed baselines.

The live doctor used a temporary API on loopback port 8010 with the working
tree code, existing local PostgreSQL/MinIO/Temporal/Neo4j/OpenSearch services,
the existing seven-document workspace, deterministic 384-dimensional embeddings
and the already installed local Gemma answer/support model. All five configured
service probes passed, recent coverage was 7 completed/0 failed, the active
index matched embedding configuration, and answer/support inventories were
available. Exit code was 0, with explicit warnings for dev auth, deterministic
embeddings and provider probes not configured in health readiness. No inference,
model pull, upload, workspace/index creation or deletion was requested.

The existing Compose API on port 8000 was intentionally not rebuilt or
reconfigured. Doctor against that older API returned exit 1 for missing
`/v1/model-readiness`, while still reporting existing search coverage correctly.
Deploy/rebuild the API with this commit before expecting that new check to work
on port 8000. Existing service volumes and provider choices were preserved.

## Skipped and remaining

No local frontend commands or browser QA were run because no frontend files
changed. Paid/live model evaluations, GPU benchmarks and model downloads were
not run; inventory presence is not an answer-quality/capacity result. Production
OIDC infrastructure was not started: role authorization was verified with the
existing signed-token API integration fixtures. Native telemetry validators and
the isolated OTLP integration are unchanged and are exercised by the existing
GitHub CI job, not rerun locally for this CLI change.

Reproducible bootstrap profiles (#49), pinned service/CI upgrades (#50) and UI
debugging handoff (#52) remain separate implementation issues. Doctor does not
bootstrap, switch embedding dimensions, reset data or bypass normal API auth
bookkeeping. The GitHub issue links the commit and its CI result separately.
