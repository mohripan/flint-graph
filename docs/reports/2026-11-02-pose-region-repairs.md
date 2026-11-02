# Region repairs for pose candidates

2026-11-02 · ADR 0054 · migration 0041 · #182/#185.

Characters → Poses adds **Repair area…** to available completed pose candidates.
Select a small rectangle, describe the correction and generate 1–2 new candidates.
The source can be unapproved. Its reviewed look and original character/style
versions remain frozen, and new images still require manual approval and anatomy
review. Drag, keyboard movement/resizing and native-pixel numeric controls work
in the existing Studio dialog. The action is hidden unless the API advertises
its opt-in capability.

The pinned klein editor receives the source and approved look. This is reference
editing followed by deterministic local compositing, rather than a mask-native
model. Only pixels inside the chosen region can change; an eight-pixel inward
feather blends its edge. Transparent crops reconstruct the original 768×1152
canvas for inference, then restore the exact native crop. The parent separately
decodes bounded PNGs and verifies every outside RGB/RGBA byte, dimensions and crop.
It rejects changed alpha and color-key transparency tricks. No model prompt,
content-policy, game format or runtime pin changes.

The scoped sidecar freezes source/hash/size/crop/region/instruction. Admission
inherits adapter versions and rejects wrong character, unavailable source, model
and weight pins. Worker retries recheck references; discarded sources never reach
the model. Old pose protocols 1–4 and replay hashes remain supported. Identical
repair replays return their admitted job even after disabling the flag. No creator
project was opened or edited during qualification.

## Qualification

The isolated QA project reused its approved Aster look and actual 200-step
character/style versions at strengths 0.6/0.4. A registered Temporal pose job
repaired the malformed hand in a 768×1152 opaque candidate. Both outputs retained
all **862,986 outside pixels** exactly, while changing more than 21,000 inside
pixels. The two-candidate run took **95.297 seconds**, with peak CUDA tensor
allocation **9,886,088,192 bytes**. The [comparison](pose-region-repairs-2026-11-02/opaque-hand-comparison.png)
shows the complete outcome: candidate 0 has a conspicuous seam; candidate 1 visibly
recovers the missing hand. Neither was approved or automatically marked anatomy-safe.
This is a local correction capability, not an anatomy-quality guarantee.

A second real job generated a transparent source, followed by a registered repair.
The repair retained its **628×1129 RGBA** dimensions and original canvas crop
`[100,23,728,1152]`. All **697,812 outside pixels**, including **448,385 nonopaque
pixels**, were identical. More than 10,000 inside pixels changed. Correction after
proper alpha-composite inspection: the raw RGBA preview exposed hidden RGB bleed;
white/dark composites show no striped fringe. See the
[composite evidence](standing-walking-guides-2026-11-02/alpha-composites.png).
This run qualifies crop/alpha preservation and does not claim
better anatomy or whole-sprite cutout quality. An independent Pillow check of the
stored original/output files agreed with the parent decoder for all three repairs.
The [safe receipt](pose-region-repairs-2026-11-02/qualification.json) records hashes,
seeds, frozen trained versions, changed/unchanged counts and measured resources.

The [desktop dialog](pose-region-repairs-2026-11-02/studio-repair-area.png) was exercised
through the real frontend: numeric coordinates, arrow movement, candidate count,
correction and durable job admission. The [390 px dialog](pose-region-repairs-2026-11-02/studio-repair-mobile.png)
remained within a 390 px document. Desktop/mobile dialog axe checks reported zero
violations and zero incomplete checks. The surrounding pre-existing navigation
rail has one contrast rule failure on its small section labels; this is recorded
rather than counting the whole page as accessible. No browser failures were found
in the new controls.

Early attempts respected `host_memory_busy`. After confirming all five main job
groups were idle, the creator-authorized main Studio pause and a task-only API/pose
QA launch freed sufficient memory without weakening the guard. No container or
external model service was stopped. One successful opaque run's initial download
probe used the wrong URL and received 404; fetching the existing stored images
through `/assets/{id}/content?variant=image` passed without rerendering.

Main migration **0041_pose_repairs** and all five foreign keys were verified.
Only the completed task-only repair QA launchers were stopped; their data remains.
Studio restarted with its existing private configuration/queues/model pins and
repairs enabled. API 8101, frontend 5173, preview 5192 `/index.html`, and both earlier
QA APIs 8276/8278 returned 200. The repair endpoint is present in the main API schema.
Creator projects were not opened or changed. The standard deployment default
remains off and requires coordinated API/worker protocol-5 rollout.

## Verification

API, child protocol, independent pixel checks and editor request/geometry tests
failed before their corresponding implementation. The tests cover unapproved
sources, inherited versions, replay conflicts/compatibility, source scope and
availability, bounded rectangles, closed protocol fields, all five PNG row
filters, alpha, native dimensions and outside changes. Pillow stays in the
isolated pose runtime; the parent has no new image-decoding dependency.

Exact passed commands from `C:\Projects\flint-graph-codex-character-studio`:

```powershell
$env:FLINT_GRAPH_ENV='test'
& runtimes/posegen/.venv/Scripts/python.exe -m unittest discover -s runtimes/posegen -p test_repair.py
uv run pytest -q --tb=short
uv run python notes/run-stack-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py tests/integration/test_narrative_styles_api.py tests/integration/test_narrative_character_adapters.py tests/integration/test_narrative_pose_adapters.py tests/integration/test_narrative_anatomy_reviews.py tests/integration/test_narrative_pose_repairs.py -q --tb=short
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
npm test --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
uv run flint-graph-prompts check --base-ref origin/master
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run python -m unittest discover -s runtimes/stylegen -p test_contract.py
uv run python -m unittest discover -s runtimes/posegen -p test_contract.py
uv run python tools/narrative/studio.py --config notes/studio-repair-qa.env
uv run python tools/narrative/studio.py --config notes/studio-repair-gpu.env --no-migrate
uv run python -X utf8 notes/qualify-repair-gpu.py
uv run python -X utf8 notes/qualify-repair-transparent.py
uv run python -X utf8 notes/qualify-repair-alpha.py
& runtimes/posegen/.venv/Scripts/python.exe notes/verify-repair-pixels-live.py
uv run python -X utf8 notes/apply-repair-migration.py
uv run python tools/narrative/studio.py --config notes/studio-active.env
uv run python -X utf8 notes/qualify-repair-main.py
```

The private PG wrapper creates/drops only a random scratch database on the separate
768 MiB fixture at 6194, and runs a real head → 0032 → head migration cycle before
the listed tests. The real GPU jobs use the task-owned QA database, scoped image
store and unique Temporal pose queue. The opaque helper's passing final invocation
checks/downloads the already completed job; it does not create another generation.

Final precommit checks passed **2,021 Python tests / 124 gated skips**,
**297 PostgreSQL tests / 1 skip**, **137 frontend tests**, **33 real Godot/preview
tests / 1 skip**, **9 child contract tests** and **2 isolated Pillow compositing
tests**. Ruff, mypy (297 modules), SQL generation, Compose config, prompt-lock
compatibility, offline Acme eval, frontend types and production build passed.
The complete set is repeated after rebasing before the master fast-forward.

Offline skips require external services/models; real GPU/Temporal/browser proof
ran separately as described above. The PG skip is the SQLite variant of a PG-lock
test. The Godot skip requires an explicitly prepared owned builder; release code
and export templates are unchanged by this feature. No Linux GPU run, new
cross-model comparison, automatic anatomy detector, CCIP calibration or completion
of all #182/#184/#185 criteria is claimed. Generated repairs still need inspection,
including lighting/linework within the patch and its boundary.
