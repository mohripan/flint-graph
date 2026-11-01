# Reviewed character looks in the Studio

The first connected Studio slice of #181/#183 now has named looks, optional tag
suggestions, side-by-side review, saved warning badges and coarse clothing-tag
comparison. It follows the [research bench](2026-11-01-character-preservation.md)
and [ADR 0047](../adr/0047-reviewed-character-looks-and-advisory-feedback.md).
It does not ship a klein pose worker, LoRA controls, CCIP scoring or automatic
ranking. Those remain separate qualification and implementation work.

## Creator workflow

**Characters → Reviewed looks → New look** chooses an approved reference and
names the outfit. **Suggest tags from image** reads it with the optional CPU
tagger; the creator edits the hair/eyes and clothes before **Lock reviewed look**.
Manual entry works without it. Predicted gender/rating/character-name tags never
become descriptions; authored character type stays authoritative. Unseen details
should remain unspecified. The creator chooses an image of one character; no
person detector is claimed.

Selected looks guide portrait wording and supply reference pixels plus words for
expressions/CGs. Portraits do not become an image-edit model. Expressions repaint
the locked source's face; CGs still use the existing IP-Adapter path and retain
its two-person limitations. The CG picker supports reviewed looks or explicit
ordinary-image mode. Two-person requests use looks for both or image mode for
both; one person's look is never silently discarded.

A new outfit creates another immutable record with an optional parent. Old
requests retain their original reference, description and look hash. Selection
can explicitly return to **Use the character description**. Stale selection or
feedback writes return 409 and offer reload, preserving local edits until then.

**Compare look** on portraits, expressions and asset cards shows both full images
and the reference's reviewed traits. Separate manual character/clothes feedback
and notes persist. Warning badges name the reference look; they do not change
approval. Viewers inspect; members lock/select, tag, generate and save feedback.

**Compare clothing tags** shows weighted garment-tag overlap and each image's
tags. Missing evidence stays unknown. Identity and automatic verdict remain
null; no fit-set cutoff is activated. Known CGs return unknown without qualified
per-person crops/assignment. Uploaded scenes still need creator inspection: this
is coarse whole-image tag overlap, not per-person verification. The research
fit's 14/15 missed clothing drifts remain a reason to keep it advisory.

## Implementation and boundaries

`CharacterLooks.tsx`, `CandidateLookReview.tsx` and `lookModel.ts` provide the UI.
Characters, expressions and CGs use look-aware API methods. Cards batch feedback
reads and expose partial/unavailable results. New services separate immutable
looks, image admission, manual reviews and raw tag observations. Migration
`0034_narrative_looks` adds five scoped tables and query indexes. Composite foreign
keys preserve project/tenant/character boundaries; selection and feedback have
optimistic versions. Looks/observations have no update endpoint. Audits contain
IDs/hashes, not descriptions or notes.

Job hashes include look IDs. Admission uses the image ledger's workspace/project
lock order, closing concurrent retry gaps. Legacy and look-aware requests cannot
reuse a key to reinterpret a recipe. Job, outbox and look snapshots commit
together. Expression/CG admission passes frozen words and character type to the
central ledger; a later profile edit cannot replace or block the locked recipe.
Geometry, expression syntax, duplicate participants and content policy remain
validated. Existing worker fences remain in force.

`runtimes/character_eval/tag.py` reuses qualified WD preprocessing with **no CCIP
sessions**. It verifies the exact reviewed WD manifest and every file; code/runtime
fingerprints and raw probabilities stay separate from edited tags. The API gains
no ONNX/Torch dependency. The adapter runs one CPU child per API process with a
45 s bound, verified PNG input up to 8 MiB/2560 pixels per edge, minimal environment
and bounded result reading. Broken/tampered installations return recoverable 503
without child paths/stderr. Tagging needs no GPU, hub download or Langfuse tracing.
Concurrent reads return recoverable 429 instead of forming an unbounded queue.

Protected assistant/image-generator files, shared narrative types and the main
checkout were untouched. This is Studio admission integration; assistant image
suggestions retain their profile-based path. No real project or owned Studio
service was opened/restarted/migrated. Story packages, runtime versions, saves and
exports are unchanged; private metadata/weights do not enter games.

The README now leads with the visual-novel Studio, delivered authoring/player
features and local setup. GraphRAG remains a shorter foundation section. Its 25
Markdown links were checked against local paths, and code fences/diff checks
passed. Research limits remain explicit.

## Verification commands

The full pass yielded **1,930 passed / 122 skipped**; Ruff and mypy (274
files) passed, as did SQL/Compose checks, 119 frontend tests, types/build and the
offline Acme evaluation. The owned PostgreSQL group passed **150 tests / 1 skip**,
including the real two-member admission race and migration round trips. The
Godot/preview group passed **33 / 1 skip**. The real WD-only child, tamper and
concurrent-busy test passed too. Required gates are repeated after rebase.

