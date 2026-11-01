# Private project style adapters and optional MLflow

Date: 2026-11-02. Implements ADR 0050 as a usable slice of #184. The API, dedicated
Temporal training worker, private model storage, pose renderer and Studio controls
are connected. This does not complete character-specific LoRA training, CG-model
integration or creator-calibrated style/lighting evaluation.

## Delivered behavior

Look → Project art style explicitly selects 4–12 distinct approved project images,
requires reviewed content captions and training-rights confirmation, and queues
20–400 updates with an explicit seed. The scoped immutable dataset records source
IDs/hashes/sizes/licenses, captions and policy/prompt-bundle identities. Replay uses
the creator's original request, so later policy changes cannot silently resample
or replace an admitted training job. Workspace admission permits one active
training job; jobs and cancellation survive view changes.

A separate opt-in Temporal worker registers the exact run before claiming an
attempt. Attempt number and execution token fence progress and publication;
cancellation stops that child's descendants, and recovery closes only an observed
closed registered run. Training uses the pinned klein pose base, rank/alpha four,
512² area buckets, batch one, cached text/latents, frozen bf16 weights, FP32 LoRA
parameters, gradient checkpointing and 8-bit Adam. No other model is unloaded.

Only validated finite paired rank-4 FP32 safetensors can publish. Create-only
private objects are outside game assets and release paths, with no public weight
download endpoint. Characters → Poses selects a completed version and strength,
and freezes its weight/base/dataset/recipe hashes. The child receives a fixed
private file and verified hash, loads it into the actual klein renderer, and
records the version used. Existing no-adapter poses and child protocols 1/2 remain
valid; optional style transfer uses protocol 3. The game format/runtime does not
change; the exported result is still an ordinary PNG.

Optional MLflow 3.17.2 runs in its own locked environment. The worker uses bounded
REST calls to mirror numeric loss steps, time/memory, image count and opaque
job/base/dataset/recipe/weight hashes. It does not upload images, captions, prompts,
paths or weights, and does not enable autologging. A live run reached FINISHED
with all 200 loss steps recorded. PostgreSQL and private storage remain authoritative;
tracking failure never fails training, and a crash after publication can omit the
mirror. The root dependency lock/OTel versions are unchanged. Langfuse continues
to own reviewed prompt/config authoring. See the [MLflow REST contract](https://mlflow.org/docs/latest/api_reference/rest-api.html).

## Real model and browser qualification

All inputs came from an explicitly selected synthetic QA dataset, in a new random
QA PostgreSQL database and project, on distinct API/frontend ports 8276/5276 and
separate Temporal queues. No creator projects were opened. Four images included
two original fixture characters and two reviewed same-rendering source variants;
these are agent selections, not creator quality labels. The private dataset and
source rights are not promoted into a blanket adapter license.

The real 200-step run saved a **16,728,296-byte** adapter in **270.329 s**, with
**7.87 GiB peak Torch allocation** and about **8.45 GiB dedicated device use after
training** on the RTX 5070 Ti Laptop 12 GB GPU. Host RSS at completion was about
1.08 GiB; that is not peak host RAM. A final-code 20-step run completed in
86.516 s, rechecking policy metadata, child/protocol/dependency-lock hashes,
private publication and live MLflow logging. The safe [receipt](private-style-adapters-2026-11-02/qualification.json)
contains exact hashes and loss histories; weights remain private.

A browser-submitted seated pose used the 200-step version at strength 0.5.
The same prompt, source and seed 1082396500 were then run without an adapter.
The [comparison sheet](private-style-adapters-2026-11-02/matched-seed.png) shows
finer outlines with this adapter in this sample, while costume fasteners, body/chair
composition and shading still differ. This is one agent visual observation, not
proof of reliable style or lighting preservation. Identity/outfit/lighting quality
still needs creator-reviewed datasets and broader held-out checks. Training loss
is not an image-quality metric.

The browser qualified image/caption selection, rights gating, real submission,
progress across views, cancellation, completed version selection, strength,
reference disclosure and result generation. See [dataset review](private-style-adapters-2026-11-02/studio-dataset.png),
[pose controls](private-style-adapters-2026-11-02/studio-pose.png) and
[mobile](private-style-adapters-2026-11-02/studio-mobile.png). At 390 px, document
width remained 390 px; scoped axe reported zero violations/incomplete checks for
training and pose controls, and browser errors were absent.

## Verification

Tests preceded the new request, training-child, publication, tracking, selection,
configuration and recovery behavior. Checks cover scopes/roles, source approval,
rights, replay under changed policy, quotas, registered-run recovery, cancellation,
stale runs, strict tensor publication, adapter-backed pose execution and fail-open
numeric-only tracking. Real PostgreSQL upgrade/downgrade/upgrade passed on a random
task-owned database. Offline qualification covers **1,976 passing tests / 124 gated skips**,
**225 PostgreSQL tests / 1 skip**, **33 real Godot/preview tests / 1 skip**,
**129 frontend tests**, **2 real pose-model tests**, and **7 child contract tests**.
Ruff, mypy (291 modules), SQL generation, Compose config, prompt-lock compatibility,
offline Acme evaluation and frontend types/build passed. The required full gates
are repeated after rebase before pushing.

From `C:\Projects\flint-graph-codex-character-studio`:

```powershell
uv run pytest -q --tb=short
uv run ruff check .
uv run mypy
$env:FLINT_GRAPH_ENV='test'
uv run alembic upgrade head --sql
docker compose config
npm test --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
uv run flint-graph-prompts check --base-ref origin/master
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run python -m unittest discover -s runtimes/stylegen -p test_contract.py
uv run python -m unittest discover -s runtimes/posegen -p test_contract.py
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
uv run python notes/run-look-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py tests/integration/test_narrative_styles_api.py -q --tb=short
uv sync --project runtimes/stylegen
uv sync --project runtimes/posegen
uv sync --project runtimes/modeltracking
uv run python notes/run-style-real.py
uv run python notes/run-style-pose.py
uv run python notes/prepare-style-studio.py
uv run python tools/narrative/studio.py --config notes/studio-style-qa.env
uv run python notes/qualify-live-style.py
uv run python notes/qualify-final-style.py
uv run python notes/style-baseline.py
uv run python notes/run-views-live-test.py
uv run python notes/apply-style-migration.py
```

The ignored wrappers hold private operator settings, create/drop only random
owned QA databases, and retain private stderr separately. The pose-live wrapper
sets the installed private pins plus `FLINT_GRAPH_NARRATIVE_POSE_LIVE=1` and a
selected synthetic secondary image, then invokes the real pose live tests.
The MLflow server was loopback-only at 6096; its readback verified FINISHED and
numeric metrics without input/artifact uploads. No Linux GPU training, multi-node
GPU admission, automatic quality threshold, character-specific LoRA or SDXL CG
adapter compatibility is claimed. Abandoned private attempt-object cleanup is not
implemented. These limitations do not block the explicit local training/pose flow.

## Rollout

Additive migration **0037_private_styles** was applied to the active owned Studio
only after aggregate image/voice/assistant/release activity counts were all zero.
Its scoped foreign keys were verified. The existing launcher/API/preview/frontend
were preserved, and private style-worker/queue configuration is prepared for the
next owner-managed coordinated reload. The separate QA Studio demonstrates the
new feature while the existing Studio remains running. API, compatible pose
worker/child and style worker must roll out together before admitting adapters.
The main checkout and assistant/CG/audio-owned implementation files were untouched.
