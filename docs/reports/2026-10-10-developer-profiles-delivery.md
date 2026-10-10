# Developer profiles delivery: 2026-10-10

Delivered [#49](https://github.com/mohripan/flint-graph/issues/49): explicit
offline/local-real Compose overlays and guarded `flint-graph-dev` check, lock and
bootstrap commands. The existing M16 preparation flow now optionally targets an
existing workspace with an explicit active index and stable upload identities.
Unprofiled `flint-graph-eval prepare` still creates fresh dedicated workspaces.
See the [runbook](../runbooks/developer-profiles.md).

Brainstorming scoped this to the existing public readiness/bootstrap/ingestion
interfaces. TDD added 21 public-boundary tests for profile preflight, model
fingerprints, role checks, model/index incompatibilities, API guard capabilities,
exclusive artifact writes, tiny-corpus opt-in and stable repeated preparation.
No unrelated workspace/index data or evaluation baselines were reset.

## Passed local gates

```text
uv run pytest -q
uv run ruff check .
uv run mypy
uv lock --check
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config --quiet
docker compose -f compose.yaml -f compose.offline.yaml config --quiet
docker compose -f compose.yaml -f compose.offline.yaml -f compose.ai-observability.yaml --profile ai-observability config --quiet
docker compose -f compose.yaml -f compose.local-real.yaml config --quiet
docker compose -f compose.yaml -f compose.local-real.yaml -f compose.ai-observability.yaml --profile ai-observability config --quiet
git diff --check
```

Full suite: **602 passed, 6 opt-in skips**, 43.33 seconds. Mypy: 147 source files.
Offline SQL used explicit deterministic answer/support environment overrides;
no database migration was applied. Local-real Compose validation used explicit
fixture model names/dimensions **only to validate configuration**, not as claimed
installed models. CI includes all four existing and four new profile/AI Compose
combinations. Deterministic reviewed baselines are unchanged.

## Real ingestion and repeat verification

Started the current API on loopback 8010 with deterministic model settings,
existing PostgreSQL on 55432 and existing MinIO/Temporal/Neo4j/OpenSearch. All five
configured dependency probes passed. The running worker was checked to use
deterministic extraction and `deterministic-test`/384 embeddings. Created a new,
dedicated evaluation workspace `7942ff92-6479-453d-be92-7e6e4aa5dea5` through the
public workspace API. Existing workspaces and raw objects were preserved.

```text
uv run flint-graph-dev bootstrap --profile offline --base-url http://127.0.0.1:8010 --workspace-id 7942ff92-6479-453d-be92-7e6e4aa5dea5 --smoke-corpus --dataset evals/datasets/acme-smoke --output notes/dx-profile-live-first.json
uv run flint-graph-dev bootstrap --profile offline --base-url http://127.0.0.1:8010 --workspace-id 7942ff92-6479-453d-be92-7e6e4aa5dea5 --smoke-corpus --dataset evals/datasets/acme-smoke --output notes/dx-profile-live-second.json
uv run flint-graph-doctor --base-url http://127.0.0.1:8010 --workspace-id 7942ff92-6479-453d-be92-7e6e4aa5dea5
uv run flint-graph-eval capture --dataset evals/datasets/acme-smoke --manifest notes/dx-profile-live-first.json --base-url http://127.0.0.1:8010 --output notes/dx-profile-live-fresh.jsonl --git-sha ca17a81-working-tree --query-timeout 60
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations notes/dx-profile-live-fresh.jsonl --config-name offline-profile-live --report notes/dx-profile-live-quality.json
```

Both preparations passed real immutable upload, ingestion completion, positive
coverage and lexical/vector projection probes for all six documents. Comparing
the two manifests confirmed identical document, version and job identities.
Doctor reported 6 completed/0 failed coverage on the existing visible global
index `1cb5935a-aff6-4083-99f9-75778604abdb`; it did not switch/deprecate that index.
Ten fresh deterministic queries completed with valid citations, but answer
match was **0.5**, abstention recall **0**, p95 latency **1.361 seconds**. This
is protocol verification, not a useful-answer quality pass.

For the guard's real PostgreSQL check, created a separate empty workspace
`5927125d-d059-46c4-94cf-94cc540615fd`, bootstrapped index
`aab6326d-d6c1-448e-b826-5b9c3a8df5cf`, then requested guarded bootstrap against
a temporary API on 8011 with an intentionally incompatible fixture model/64
dimensions. It returned **409**; public index inspection confirmed the original
index remained active. Both temporary API helpers were stopped after the smoke.
The small test workspaces/artifacts remain inspectable; nothing was deleted.

## Real local-answer verification and normal API deployment

Rebuilt **only the normal API** with
`docker compose up --build --no-deps -d api`, explicitly preserving its current
nonsecret embedding/provider/model/timeout/context settings from the existing
container. Other services, worker model choices and volumes were not recreated.
The current readiness/digest/guard endpoints now work on port 8000. The doctor
passed for the existing seven-document workspace
`b55da700-1aaf-409a-befb-965fc9f182b4` without changing its selected index.

```text
uv run flint-graph-doctor --workspace-id b55da700-1aaf-409a-befb-965fc9f182b4 --json
uv run flint-graph-eval capture --dataset evals/datasets/acme-smoke --manifest notes/dx-profile-live-first.json --base-url http://localhost:8000 --output notes/dx-profile-live-ollama-fresh.jsonl --git-sha ca17a81-working-tree --query-timeout 180
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations notes/dx-profile-live-ollama-fresh.jsonl --config-name ollama-answer-profile-live --report notes/dx-profile-live-ollama-quality.json
```

All ten fresh synthetic cases completed with **1.0 answer match, citation
validity, citation requirements, support ratio and abstention accuracy/recall**.
Retrieval hit@10 was 0.75 and recall@10 0.75; answer success does not establish
perfect retrieval. End-to-end p50/p95 latency was **5.859/13.777 seconds**.
Answer/support used already installed
`igorls/gemma-4-12B-it-qat-q4_0-unquantized-heretic:latest`, inventory digest
`sha256:2835c50a7b13c1e9c8ab58a4d08368e374ae5f33ce055afb0b8081bc006aef9f`.
These captures identify the source as the working tree after ca17a81, not a
falsely claimed previously committed/deployed revision.

This was a **hybrid smoke**: embeddings remained deterministic/384. A fully
local-real profile was correctly rejected before mutation/lock creation against
both deterministic and hybrid configurations:

```text
uv run flint-graph-dev lock --profile local-real --workspace-id 7942ff92-6479-453d-be92-7e6e4aa5dea5 --base-url http://127.0.0.1:8010 --output notes/dx-local-real-negative-lock.json
uv run flint-graph-dev lock --profile local-real --workspace-id 7942ff92-6479-453d-be92-7e6e4aa5dea5 --output notes/dx-hybrid-negative-lock.json
```

Both returned the expected failure and produced no output file. Installed model
inventory checks are not inference tests, declared embedding dimensions are not
measured by inventory, and a successful hybrid capture does not prove real
embedding quality. Existing captures do not populate provider token/cost metrics;
their default zeros are **not** token or cost measurements.

## Skipped and next issues

No embedding model was downloaded, paid/cloud provider called, or GPU rented.
Positive fully local-real ingestion with an actual embedding model remains
unverified; it needs separately provisioned compatible models/hardware. No local
frontend commands/browser checks were run because no frontend files changed.
OIDC role checks use signed-token API fixtures rather than a new live IdP.
Native telemetry smoke is unchanged and reruns in GitHub CI, not locally here.

The user requested realistic nightly black-box tests, relevant live checks for
each implemented slice, and a larger **business/financial** corpus. Added
[#53](https://github.com/mohripan/flint-graph/issues/53) and
[#54](https://github.com/mohripan/flint-graph/issues/54), with a pinned public FinQA
release, separate answer annotations, license/provenance and bounded downloads.
Synthetic success above is not a claim of financial-domain or production quality.
