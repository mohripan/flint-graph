# Standing and walking body guides — 2026-11-02

ADR 0055 / #182 / #185. **Characters → Poses → Body guide** now offers front
standing and three-quarter walking beside the existing seated guide. Selecting
one fills an editable pose description and previews its skeleton. History retains
the actual admitted guide. An additional appearance view remains mutually exclusive
with a guide; private character and project-style versions remain available.

This is a preset extension of the pinned RefControl adapter and protocol 6, with
its existing 0.8 strength, four-step base recipe, renderer and appearance sizing.
No model download, prompt change, content-policy change, migration or Godot runtime
bump is involved. Deploy API and pose child together: an older child rejects the
new identifiers. The original seated dictionary remains byte-identical, hash
`665c6b7508ec44ab3a132fa5d514a20f16264ce9cd15486c9697d4bc7ebecf0a`.
Capability suggestions are form metadata outside the frozen guide/hash.

## Real output and limits

All runs used only the owned Aster synthetic fixture, its approved appearance
reference, the existing pinned FLUX.2 klein 4B/RefControl model and real
HTTP → Temporal → isolated CUDA child → stored PNG path. The API draws seeds and
freezes them at admission; these are recorded runs, not a fixed-seed A/B comparison.
The [receipt](standing-walking-guides-2026-11-02/qualification.json) includes all
six generated candidates, both pre-release and final walking geometry/hashes,
seeds, image hashes, actual memory, timing and selected private adapter hashes.
All images remain unapproved candidates; no positive anatomy verdict was inferred.

The [final sheet](standing-walking-guides-2026-11-02/comparison.png) shows two
opaque standing candidates using the reference alone, and two transparent walking
candidates using character strength 0.6 plus style 0.4. Each of these four visibly
has two arm/hand and leg/boot chains. Standing took **95.890 seconds**, peak
**9,967,721,472 bytes** allocated; final walking took **82.250 seconds**, peak
**9,984,285,696 bytes**. Actual host availability exceeded the unchanged 6 GiB
floor. The 11 GiB dedicated GPU free-memory guard is unchanged.

The [initial walking run](standing-walking-guides-2026-11-02/prerelease-walking.png)
exposed an extra arm/hand and boot/cuff fragments in one of two candidates. That
synthetic candidate was explicitly [marked anatomically flawed](standing-walking-guides-2026-11-02/negative-review.json)
through the normal review API, preserving approval and other verdicts; training
rejects known flawed images. Before release, the walking wrists were lowered and
the editable context changed from swinging arms to relaxed arms down. Both new
candidates have two visible limb chains. The two runs have different seeds and
context as well as geometry, so this is scoped visual qualification, not causal
proof or an estimated success rate. Fingers, coat buttons/trim, cuffs, proportions,
linework and lighting still vary. Guides do not guarantee correct anatomy or an
identical approved outfit. No back-view, arbitrary pose editor, Linux GPU or
multi-character CG qualification is claimed here.

The first standing admission stopped with `host_memory_busy`, produced no images
and is retained in the receipt. Owned Studios were paused only after aggregate
image/voice/assistant/release/training counts were zero. No resource guard was
weakened, other model service stopped or container/volume removed. One polling
connection dropped during final walking; reconnecting retrieved the same completed
job without generating another job.

## Studio and alpha inspection

The actual [desktop picker](standing-walking-guides-2026-11-02/studio-walking-desktop.png)
and [phone layout](standing-walking-guides-2026-11-02/studio-standing-mobile.png)
show the selected guide and correct editable context. At 390 px the document and
viewport widths both equal 390. Scoped axe checks of the pose form found zero
violations and zero incomplete checks on desktop and phone. The reference and
result images were inspected after proper compositing.

The earlier seated and region-repair reports incorrectly called the raw RGBA
preview's striped RGB bleed a visible fringe. [White/dark composites](standing-walking-guides-2026-11-02/alpha-composites.png)
of the unchanged stored images show that those pixels are fully transparent.
The reports are corrected; no cutout or image-generation code was changed.
Chair irregularities, detached scarf detail and fine anatomy remain review concerns.

The main Studio (8101/5173/5192), Aster QA (8276/5276/5296) and character QA
(8278/5278/5298) were restored with their original private configurations. Their
nine API/frontend/preview health endpoints returned 200; schema remains 0042 and
the new guide catalog is advertised. The task-only QA server was stopped after
qualification, retaining its data. [Rollout receipt](standing-walking-guides-2026-11-02/rollout.json).

## Verification

Tests were written first: new IDs failed API admission, the closed child protocol
and the frontend request builder. After implementation, focused checks passed.
Full verification before the commit and again after rebasing passed: **2,031
Python tests / 124 skips; 309 PostgreSQL tests / 1 skip; 139 frontend tests;
33 real Godot tests / 1 skip**. Ruff, mypy (298 modules), Alembic offline SQL,
Compose validation, frontend types/build, prompt lock, deterministic evaluation,
child contracts, guide rasterization and repair pixel checks passed too. Exact
commands, run from the isolated worktree:

```powershell
$env:FLINT_GRAPH_ENV='test'
& runtimes/posegen/.venv/Scripts/python.exe -m unittest discover -s runtimes/posegen -p test_guidance.py
& runtimes/posegen/.venv/Scripts/python.exe -m unittest discover -s runtimes/posegen -p test_repair.py
uv run pytest -q --tb=short
uv run python notes/run-stack-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py tests/integration/test_narrative_styles_api.py tests/integration/test_narrative_character_adapters.py tests/integration/test_narrative_pose_adapters.py tests/integration/test_narrative_anatomy_reviews.py tests/integration/test_narrative_pose_repairs.py tests/integration/test_narrative_pose_guides.py -q --tb=short
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
uv run python tools/narrative/studio.py --config notes/studio-guides-qa.env
uv run python notes/qualify-motion-guides.py standing
uv run python notes/qualify-motion-guides.py walking
uv run python notes/resume-motion-guides.py walking
uv run python notes/mark-motion-negative.py
uv run python tools/narrative/studio.py --config notes/studio-guides-ui.env
& runtimes/posegen/.venv/Scripts/python.exe notes/record-motion-guides.py
uv run python tools/narrative/studio.py --config notes/studio-active.env
uv run python tools/narrative/studio.py --config notes/studio-style-qa.env
uv run python tools/narrative/studio.py --config notes/studio-character-qa.env
uv run python notes/qualify-motion-main.py
```

Private wrappers retain credentials/errors in ignored notes. The PG wrapper used
a fresh random database on the separate 6194 test fixture and qualified head →
0032 → head, then removed only that database. Offline skips require optional
external services/models; actual GPU, browser and Temporal checks ran separately.
The PG skip is a SQLite variant of a PostgreSQL-lock test. The Godot skip requires
an explicitly owned prepared builder; this change does not modify release code or
templates. No required verification command was skipped.
