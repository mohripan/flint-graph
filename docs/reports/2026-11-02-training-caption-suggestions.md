# Reviewed training-caption suggestions — 2026-11-02

ADR 0056 / #184. Project-style and reviewed-character training now offer
**Suggest caption for…** for each selected image. The existing pinned local WD
CPU runtime proposes content tags with confidence; the creator reviews, applies
and edits them. Reading never replaces typed text. Applying checks the selected
image ID/hash, changes only its caption, and resets training confirmations.
Manual entry works when suggestions are missing, empty, busy or unavailable.

## Behavior and boundaries

The member-only `POST /style-jobs/caption-suggestions` verifies the approved PNG's
project, size, dimensions and private stored bytes. The source is limited to
8 MiB and 64–2560 pixels per side. The existing immutable observation records
raw probabilities and source/model fingerprints. Only a closed, versioned set of
appearance/garment/pose/framing/scene tags becomes suggested text, within 600
characters / 48 tags and the current content policy. Inferred gender/counts,
character names, ratings and rendering style/quality instructions are excluded.
Confidence ≥0.35 is a proposal filter, not a calibrated correctness threshold.

Release the authentication/read transaction before the bounded CPU call, then
lock/recheck project and source before persistence. Discard/archive during tagging
is refused. A first concurrent-edit test exposed a held SQLite writer lock; the
transaction boundary was corrected before the full suites passed. A regression
test with varying repeated tagger results also verifies that returned
text/confidences derive from the existing saved observation ID. No training
job, approval, reviewed look or anatomy verdict is changed by a suggestion.
The editor aborts stale requests on project/look changes; proposals stay separate
from current text until explicitly used. Training freezes the final reviewed text
through its existing dataset/trigger path. Old jobs and recipe hashes remain valid.

No migration, model download, GPU/training recipe, prompt template, content policy
or game runtime change is involved. CCIP is not loaded. The broader #184/M40
comparative and creator-calibration criteria remain open. This improves training
input preparation; it does not establish improved identity, clothes, lighting,
linework or anatomy in generated outputs.

## Real qualification

Only owned synthetic Aster fixtures were used. Four approved images were read
through the real API/private store/pinned isolated CPU runtime. End-to-end times
were **4.547, 2.937, 3.062 and 3.391 seconds**. The seated image's proposal includes
`sitting` and `chair`; standing/rear images have their own observations. Tags can
still omit or misread details and contain redundant coarse terms. The creator
must edit them; a high confidence is not a guarantee.
[Proposals, confidences and fingerprints](training-captions-2026-11-02/qualification.json).

The actual browser verified a manual edit made while tagging remained intact;
reading preserved confirmations, and applying cleared rights plus the character
form's same-look/anatomy confirmations. A proposal was applied and edited before
submitting a real four-image training job. Its persisted captions/dataset/recipe
were checked, then the still-queued job was cancelled, without model execution.
[Training admission receipt](training-captions-2026-11-02/training-admission.json).
This is an admission/caption-freezing check; no new GPU training or quality trial
was run because the training recipe and worker interface did not change.

[Desktop proposal](training-captions-2026-11-02/studio-proposal.png),
[phone proposal](training-captions-2026-11-02/studio-proposal-mobile.png), and
[character confirmations](training-captions-2026-11-02/character-confirmations.png).
Scoped axe checks found zero violations/incomplete checks on both desktop and
phone. At 390 px, document and viewport widths were both 390.

The main Studio and both earlier QA Studios were reloaded only after all five
job classes were idle. Original private queues, models, data and configurations
were preserved. Their nine API/frontend/preview endpoints returned 200; schema
remains 0042, the new route/capability is present, and a real caption request on
an approved source in the owned main synthetic fixture succeeded. The initial
readiness harness needed normalization of an older string look-ID receipt; the
application route did not fail. The task-only QA launcher was stopped, retaining
its fixtures. [Rollout receipt](training-captions-2026-11-02/rollout.json).

## Verification and exact commands

Tests first failed on the absent API route and frontend application helper. Full
checks passed before commit and again after rebase: **2,036 Python tests / 124
skips; 319 PostgreSQL tests / 1 skip; 140 frontend tests; 33 real Godot tests /
1 skip**. Ruff, mypy (299 modules), offline SQL, Compose, frontend types/build,
prompt locks, deterministic evaluation and child/guide/repair contracts passed.

```powershell
$env:FLINT_GRAPH_ENV='test'
& runtimes/posegen/.venv/Scripts/python.exe -m unittest discover -s runtimes/posegen -p test_guidance.py
& runtimes/posegen/.venv/Scripts/python.exe -m unittest discover -s runtimes/posegen -p test_repair.py
uv run pytest -q --tb=short
uv run python notes/run-stack-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py tests/integration/test_narrative_styles_api.py tests/integration/test_narrative_character_adapters.py tests/integration/test_narrative_pose_adapters.py tests/integration/test_narrative_anatomy_reviews.py tests/integration/test_narrative_pose_repairs.py tests/integration/test_narrative_pose_guides.py tests/integration/test_narrative_training_captions.py -q --tb=short
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
uv run pytest tests/integration/test_narrative_training_captions.py tests/integration/test_narrative_styles_api.py tests/integration/test_narrative_looks_api.py -q --tb=short
node --test frontend/tests/narrative-styles.test.mjs
uv run python tools/narrative/studio.py --config notes/studio-captions-ui.env
uv run python notes/qualify-caption-suggestions.py
$env:AGENT_BROWSER_SESSION='flint-training-captions'
npx --yes agent-browser a11y --selector '.style-studio > details > fieldset' --json
uv run python tools/narrative/studio.py --config notes/studio-active.env
uv run python tools/narrative/studio.py --config notes/studio-style-qa.env
uv run python tools/narrative/studio.py --config notes/studio-character-qa.env
uv run python notes/qualify-captions-main.py
```

Private wrappers retain credentials/errors under ignored notes. PostgreSQL checks
used a fresh random database on the separate 6194 fixture and passed real head →
0032 → head migration checks; only that database was removed. Default-suite skips
require optional external models/services. Actual CPU, browser, storage and API
checks ran separately. The PG skip is a SQLite variant of a PG locking check;
the Godot skip needs an explicitly prepared CG builder. No release/runtime code
changed. No required verification command was skipped. A new GPU training run
was deliberately not performed or claimed.
