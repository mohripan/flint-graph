# Character and project-style adapters in one pose

Date: 2026-11-02. Implements ADR 0052, a bounded continuation of #184/#185.
The Studio now combines a trained version of the exact reviewed character look
with a separately trained project style. No game format/runtime version, model
pin, ML dependency or creator project was changed.

## Delivered behavior

With `NARRATIVE_POSE_MAX_ADAPTERS=2`, Characters → Poses offers **Trained character
look** and **Project style**, each with its own strength. Both selections and
weight hashes are frozen when Generate is pressed. Strengths are 0.1–1 and the
combined total is bounded to 1; the form blocks an excessive total and explains
how to reduce it. This is an initial influence bound, not a measured optimum.
[Selected controls](combined-pose-adapters-2026-11-02/studio-selected.png),
[excess-strength rejection](combined-pose-adapters-2026-11-02/studio-strength-bound.png),
[results with both versions](combined-pose-adapters-2026-11-02/studio-results.png)
and [mobile controls](combined-pose-adapters-2026-11-02/studio-mobile.png) show the flow.

The optional `character_adapter` API role requires a completed character adapter
for this exact character/look/approved base. When present, `style_adapter` requires
a project style. Both must belong to this project/workspace and match the exact
installed klein manifest. Wrong roles, duplicate versions, wrong looks/models,
unavailable versions and excessive strengths are refused. The additional scoped
sidecar (migration 0039) has four foreign keys, including a character-training
binding. Worker retries recheck target, scope, model, private bytes and training
metadata. A replay returns its original admitted job even after admission is
switched off; old request hashes and legacy character versions selected through
`style_adapter` remain valid.

Closed child protocol 4 transfers the character and optional style in fixed
order under fixed private filenames. Weight/dataset/recipe hashes and strengths
are checked; paths, extra fields, duplicate roles/hashes, nonfinite or boolean
strengths and unbounded combinations are refused. Diffusers/PEFT loads two named
adapters and applies their individual weights. PNG provenance records both roles,
versions and hashes. Existing protocols 1–3 and the default single chooser remain
supported. Weights stay outside ordinary assets, public download routes, tracking
artifacts and games.

## Real qualification and limitations

A fresh random QA database/project and unique queues ran on API 8280, frontend
5280 and preview 5300. The creator's projects were not opened. Character training
used four agent-reviewed synthetic Aster sources: base, rear view, corrected
seated reference and wave. The earlier extra-boot candidate was excluded by hash.
Project-style training used three of those sources plus Nera to exercise a
separate dataset/version. These are agent selections, not creator calibration.

Both actual 200-step runs completed on the RTX 5070 Ti Laptop 12 GB GPU:
character **286.297 s**, project style **272.469 s**, each with **8,448,426,496 B
(7.87 GiB) peak Torch allocation**. Both MLflow runs reached FINISHED. The browser
selected character 0.6 and style 0.4, requested two opaque seated candidates and
submitted the real job. Both private versions were loaded, as confirmed by child
and worker provenance, with matching executed child/protocol source hashes.
The job completed in **80.844 s**, with **9,885,839,360 B (9.21 GiB) peak Torch
allocation**. Completion host RSS was about **1.26 GiB**, not peak host memory.
The [safe receipt](combined-pose-adapters-2026-11-02/qualification.json) records
exact model/dataset/recipe/weight/look hashes, seeds, runtime measurements and
manual observations, without private object keys or weights.

[Candidate 0](combined-pose-adapters-2026-11-02/seated-0.png) has two visible legs
and boots and both hands visible. [Candidate 1](combined-pose-adapters-2026-11-02/seated-1.png)
has a malformed hand merging into the thigh. Both broadly preserve the white
hair/red eyes/navy coat/red scarf look; garment trim, fingers, chair geometry and
rendering still need review. The second was explicitly marked as failing anatomy
and excluded from training in its review notes. Both remain unapproved. This
qualifies combination and memory use; it does not establish measured quality
improvement or guarantee anatomy, outfit details, linework or lighting. The
seated pose was represented in the training sources, so it is not a held-out
quality benchmark. No automatic limb detector is claimed.

The browser verified the bounded strength control, independent selection,
disabled controls while generating and both version labels in results. At 390 px,
document width stayed 390 px. Scoped axe 4.12.1 checks reported zero violations
and zero incomplete checks on desktop and mobile; browser errors were absent.

The first training attempt correctly stopped with `host_memory_busy`. After the
creator explicitly authorized pausing Studio, the main launcher was stopped only
after all five aggregate job groups were idle. An initial PostgreSQL run also hit
the task-owned 384 MiB fixture's memory limit (254 passes, two connection errors
during recovery). No existing container was stopped or reconfigured. A separate
768 MiB test-only PostgreSQL fixture on loopback 6194 completed the entire suite.
These resource failures were rerun, not counted as passing checks.

Migration **0039_pose_adapter_stacks** was applied to the main Studio database
with idle counts and all four new foreign keys verified. After qualification,
only the new 8280/5280/5300 QA launcher was stopped. The main Studio was restarted
with the existing private settings/queues/model pins and `MAX_ADAPTERS=2`;
API 8101 `/health/live`, frontend 5173 and preview 5192 `/index.html` returned 200.
The earlier Aster QA (8276/5276/5296) and character QA (8278/5278/5298) stayed running,
and their API liveness checks passed. No external model service or existing
Docker container/volume was stopped. The launcher reported all services ready.

## Verification

API, child-transfer, closed-protocol and frontend request tests failed before
the corresponding behavior was implemented. Full checks passed before commit:
**1,993 Python tests / 124 external-service skips**, **255 PostgreSQL tests / 1
skip**, **33 real Godot/preview tests / 1 skip**, **132 frontend tests**, and **8
child contract tests**. Ruff, mypy (294 modules), SQL generation, Compose config,
prompt-lock compatibility, offline Acme evaluation and frontend type/build checks
passed. Full checks are repeated after rebasing before the master fast-forward.

Exact passing commands, from `C:\Projects\flint-graph-codex-character-studio`:

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
uv run python notes/run-stack-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py tests/integration/test_narrative_styles_api.py tests/integration/test_narrative_character_adapters.py tests/integration/test_narrative_pose_adapters.py -q --tb=short
uv run python tools/narrative/build_preview.py --engine C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe --templates C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates --parent-origin http://localhost:5280 --output C:/Projects/flint-graph-codex-character-studio/notes/stack-adapter-preview
uv run python notes/prepare-stack-studio.py
uv run python tools/narrative/studio.py --config notes/studio-stack-qa.env
uv run python notes/prepare-stack-fixture.py
uv run python -X utf8 notes/qualify-stack-training.py
uv run python -X utf8 notes/qualify-stack-pose.py
uv run python -X utf8 notes/review-stack-results.py
uv run python -X utf8 notes/apply-stack-migration.py
uv run python tools/narrative/studio.py --config notes/studio-active.env
uv run python -X utf8 notes/qualify-stack-main.py
```

Ignored wrappers retain private operator values/stderr and create/drop only
random test databases. PostgreSQL live upgrade/downgrade/upgrade passed. The PG
skip is the SQLite variant of a PG-lock test; the Godot skip requires an explicit
owned prepared builder. Offline skips gate external services/models; real GPU
qualification above ran separately. No Linux GPU run, Animagine/SDXL CG adapter
compatibility, creator-calibrated comparison or automatic anatomy score is
claimed. Those remain separate work; this slice does not close all of #184/M40.
