# Seated body guidance and missing-leg regression

2026-11-02 · ADR 0055 · migration 0042 · model-development slice of #182/#185.

Characters → Poses now offers **Body guide → Seated — both feet on the floor**.
The guide explicitly positions both hips, knees, ankles and wrists. The approved
look still supplies appearance; private character/style versions remain optional.
The guide replaces the supplemental character view. Default deployments keep the
feature off; the qualified local Studios enable it. Existing pose/repair prompts,
no-guide request identities and protocols 1–5 are unchanged.

## Root cause and implementation

The creator's one-leg image is the earlier synthetic QA pose. Replaying its stored
prompt, approved reference and seed **1610368469** reproduced the missing leg
**before segmentation**. This is a model geometry failure, rather than evidence
that the cutout removed a correctly drawn leg. The immutable negative image, SHA,
seed and manual label are retained in
[the regression fixture](../../evals/character-preservation/anatomy-regressions-v1/cases.json).
Its current original QA asset was explicitly marked flawed through the normal
review API, preserving identity/clothes feedback and image approval; the existing
training guard excludes it. No creator project was annotated or edited.

The new condition uses the publisher's [RefControl 4B pose adapter](https://huggingface.co/xocialize/refcontrol-FLUX.2-klein-4B-pose-lora/blob/b2b0edf2622f2abd980bf868441149d71b3eb7b0/README.md),
pinned to `b2b0edf2622f2abd980bf868441149d71b3eb7b0`. The publisher declares
Apache-2.0 and credits Wikimedia/Pexels training media. Its 92,426,792-byte
safetensors file is verified against the published LFS hash and the complete local
manifest. This is a low-rank adapter on the existing klein editor, not a separate
ControlNet or a newly trained FlintGraph model.

Protocol 6 renders the frozen COCO-18 guide first and supplies the approved
appearance reference second, fitted within 512 square. The pose adapter uses a
fixed **0.8** strength, independently of the private character/style strength
budget. `seated-front-v1` versions its coordinates, renderer, strength and reference
preprocessing; future recipe changes need a new guide version. The base remains
pinned, bf16, four steps and guidance 1. The sidecar freezes guide data/hash and
control manifest. API/worker/parent reject conflicting extra views, changed model
or weight pins and malformed protocol data before inference.

`narrative.image.pose_control` was authored through the existing Langfuse service,
read back with matching identity and added as a dedicated complete locked bundle.
All earlier entries, versions, bundles and typed image policy remain intact.
No existing deployment labels were changed. Only the generic template/schema/config
were sent; no character description, image, prompt variables or weights were sent.
The JSON numeric representation of guidance was normalized in this new entry to
match the actual service round trip. No old entry was normalized or rewritten.
The new catalog inventory was assembled through the typed bundle/upgrade validator;
ordinary same-inventory CLI lock/promotion rules are unchanged.

Public pose weights and private trained versions stay in operator/private storage,
never in game assets. Server-built notices append the pinned pose-model credit.
Local repairs retain that attribution from their source, without reapplying the
pose adapter; their outside-pixel contract remains intact.

## Real outcomes

The [comparison](seated-pose-guidance-2026-11-02/comparison.png) shows the failure,
an early extra-hand probe and final outputs. The [receipt and thumbnails](seated-pose-guidance-2026-11-02/qualification.json)
retain every controlled sample, seeds, hashes, guide data, inherited versions,
actual source-code hashes and measured resources.

An initial compatibility probe using the public model-card trigger drew both
legs but added a third hand in one of two images. Its diagnostic wrapper then
failed while hashing a source file at the wrong copied-script path; that is not
counted as a passing production run. A first registered two-candidate stacked run
completed but had costume/detail artifacts and unclear hands. These are retained,
rather than presented as successful anatomy examples.

The final guide separates the wrists over their thighs and uses 0.8 control
strength. Two default opaque candidates visibly show **two legs, two boots and
two hands**; the registered run took **80.000 seconds**, with peak CUDA allocation
**9,967,721,472 bytes**. A separate transparent run retained both leg/hand chains,
producing **695×1100 RGBA** in **73.907 seconds**, peak **9,967,574,016 bytes**.
A final character 0.6 + style 0.4 + pose 0.8 run also completed, with two visible
legs/boots/hands, in **70.907 seconds**, peak **9,984,285,696 bytes**. All candidates
remain unapproved, with manual review unknown. This is a scoped visual check,
not a calibrated anatomy classifier or statistical quality comparison.

