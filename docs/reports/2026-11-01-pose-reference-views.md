# Approved pose views and primary rendering guidance

Date: 2026-11-01. [ADR 0049](../adr/0049-approved-pose-reference-views.md), #185
implementation continuation after the model-backed pose feature.

## Delivered behavior

A pose can now use its primary reviewed look plus one explicitly chosen approved
view labelled front, side, back or detail. Studio requires same-character/outfit
confirmation. History shows **References used** with frozen names and thumbnails;
active jobs show their fixed inputs. Selection remains optional and the operator
cap defaults to one reference (`FLINT_GRAPH_NARRATIVE_POSE_MAX_REFERENCES=2`
enables the new flow after rollout).

Migration 0036 adds ordered source snapshots with workspace/project/asset/job
foreign keys, primary/extra role constraints and duplicate-asset protection.
Admission verifies approval, character ownership, image kind, size and source
identity. Different selection/view under one request key conflicts. Omitting the
new field and sending an empty list preserve the old single-reference request
identity. Pre-0036 jobs without reference rows still execute and display correctly.
The worker checks both source hashes/approval and stores the ordered reference
manifest hash in private candidate provenance. Ordinary game assets remain PNGs.

The isolated child accepts protocol 2 with two hashes and fixed private filenames;
protocol 1 remains accepted. Only the extra view is fitted within 512×512 with
Lanczos, keeping the qualified primary preprocessing. The exact input sizes,
source hashes and preprocessing identity are recorded. Rendering remains the same
pinned FLUX.2 klein 4B model, bf16 staging, four steps, guidance 1 and 768×1152.
No weights are trained, no model is silently substituted, and no story/runtime
format changes are needed.

The creator's screenshots raised a distinct problem: matching identity does not
establish matching ink weight, shading, palette or light direction. Single-view
pose prompt **v2** and the new `narrative.image.pose_views` entry explicitly request
the primary's rendering. The extra supplies shape/garment details without style
blending. Old prompt versions/bundles remain available and existing admissions
keep their stored prompts. These are instructions, **not a style/lighting lock**.
The preserved typed image policy and its model-specific negative-conditioning
limitation are unchanged.

## Real evidence and limits

The existing Studio on 8101/5173 was kept running during qualification. A separate
real instance used API **8276**, frontend **5276**, its own random PostgreSQL
database in the task-owned PG container, its own Temporal queue and new scoped
MinIO keys. Only synthetic Aster fixtures were opened/modified; no creator project
was used. Migration 0036 was applied to that isolated database and exercised by the
fresh upgrade/downgrade/upgrade tests. Migration 0036 was also applied to the
configured Studio after all job queues were confirmed idle, and the two-view opt-in
was prepared in its private task-owned configuration. Its running authoring
processes were not restarted: activation of the new API/prompt bundle awaits the
next coordinated reload, preserving the current playtest.

The HTTP → PostgreSQL → Temporal worker → GPU → verified MinIO download completed
with a **665×1137 RGBA** candidate. It used the original 832×1216 primary plus an
approved seated detail image, resized to 334×512. The job followed the wave request
and retained the main white hair, red eyes, blue coat, gold trim and red scarf.
Fine details still varied, and **outlines remained heavier than the primary**.
This is execution qualification, not proof that the rendering complaint is solved.
A quantitative style claim, creator rating, style LoRA or lighting guarantee would
require separate evidence. Face-only expression repainting remains preferable
when body/outfit pixels should remain identical.

The [receipt](pose-reference-views-2026-11-01/qualification.json) records exact
source hashes, input sizes, model/code/preprocessing identities and output hash.
Child time was **72.297 s**, peak Torch allocation about **9.19 GiB**, device use
after rendering **10.52 GiB**, resident host memory at completion **2.88 GiB**
(not peak). Existing 11 GiB dedicated-GPU / 6 GiB host admission floors remain;
these checks are observations, not resource reservations.

Browser checks covered an unconfirmed selection disabling Generate, explicit
confirmation, real job submission, navigation preserving progress, cancellation,
frozen reference disclosure and review. At 390 px the document width stayed
390 px; scoped axe reported zero violations/incomplete checks and console errors
were absent. See the [references/result](pose-reference-views-2026-11-01/references-and-result.png)
and [mobile panel](pose-reference-views-2026-11-01/studio-mobile.png).
No new export/preview artifact or builder image is required; PNG binding/export is
unchanged and native runtime/preview conformance was rerun.

## Verification and commands

Tests preceded new behavior: two-reference admission/execution, legacy replay,
closed protocol/hash transfer, confirmation/selection and rendering instructions.
The complete offline suite passed **1,957 / 124 skips**. Task-owned PostgreSQL
passed **207 / 1 skip** with live upgrade/downgrade/upgrade. Pinned Godot/preview
passed **33 / 1 skip**. Real model tests passed **2**, protocol tests **4**,
frontend tests **127**. Ruff, mypy (281 source files), prompt-lock compatibility,
SQL generation, Compose config, offline Acme evaluation and frontend types/build passed. The required gates
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
uv run python -m unittest discover -s runtimes/posegen -p test_contract.py
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
uv run python notes/run-look-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py -q --tb=short
uv run python notes/run-views-live-test.py
uv run python notes/apply-views-migration.py
uv run python notes/prepare-views-studio.py
uv run python tools/narrative/studio.py --config notes/studio-views-qa.env
uv run python notes/qualify-live-views.py
```

Private wrappers remain ignored. The PG wrapper creates/drops only a random
task-owned test database. The live-model wrapper supplies private installed model
pins and `FLINT_GRAPH_NARRATIVE_POSE_LIVE=1`, plus an explicitly selected synthetic
`FLINT_GRAPH_NARRATIVE_POSE_LIVE_SECONDARY`, then invokes `python -m pytest
tests/integration/test_narrative_pose_live.py -q --tb=short`. Browser sessions are
named and isolated. Offline skips cover explicitly gated external services/model
runs, including these two GPU tests executed separately. The PG skip is the SQLite
variant of the PG-only concurrency case; the Godot skip is the prepared-builder CG
gate. Other model families, Linux GPU execution, per-person CG scoring and LoRA
training were not run or claimed. Existing assistant/CG/audio-owned paths and the
main checkout remained untouched.
