# Character poses in Studio

Date: 2026-11-01. Implements the first model-backed pose feature from ADR 0046
through [ADR 0048](../adr/0048-character-pose-model-worker.md).

## Delivered

Characters → **Poses from a reviewed look** takes an immutable approved look,
a pose instruction, 1–4 candidates and optional transparent output. Jobs remain
visible across navigation/reload. Candidates support comparison/manual look
feedback, approval/discard and **Use on stage**, which adds a named character
sprite for scene/line selection. Pose renders are excluded from the portrait
section. Transient browser retries retain the request's idempotency key.

Migration 0035 adds a scoped pose-plan sidecar to the existing image ledger.
The shared image outbox/recovery selects ordinary or pose plans explicitly;
a separate opt-in pose worker runs the inherited IDs-only Temporal workflow,
quotas, execution fencing, cancellation and immutable artifact publication.
Model/source/look/prompt identities and seeds remain fixed across retries.
A changed installed model pin fails instead of substituting another model.

The isolated `runtimes/posegen` environment pins FLUX.2 klein 4B at revision
`e7b7dc27f91deacad38e78976d1f2b499d76a294`. It verifies the manifest and every
listed file, encodes the exact chat-wrapped prompt, releases the encoder, then
renders with transformer/VAE. Both stages load directly to CUDA with low CPU
memory loading. Four distilled steps, guidance 1, 768×1152; optional CPU ISNet
segmentation produces cropped transparent PNGs. The model weights stay private.
The new catalog entry `narrative.image.pose` preserves all historical bundles;
`flint-graph-prompts check --base-ref origin/master` passes.

Input policy remains enforced. This distilled model has no SDXL negative
conditioning: the policy's negative tags are not claimed to be applied.
The child rejects more than 512 wrapped tokens rather than truncating them.
Dedicated VRAM/host availability checks are observations, not reservations;
shared resource coordination remains M41. No unrelated process/model is unloaded.
No story-format, save or Godot runtime version change is needed.

## Real qualification

Only the repository's synthetic adult Aster and a newly created task-owned
workspace/project were used. No creator project was opened or modified.
The real HTTP → PostgreSQL → Temporal pose worker → model child → MinIO flow
completed with a **729×1117 transparent candidate**, subsequently approved and
bound in the browser, saved, placed at center, and played in Godot web preview.
The immutable [receipt](character-poses-2026-11-01/qualification.json) records
hashes, seeds, model/source/look and measured runtime metadata.

On the RTX 5070 Ti Laptop GPU (12,227 MiB):

| Observation | Live job |
| --- | --- |
| Child time, including verification/loading/cutout | 70.469 s |
| Peak Torch GPU allocation | 9.19 GiB |
| Dedicated device use after render | 10.08 GiB |
| Host RAM available at admission | 7.91 GiB |
| Process resident memory at completion, not peak | 2.59 GiB |
| Prompt tokens | 115 |

The initial CPU-loading configuration refused available host memory below its
9 GiB floor. Direct CUDA loading avoids the full CPU copy; the qualified path
uses a 6 GiB host floor with an unchanged 11 GiB dedicated GPU floor.
Windows qualification also exposed Torch's default cache username lookup in a
closed environment. An explicit per-job `TORCHINDUCTOR_CACHE_DIR` fixes it without
inheriting operator identity/credentials. A process-tree regression exposed a
Windows launcher leaving descendants alive on timeout; cleanup now stops only
the owned child tree. The real active-job cancellation completed in 2.078 s,
with zero assets, zero remaining pose children and zero reported device use.

Desktop and 390 px browser checks covered persisted progress, approval, stage
binding, saved scene placement and preview. The mobile document width was 390 px;
scoped axe 4.12.1 checks reported zero violations/incomplete checks. The browser
console had no errors. See the [mobile panel](character-poses-2026-11-01/studio-mobile.png)
and [saved playtest](character-poses-2026-11-01/playtest.png).

A **real release** of the saved scene reached Ready. Authorized source, web and
manifest downloads matched their immutable hashes. Source import with pinned
Godot passed; the [downloaded browser build](character-poses-2026-11-01/release.png)
rendered the seated sprite/dialogue. Source includes the model/license attribution
and contains no safetensors, ONNX weights or environment file. Existing runtime
and builder/preview pins were reused; no engine artifact was rebuilt.

The additive migration was applied to the configured local Studio only after
checking all image/voice/assistant/release queues were idle. The task-owned
launcher was reloaded with preserved queues/model pins/private build root and
explicit `pose` service. API 8101, preview 5192 and frontend 5173 are running.
The main checkout/configuration, other sessions' processes and data were preserved.

## Verification

Tests were added and observed failing before each implementation slice: admission,
queue separation, frozen execution, protocol/manifest rejection, child supervision,
private cache, descendant cleanup and frontend request/status/history behavior.

The final offline suite passed **1,952 / 123 skipped**; task-owned PostgreSQL
qualification passed **199 / 1 skipped**, including a fresh live
upgrade/downgrade/upgrade. Real pinned Godot/preview passed **33 / 1 skipped**.
The explicit real-model adapter check passed **1**; isolated protocol tests passed
**3**. All **126 frontend tests**, Ruff, mypy (281 source files), Alembic SQL,
Compose configuration, prompt-lock compatibility, frontend types/build and offline
Acme evaluation passed. Required gates are repeated on the rebased branch.

Commands run from `C:\Projects\flint-graph-codex-character-studio`:

```powershell
uv sync --frozen --project runtimes/posegen
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
uv run python -m unittest discover -s runtimes/posegen -p test_contract.py
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
uv run python notes/run-look-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py tests/integration/test_rate_limit_state.py tests/integration/test_narrative_request_boundary.py tests/integration/test_security_boundary.py tests/integration/test_metrics_recording.py tests/integration/test_narrative_assistant_events.py tests/integration/test_narrative_poses_api.py -q --tb=short
uv run python notes/run-pose-live-test.py
uv run python notes/qualify-live-pose.py
uv run python notes/qualify-pose-cancel.py
uv run python notes/qualify-pose-release.py
& 'C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe' --headless --editor --path notes/pose-release/source --import
```

Private wrappers remain ignored under notes. The PG wrapper creates/migrates/drops
only a random database on task-owned `flint-codex-prompt-pg-final` (6192); it never
uses the Studio DB as a test fixture. The live-model wrapper loads private
operator model/runtime pins and invokes `python -m pytest
tests/integration/test_narrative_pose_live.py -q --tb=short` with explicit
`FLINT_GRAPH_NARRATIVE_POSE_LIVE=1`. HTTP wrappers touch only their recorded newly
created fixture. Browser qualification used named isolated `agent-browser` sessions.

Offline skips are opt-in external-service/model tests. The new pose live check
is executed separately. The PG-group skip is the SQLite variant of a PG-only race.
The Godot-group skip is the prepared-builder CG gate; this pose story instead
passed the live Studio's existing release pipeline. Other model families, Linux
GPU execution and character/style LoRA training were not run by this delivery.
One fixture proves execution, not general identity/clothing accuracy; creator
review and the existing manual/advisory controls remain necessary.