The transparent output retains the existing cutout fringe and chair irregularities.
Fine fingers, costume trim, face proportions, linework and lighting can still vary.
This fixes an explicit geometry-conditioning gap; it does not prove all seated
images or other poses correct. Back views, arbitrary pose editing, multi-character
CGs, Linux GPU qualification and full #182/#184/#185 acceptance remain outside this
slice. The manual negative fixture does not pretend that ordinary unit tests can
recognize an anatomical defect in a generated image.

The [Studio selector](seated-pose-guidance-2026-11-02/studio-body-guide.png) and
[phone layout](seated-pose-guidance-2026-11-02/studio-body-guide-mobile.png) were
exercised through the actual frontend. Selecting a guide clears/hides the extra
view, previews the skeleton and sets editable seated context. A queued job retained
its actual frozen guide after navigating to Assets and back. At 390 px the document
remained 390 px wide; scoped desktop/mobile axe reported zero violations and zero
incomplete checks. Browser errors were absent.

Early UI/model attempts correctly failed `host_memory_busy`. The existing 6 GiB
host and 11 GiB dedicated-GPU admission floors were retained. Main and the older
owned QA Studios were paused only after aggregate idle checks; sufficient memory
then admitted the final runs. All three Studios were restored with preserved
private settings, queues, model/build pins and data, plus the qualified guide pin.
Main migration 0042 and its two scoped foreign keys were verified. Main API 8101,
frontend 5173 and preview 5192, and older QA APIs 8276/8278 returned 200. The completed
task-only guide QA launcher was stopped with its data retained. No Docker container,
volume, Ollama or other external model service was stopped.

## Verification

Meaningful tests failed before their behavior was added: rollout gating, guide
snapshot/replay, dedicated prompt selection, worker input/pin transfer, closed
protocol, public weight verification and generated notices. Final checks passed
**2,028 Python tests / 124 gated skips**, **305 PostgreSQL tests / 1 skip**,
**138 frontend tests**, **33 real Godot/preview tests / 1 skip**, **10 child contract
tests**, **2 isolated repair tests** and **1 guide raster test**. Ruff, mypy (298
modules), SQL generation, Compose config, prompt compatibility, offline Acme eval
and frontend types/build passed. The complete set is repeated after rebase before
master is fast-forwarded. An early full run caught duplicate test-module basenames
and a local typing-name collision; those were corrected before the complete green run.

Exact passed commands from `C:\Projects\flint-graph-codex-character-studio`:

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
uv run python tools/narrative/fetch_model.py --repo xocialize/refcontrol-FLUX.2-klein-4B-pose-lora --revision b2b0edf2622f2abd980bf868441149d71b3eb7b0 --license apache-2.0 --file refcontrol-pose-klein-4b.safetensors --file README.md --out notes/models/refcontrol-pose-klein-4b
uv run python -X utf8 notes/diagnose-missing-leg.py
uv run python -X utf8 notes/author-pose-control-prompt.py
uv run python tools/narrative/studio.py --config notes/studio-guides-qa.env --no-migrate
uv run python tools/narrative/studio.py --config notes/studio-guides-ui.env --no-migrate
uv run python -X utf8 notes/qualify-seated-guide.py
uv run python -X utf8 notes/qualify-seated-guide-final.py
uv run python -X utf8 notes/qualify-seated-guide-alpha.py
uv run python -X utf8 notes/qualify-seated-guide-stacked.py
& runtimes/posegen/.venv/Scripts/python.exe notes/record-guide-qualification.py
uv run python -X utf8 notes/apply-guide-migration.py
uv run python tools/narrative/studio.py --config notes/studio-active.env
uv run python tools/narrative/studio.py --config notes/studio-style-qa.env
uv run python tools/narrative/studio.py --config notes/studio-character-qa.env
uv run python -X utf8 notes/mark-missing-leg-qa.py
uv run python -X utf8 notes/qualify-guides-main.py
```

Private wrappers keep credentials/errors in ignored notes. The PG wrapper creates
and drops only a fresh random database on the separate 768 MiB fixture at 6194;
real head → 0032 → head migration checks passed. Offline skips require optional
external services/models; real GPU/Temporal/browser qualification ran separately.
The PG skip is a SQLite variant of a PG-lock test. The Godot skip requires an
explicit owned prepared builder; release/runtime code and templates are unchanged.
No check or resource guard was disabled to obtain these results.
