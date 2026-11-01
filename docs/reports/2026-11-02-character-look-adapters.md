# Reviewed-character adapters and anatomy review

Date: 2026-11-02. Implements ADR 0051, a product slice of #184 on the installed
klein pose renderer. It adds character/look training to the private style-training
path without changing game packages, runtime versions, model dependencies or
ordinary project-style requests.

## Delivered

Characters → Poses → Character look training explicitly selects 4–12 approved
same-character/outfit images, including the reviewed base. Captions start with
reviewed look tags and must be edited/reviewed for each actual pose/scene. The
creator confirms the same look, checks anatomy/hands/feet/limb count, and confirms
training rights. Foreign characters, CG/background sources, missing or discarded
bases and foreign workspace/project resources are refused.

Migration 0038 adds a private sidecar with scoped training-job and character/look
foreign keys and a frozen look snapshot. The dataset hash includes the reviewed
look hash and confirmations. Old project-style jobs and idempotency hashes remain
valid. Listings fetch target metadata in a batch. The existing fenced ledger,
registered Temporal run, cancellation/recovery, rank-4 trainer and private
create-only safetensors store are reused.

Trained rendering version offers project styles and completed versions for this
exact reviewed look. Admission and training/render retries check the immutable
target and approved base; a different outfit/look never silently inherits the
weights. PNG provenance includes adapter kind, reviewed-look hash and the existing
version/weight hash/strength. One adapter is selected per pose; independent
character/style stacking is not enabled. Weights remain outside ordinary assets
and games, with no public weight download route.

MLflow separates `flint-character-look` and `flint-project-style` runs with an
allowlisted kind parameter. The live character run reached FINISHED. Numeric
loss/resource metrics and opaque hashes are mirrored; names, tags, inputs,
captions, prompts and weights are not uploaded. PostgreSQL/private storage remain
authoritative, and tracking failure does not fail training.

## Extra-leg feedback and real qualification

The creator observed that the previous seated Aster preserved identity/clothes but
had an extra hanging boot/third leg. This is a separate anatomy failure; identity
or clothing similarity does not certify it. The old candidate was preserved with
review notes and excluded from this training set. Two replacement seated
candidates were generated with clearer leg/chair geometry; the first has two
clearly visible legs and boots. They remain candidates for creator approval.
See the [replacement](character-look-adapters-2026-11-02/seated-replacement.png).
This is regeneration and manual inspection, not an automatic anatomical repair
or limb-count detector.

The new training dataset uses four explicitly selected synthetic QA sources of
Aster in the travel coat: the approved base, a rear view, the inspected seated
replacement and a wave. A receipt asserts the rejected image's hash is absent.
These are agent selections, not creator-calibrated scores. No real Studio
projects were opened. A new random task-owned database, project and queues used
API 8278, frontend 5278 and preview 5298, preserving the existing Studio and the
Aster QA application on 5276 while the creator was viewing it.

A real browser-submitted **200-step** character run completed in **265.578 s** on
the RTX 5070 Ti Laptop 12 GB GPU. Peak Torch allocation was **7.87 GiB**;
dedicated device use after training was about **8.45 GiB**. Host RSS at completion
was about **2.06 GiB**, not peak host RAM. The existing exact base manifest,
rank/alpha four, 512²-area aspect buckets, bf16 frozen weights, FP32 LoRA parameters,
gradient checkpointing, cached text/latents and 8-bit Adam recipe were preserved.
Four is the tested dataset size and admission minimum, not a measured quality
threshold or proof that four images suffice for every character.

The browser selected that completed version at strength 0.5 and generated a
walking pose, which was not a training pose. Rendering completed in **69.844 s**,
with about **9.20 GiB peak Torch allocation**. The [walking result](character-look-adapters-2026-11-02/walking.png)
has two visible legs and preserves the broad white-hair/red-eye/navy-coat/red-scarf
look. Costume trim, fingers, linework and lighting still require review. This
single result does not establish a measured improvement over the baseline.
The [safe receipt](character-look-adapters-2026-11-02/qualification.json) records
exact dataset/model/recipe/weight/look hashes and runtime measurements, with no
private object keys or weights.

A real request with this version and another reviewed look returned 422 before
rendering. The browser hid the incompatible version and offered it again after
restoring the original look. Checks also covered anatomy-review gating, explicit
selection/caption review, progress, frozen target disclosure and result provenance.
See [training review](character-look-adapters-2026-11-02/studio-dataset.png),
[result controls](character-look-adapters-2026-11-02/studio-result.png) and
[mobile](character-look-adapters-2026-11-02/studio-mobile.png). At 390 px the document
width remained 390 px; scoped axe reported no violations/incomplete checks, and
browser errors were absent.

## Verification

Meaningful API, model-tracking and frontend request/compatibility tests failed
before the new behavior was implemented. Full offline tests passed **1,983 / 124
gated skips**, broad PostgreSQL qualification **237 / 1 skip**, real pinned
Godot/preview **33 / 1 skip**, frontend **131**, and child contract tests **7**.
Ruff, mypy (293 modules), SQL generation, Compose config, prompt-lock compatibility,
offline Acme evaluation and frontend type/build checks passed. PostgreSQL live
upgrade/downgrade/upgrade ran on fresh random databases in the task-owned fixture.
The required gates are repeated after rebasing before pushing.

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
uv run python notes/run-look-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py tests/integration/test_narrative_styles_api.py tests/integration/test_narrative_character_adapters.py -q --tb=short
uv run python tools/narrative/build_preview.py --engine C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe --templates C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates --parent-origin http://localhost:5278 --output C:/Projects/flint-graph-codex-character-studio/notes/character-adapter-preview
uv run python notes/regenerate-anatomy.py
uv run python notes/prepare-character-studio.py
uv run python tools/narrative/studio.py --config notes/studio-character-qa.env
uv run python notes/prepare-character-fixture.py
uv run python notes/qualify-character-training.py
uv run python notes/qualify-character-pose.py
uv run python notes/qualify-character-compatibility.py
uv run python notes/apply-character-migration.py
```

Ignored wrappers retain private operator values and stderr; they create/drop only
random task-owned test databases. Offline skips gate external services/models;
real GPU qualification above was executed separately. The PG skip is the SQLite
variant of a PG-lock test; the Godot skip requires an explicit owned prepared
builder. No Linux GPU run, Animagine character training, CCIP calibration,
automatic anatomy/identity score, independent adapter stacking or SDXL CG adapter
compatibility is claimed. These remain separate #184/M40 work.

Migration **0038_character_adapters** was applied to the owned Studio database
after aggregate image/voice/assistant/release/style activity counts were all zero;
scoped foreign keys were verified. Existing Studio and Aster QA processes were
preserved, with rollout pending their owner's coordinated reload. The new isolated
Studio demonstrates the feature meanwhile. No main-checkout, assistant-owned,
imagegen/CG-owned, voice-owned, trace-probe or shared story-types implementation
files were changed.