Browser qualification used only a fresh SQLite/artifact fixture API on 8272 and
Vite on 5274 (the earlier prototype used 8271/5273), with the separate named
agent-browser session `codex-character-looks`. It exercised tag suggestions and
creator edits, unavailable-tagger manual entry, locking/reopening, persisted
feedback/badges, coarse tag comparison, feedback-fetch failure, keyboard Escape,
and all three image-admission controls. Receipt assertions checked the same look
hash/reference and edited words on portrait, expression and CG jobs. These were
admission tests with no running GPU image worker. Desktop 1440×1100 and mobile
390×844 axe 4.12.1 scans each found zero violations/incomplete checks at the top.
A scrolled-state audit left two labels behind the sticky header for manual
contrast review; both were checked at the top and while scrolling.

Evidence: [locked look](evidence/reviewed-character-looks-2026-11-01/locked-look-desktop.png),
[desktop comparison](evidence/reviewed-character-looks-2026-11-01/compare-desktop.png),
[mobile comparison](evidence/reviewed-character-looks-2026-11-01/compare-mobile.png),
[saved warnings](evidence/reviewed-character-looks-2026-11-01/asset-warnings.png),
[receipt](evidence/reviewed-character-looks-2026-11-01/browser-qualification.json).
Representative exact browser commands (refs were refreshed from snapshots):

```powershell
$env:AGENT_BROWSER_SESSION='codex-character-looks'
npx --yes agent-browser skills get core
npx --yes agent-browser snapshot -i
npx --yes agent-browser set viewport 1440 1100
npx --yes agent-browser set viewport 390 844
npx --yes agent-browser a11y --tags wcag2a,wcag2aa --json
npx --yes agent-browser set offline on
npx --yes agent-browser eval "window.dispatchEvent(new Event('flint-look-review-changed'))"
npx --yes agent-browser wait --text 'Some saved look feedback could not be shown.'
npx --yes agent-browser set offline off
uv run python notes/assert-look-browser.py
```

All commands ran in `C:\Projects\flint-graph-codex-character-studio`, prepared
with `uv sync --all-groups` and `npm ci` in `frontend`. New HTTP/model seams were
observed red before their implementation. Tests cover immutable look retries,
frozen prompt delivery to the worker boundary, legacy-key collisions, references,
advisory feedback, stale versions, reviewed versus inferred tags, unknown identity,
later profile edits, invalid geometry/expressions/participants,
roles/scope/policy/archive rules and concurrent retries by two PostgreSQL members.

```powershell
uv run pytest -q --tb=short
uv run ruff check .
uv run mypy
$env:FLINT_GRAPH_ENV='test'
uv run alembic upgrade head --sql
docker compose config
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
```

Real pinned Godot/preview qualification:

```powershell
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
```

PostgreSQL used only the task-owned `flint-codex-prompt-pg-final`, loopback 6192.
The private wrapper creates a random database, performs head → 0032 → head,
runs tests, then drops that database without printing credentials:

```powershell
uv run python notes/run-look-postgres.py tests/integration/test_prompt_snapshots.py tests/integration/test_ingestion_activities.py tests/integration/test_provenance_extraction_persistence.py tests/integration/test_query_orchestration.py tests/integration/test_query_run_ledger.py tests/integration/test_narrative_assistant_execution.py tests/integration/test_narrative_characters_api.py tests/integration/test_usage_accounting.py tests/integration/test_narrative_looks_api.py -q --tb=short
```

Actual WD-only inference and tamper refusal:

```powershell
uv sync --project runtimes/character_eval
$env:FLINT_GRAPH_LOOK_TAGGER_MODEL='C:/Projects/flint-graph-codex-character-research/notes/models/wd14'
$env:FLINT_GRAPH_LOOK_TAGGER_PYTHON=(Resolve-Path runtimes/character_eval/.venv/Scripts/python.exe).Path
uv run pytest tests/integration/test_narrative_look_tagger_live.py -q --tb=short
```

Provisioned live checks and the PostgreSQL-only race are opt-in in the default
suite and run separately above. One Godot prepared-builder CG release gate is
skipped: no runtime/export change requires a builder/preview rebuild or release
build here. Admission tests use the existing fake engine at the worker boundary;
they make no claim of newly running a GPU image model.

## Activation and remaining work

The owner must apply 0034 and reload their API/frontend from the merged checkout;
this delivery does not restart their Studio. Optional tagger configuration is in
the [runbook](../runbooks/narrative-image-generation.md#reviewed-looks-and-clothing-tags).
Manual looks/feedback do not need it.

CCIP licensing and creator-held-out calibration, pose-model rollout, independent
multi-view/sheet references, per-person CG scoring, automatic ranking/best-N and
real private LoRA training remain open. No LoRA controls are advertised without
training implementation and an approved set. All seven research issues are not
closed by this slice.
