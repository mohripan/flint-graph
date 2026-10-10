# Explicit developer profiles

Implemented for [#49](https://github.com/mohripan/flint-graph/issues/49), under
[ADR 15](../adr/0015-reproducible-developer-experience.md). Use one model overlay,
an existing dedicated evaluation workspace, and public APIs. Nothing creates a
workspace implicitly, downloads models, deletes data or resets volumes.

## Offline models

```text
docker compose -f compose.yaml -f compose.offline.yaml config --quiet
docker compose -f compose.yaml -f compose.offline.yaml up --build -d
uv run flint-graph-dev check --profile offline --workspace-id YOUR-WORKSPACE-UUID
uv run flint-graph-dev bootstrap --profile offline --workspace-id YOUR-WORKSPACE-UUID
```

Create/select a dedicated workspace through the existing UI/API first; replace
the UUID placeholder. `check` only reads. `bootstrap` requires admin/owner and
uses an existing compatible visible index. If no visible active index exists,
it uses the guarded idempotent public bootstrap API. An incompatible active
index stops the command instead of switching/deprecating it. The API advertises
guard support; older APIs cannot be used to create an index through this tool.
The guard checks the workspace's active index under the existing PostgreSQL row
lock, protecting against an index appearing between preflight and mutation.

Offline explicitly selects deterministic extraction, 384-dimensional fixture
embeddings, answers and support checking across API, worker and relay. It means
**no external model calls**, not zero local networking or image downloads.
Compose services/images and Python dependencies must already be available for
a completely disconnected setup. Deterministic answers/embeddings are protocol
fixtures, not meaningful model-quality evidence. Unlike doctor `--offline`, the
profile's `check` still contacts your running local API.

## Local-real models

Choose models already installed in Ollama. Use explicit tags and confirm the
embedding model's actual dimensions from its provider documentation. No model
is prescribed or downloaded by this tool. PowerShell:

```powershell
$env:FLINT_GRAPH_LOCAL_EMBEDDING_MODEL = "YOUR-INSTALLED-EMBEDDING-MODEL:TAG"
$env:FLINT_GRAPH_LOCAL_EMBEDDING_DIMENSIONS = "YOUR-MODEL-DIMENSIONS"
$env:FLINT_GRAPH_LOCAL_ANSWER_MODEL = "YOUR-INSTALLED-ANSWER-MODEL:TAG"
$env:FLINT_GRAPH_LOCAL_SUPPORT_MODEL = "YOUR-INSTALLED-SUPPORT-MODEL:TAG"
docker compose -f compose.yaml -f compose.local-real.yaml config --quiet
docker compose -f compose.yaml -f compose.local-real.yaml up --build -d
```

Unix shells use `export NAME=value` for those four variables, followed by the
same Compose commands. `FLINT_GRAPH_LOCAL_OLLAMA_URL` optionally overrides the
default `http://host.docker.internal:11434`; container host-gateway mappings are
included for Linux. Ollama must be reachable from the containers, not merely
from the shell. Do not expose an unauthenticated inference server publicly.
Keep API/worker/relay on the **same** selected overlay. Actual worker settings are
not inferred from API configuration; a real ingestion smoke verifies their path.

Record the installed model fingerprints through the authorized public API:

```text
uv run flint-graph-dev lock --profile local-real --workspace-id YOUR-WORKSPACE-UUID --output notes/local-models.lock.json
uv run flint-graph-dev check --profile local-real --workspace-id YOUR-WORKSPACE-UUID --model-lock notes/local-models.lock.json
uv run flint-graph-dev bootstrap --profile local-real --workspace-id YOUR-WORKSPACE-UUID --model-lock notes/local-models.lock.json
```

Review the lock, then retain it with the evaluation report. It pins the explicit
model names, SHA-256 inventory digests and declared embedding dimensions.
`lock` is a read-only API operation with an explicit local output file; existing
files are never overwritten. Missing models/digests, untagged names, changed
models/dimensions/digests, unknown hosted providers and incompatible indexes fail
before setup mutation. Tags can move, so name alone is not a pin. This fingerprint
is a preflight snapshot, not server-side enforcement of immutable model storage.
Do not update an installed model during preparation/evaluation. A changed digest
requires an intentionally recorded/reviewed new lock, not silent acceptance.

Local-real covers **embeddings, answers and support**, not extraction quality:
extraction remains explicitly deterministic to avoid an unpinned fourth model.
Declared dimensions are compared with the index; inventory checks do not run an
embedding to measure intrinsic dimensions. The opt-in ingestion smoke checks the
adapter's actual vector length. A different embedding model/dimension requires
a separately chosen compatible index and explicit backfill; this command will
not change an existing incompatible index. Prefer a new dedicated evaluation
workspace when changing models.

No cloud key is needed by these two profiles. Local models still use hardware,
electricity and hosting resources. Hosted Anthropic/OpenAI-compatible profiles
are not included: API settings can incur provider charges, so use the existing
explicit provider setup and an approved budget instead of treating them as
offline/local-real fallbacks. OIDC credentials remain independent: read a valid
bearer token from `FLINT_GRAPH_API_TOKEN` or `--token-env NAME`, never the URL.
Remote APIs require HTTPS; redirects and ambient proxy credentials are disabled.

## Optional tiny corpus and fresh queries

Bootstrap uploads **nothing** unless `--smoke-corpus` is supplied:

```text
uv run flint-graph-dev bootstrap --profile offline --workspace-id YOUR-WORKSPACE-UUID --smoke-corpus --dataset evals/datasets/acme-smoke --output notes/smoke-first.json
uv run flint-graph-dev bootstrap --profile offline --workspace-id YOUR-WORKSPACE-UUID --smoke-corpus --dataset evals/datasets/acme-smoke --output notes/smoke-second.json
uv run flint-graph-eval capture --dataset evals/datasets/acme-smoke --manifest notes/smoke-first.json --base-url http://localhost:8000 --output notes/smoke-fresh.jsonl --git-sha YOUR-DEPLOYED-REVISION
```

For local-real, substitute the profile and add `--model-lock PATH`. Every output
must use a new filename. Tiny smoke input is limited to ten files/1 MiB total,
with the existing contained-path/format/byte validation. It reuses M16
preparation: immutable uploads, job and positive-chunk coverage polling, and
both lexical/vector projection visibility probes. Preparation is bounded by
`--prepare-timeout` (default 600 seconds, maximum 1800).

Repeated unchanged uploads use stable workspace/dataset/label/content-derived
idempotency keys and return the same document/version/job identities. Changed
bytes create a new immutable version of the same namespaced logical source.
Failures leave inspectable state and never delete/resurrect a failed or deleted
document; retrying an unchanged failed key does not invent a fresh attempt.
If the selected active index changed, preparation stops without switching it.
Normal uploads can still observe a concurrent operator index change; keep setup
stable during the smoke and inspect coverage after interruption.

The capture-compatible manifest records the selected profile, model lock and
approved effective configuration. Capture is separate and opt-in: it executes
queries and, for local-real, real model inference. Its bearer-token variable is
`FLINT_GRAPH_EVAL_TOKEN` (or its own `--token-env`). Neither command overwrites
reviewed baselines. A successful setup smoke does not establish useful answers;
inspect fresh quality scores and the [nightly black-box issue #53](https://github.com/mohripan/flint-graph/issues/53).

Adding Phoenix uses the existing AI overlay **after** the model overlay:
`-f compose.yaml -f compose.offline.yaml -f compose.ai-observability.yaml --profile ai-observability`.
Substitute local-real as needed. See [AI observability](ai-observability.md) for
privacy, budgets and local-only boundaries. See the
[delivery report](../reports/2026-10-10-developer-profiles-delivery.md) for exact
live checks and unverified local-real hardware/model behavior.
