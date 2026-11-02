# Manual anatomy review and training exclusion

Date: 2026-11-02. Implements ADR 0053, a continuation of #183/#184.
A creator can now mark faulty anatomy separately from identity and clothing,
see warnings in the Studio, and keep known flawed image bytes out of new or
in-flight character and project-style training. Image approval stays available.
No model, training recipe, content policy, game format or Godot version changed.

## Behavior

**Assets → Compare look → Anatomy** offers unknown, acceptable and flawed.
A manual problem produces **Review anatomy** even when identity and clothes are
same. Training pickers disable the source and explain the exclusion. The server
also checks selected sources when client feedback is unavailable or truncated.
Unknown preserves the existing training flow and does not certify anatomy.
Existing notes are not parsed into verdicts automatically.

Migration 0040 creates a workspace/project/image-SHA review table with an explicit
version, actor and timestamps. The verdict is shared by identical image bytes
inside this project, independent of the comparison look or uploaded asset ID.
Discarding/reuploading the same file does not evade the verdict, and a live copy
can deliberately revise it. Other projects remain independent. Existing ordinary
identity/clothes/notes reviews keep their own versions and data.

Feedback reads include `anatomy` and `anatomy_version`. A write that includes
anatomy must supply `anatomy_base_version` alongside the normal `base_version`.
A stale dialog for another look/copy returns 409 rather than clearing a newer
verdict. Legacy clients omitting anatomy preserve it; the new control is hidden
against older APIs that do not return the field. Approval and other story edits
are independent of these reviews.

Both character and project-style admission reject flawed image bytes with 422
`anatomy-review-failed`. Idempotent replays keep the original job/history. The
style worker rechecks before reading inputs, during progress/watch checks, and
under the project review lock immediately before publishing a completed version.
A source flagged after admission fails with `anatomy_review_failed`; no usable
weight binding is published. A private staged object may remain after a final
publication race, as with cancellation. Existing completed adapters remain
selectable; they are not retroactively revoked.

## Live qualification

An isolated QA app used API 8280, frontend 5280 and preview 5300, an existing
task-owned random database, a fresh synthetic workspace/project and a unique
queue. No creator project was opened or annotated. The previous real combined
render's hand-defect PNG was uploaded into this new QA project under an explicit
synthetic-test rights declaration. Its ordinary approval remained intact.

The browser saved identity/clothes as same and anatomy as flawed. The asset card
showed the warning; character training showed a disabled source and exclusion
message. The [review dialog](anatomy-training-review-2026-11-02/studio-review.png),
[asset warning](anatomy-training-review-2026-11-02/studio-warning.png),
[training picker](anatomy-training-review-2026-11-02/studio-training.png) and
[mobile view](anatomy-training-review-2026-11-02/studio-mobile.png) record the flow.

Before starting its worker, a real style job was admitted with the then-unlabelled
source. The browser marked it flawed, then a dedicated real Temporal style worker
started on that isolated queue. The registered job failed with the specific
anatomy error, **zero training progress** and **no published weight hash**.
The [job status](anatomy-training-review-2026-11-02/studio-worker-rejection.png)
gives an actionable explanation. No new GPU training/render or automatic anatomy
inference was needed: this behavior must stop before the trainer is invoked.
The [safe receipt](anatomy-training-review-2026-11-02/qualification.json) records
the image hash, manual verdict/version, terminal job and accessibility results.

Desktop training and mobile axe checks reported zero violations and zero
incomplete checks. The native review dialog reported zero violations and one
incomplete contrast rule because axe considered text to overlap other elements;
the captured dialog was manually checked for readable, unobscured text. This is
not counted as a completely automated dialog accessibility pass. At 390 px the
document remained 390 px wide. Browser errors were absent.

After all five aggregate main job groups were idle, the creator-authorized main
Studio pause allowed migration **0040_anatomy_reviews** and its project-scope and reviewer foreign
keys to be verified. Only the task-only anatomy QA launchers were stopped. The
main Studio restarted with its existing private configuration, queues and model
pins. API 8101 `/health/live`, frontend 5173 and preview 5192 `/index.html` returned
200; earlier QA API 8276 and 8278 liveness checks passed too. The first readiness
probe ran before frontend startup completed; the bounded readiness retry passed
after the launcher reported ready. No container or external model service was
stopped, and no creator assets were changed.

## Verification

Review persistence, API admission, worker execution and frontend request tests
failed before the corresponding behavior was added. Checks cover legacy writes,
independent version conflicts, deliberate revisions, reuploads, scope/member
boundaries, approval independence, queued and mid-training failures, and the
final publication race. Fresh task-only PostgreSQL upgrade/downgrade/upgrade
passed. Full precommit checks passed **2,002 Python tests / 124 gated skips**,
**273 PostgreSQL qualification tests / 1 skip**, **134 frontend tests**, **33 real
Godot/preview tests / 1 skip**, and **8 child contract tests**. Ruff, mypy (295
modules), SQL generation, Compose config, prompt compatibility, offline Acme eval
and frontend type/build checks passed. The full set is repeated after rebasing
before the master fast-forward.

Exact passed commands from `C:\Projects\flint-graph-codex-character-studio`:

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
uv run python notes/run-stack-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py tests/integration/test_narrative_styles_api.py tests/integration/test_narrative_character_adapters.py tests/integration/test_narrative_pose_adapters.py tests/integration/test_narrative_anatomy_reviews.py -q --tb=short
uv run python tools/narrative/studio.py --config notes/studio-anatomy-qa.env
uv run python -X utf8 notes/prepare-anatomy-fixture.py
uv run python -X utf8 notes/prepare-anatomy-queued-job.py
uv run python tools/narrative/studio.py --config notes/studio-anatomy-worker.env --no-migrate
uv run python -X utf8 notes/qualify-anatomy-worker.py
uv run python -X utf8 notes/apply-anatomy-migration.py
uv run python tools/narrative/studio.py --config notes/studio-active.env
uv run python -X utf8 notes/qualify-anatomy-main.py
```

Private wrappers retain operator values/stderr and create/drop only random
scratch databases on the separate 768 MiB fixture (6194). Offline skips gate
external services/models; the real Temporal rejection and browser checks above
ran separately. The PG skip is a SQLite variant of a PG-lock test; the Godot skip
requires an explicit owned prepared builder. No Linux GPU qualification, new
model-quality comparison, automatic anatomy detection/repair, CCIP calibration
or completion of all #183/#184 acceptance criteria is claimed.
