# Assistant image actions, clarification and inherited stage images

The reported conversation was inspected through authorized read-only project APIs.
It had two background jobs with the same description, and a character proposal
that invented a name and school uniform. No creator project was edited, no live
turn or generation was started, and no owned process/container was restarted.
All mutation tests used synthetic projects and isolated databases.

Previously, Generate retained only component-local state; backgrounds also received
a fresh random request key on every click. Unmounting lost the association. The
new project-scoped endpoints derive a stable UUID5 key from the accepted proposal
and original operation index. They reuse existing image admission, policy checks,
audit/outbox writes and job responses. Tenant/project locks serialize concurrent
starts before profile updates. Acceptance is required, and one action retains one
job through completion, failure or cancellation. No migration was necessary.

Old v1/v2 suggestions recover matching legacy UUID4 jobs without rewriting data.
Matching uses creator, acceptance time, purpose, count and generation parameters;
when an old action omitted hires, its existing standard-resolution job remains
valid. Historical matching is necessarily inferred and can be ambiguous for
identical old requests. v3 proposals never use this fallback. Identical new
suggestions at different operation indexes remain independent requests.

Assistant reads before offering Generate, polls active jobs and retains monotonic
progress/terminal results when responses arrive out of order. Assets discovers
background jobs every 1.5 seconds while mounted, even without a known active job,
shows progress under all filters and reloads candidates on completion. Image bytes
and approval rules are unchanged.

Prompt v3 asks about material missing details (name, outfit, sprite/portrait/cast
intent), uses established history, and honors delegated choices. It suggests no
proposal while asking. Transparent sprites default to hires/2× with explicit
opt-out. Its frozen identity is
`5caef1eeab73bcb1531fbbda1a267e52ef750d8cab9129d0db720da0636551b5`;
v1/v2 pins remain intact. The first live draft failed by proposing an unnamed boy;
that failure led to clearer precedence and examples before the final live pass.
This qualifies the observed model behavior, not a guarantee for every model.

The scene in the screenshot already rendered an inherited background. The picker
now shows its actual thumbnail plus **From earlier scenes: asset_id**, instead of
an empty **Unchanged** checkerboard. CGs use the same distinction; unknown incoming
paths and explicitly cleared layers remain distinct. Inspection does not mutate
stage nodes or add redundant backgrounds.

## Verification

Worktree: `C:/Projects/flint-graph-codex-assistant`, branch
`codex/assistant-image-state`, based on current `origin/master` (`2bbe8d7`).
Tests for server action recovery/defaults and frontend API/model behavior were
written and observed failing before implementation. Added inherited-image and
out-of-order-status cases likewise failed before their implementations.

Commands run from the worktree unless noted:

```powershell
uv sync --all-groups
npm --prefix frontend ci
uv run pytest
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

All passed: **1,752 Python tests passed, 100 skipped**; **95 frontend tests passed**.
The Python skips include explicitly gated live services and the SQLite-only skip
of the PostgreSQL row-lock test. Ruff, mypy, migration SQL, Compose validation,
frontend typecheck/build and the offline eval gate also passed.
After `git fetch origin` and `git rebase origin/master`, the entire required
verification set above was repeated on the branch: Python **1,752 passed / 100
skipped**, frontend **95 passed**, and all remaining listed checks passed again.

Real engine/release checks used the existing verified 4.7.2 toolchain and the
runtime 0.5.0 builder image prepared during the CG delivery:

```powershell
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
$env:FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE='sha256:40f759774ab3f467811bc77f20b3c460fa3e7b1e2d3bea52b3f5fdb389b87f22'
$env:FLINT_GRAPH_NARRATIVE_BUILDER_TOOLCHAIN='1cc5e00d921058f5eb8fbc8713af59fa30438a0d5b0c7bd04fc58604fa5a7c9a'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
```

**34 passed**, including a real CG release export. Runtime sources/pins were not
changed by this fix, so builder preparation and preview rebuilding were not repeated.

PostgreSQL qualification used a disposable database created by a task-local
launcher on the existing PostgreSQL service, with per-test migrated schemas;
the launcher drops only that database afterward. Credentials stayed in child
environment variables and were never printed. Exact invocations:

```powershell
uv run python notes/run-assistant-postgres.py
uv run python notes/run-assistant-postgres.py tests/integration/test_narrative_assistant_images.py -q --tb=short
```

The launcher's default pytest command was
`python -m pytest tests/integration -k 'narrative and not live and not worker_live and not runner_live' -q --tb=short`:
**276 passed, 10 skipped, 443 deselected** before the additional concurrent-click
case. The final focused run passed **11 tests, 1 skipped** on SQLite and PostgreSQL,
including simultaneous starts resolving to one job (the SQLite lock case is skipped).
Other services' databases,
containers, volumes and running workers were preserved.
The full PostgreSQL command was repeated after rebasing: **279 passed, 11 skipped,
443 deselected**, including all additional action-identity and concurrency cases.

Local model qualification (direct adapter calls on a synthetic story, no Temporal
or project mutation):

```powershell
$env:FLINT_GRAPH_ASSISTANT_CLARIFICATION_MODEL='igorls/gemma-4-12B-it-qat-q4_0-unquantized-heretic:latest'
uv run pytest tests/integration/test_narrative_assistant_clarification_live.py -q -s --tb=short
```

**1 passed**, covering an ambiguous character request with no proposal, a follow-up
using the supplied name/outfit plus preserved traits and hires sprite, a sufficiently
described background request, and explicit delegation of naming/clothes.

Browser qualification used the `agent-browser` skill and a named Edge session,
with production components mounted by the synthetic fixture at
`frontend/tests/fixtures/assistant-images.html`:

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5273 --strictPort
agent-browser --session flint-assistant-images --executable-path 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' open http://127.0.0.1:5273/tests/fixtures/assistant-images.html
```

UI interactions verified Generate → Assets progress, progress under CGs, return
to Assistant and reload without another Generate button, one total job start,
completion refreshing four review candidates, and inherited thumbnail/label with
no story mutation. No browser page errors were reported. Screenshots accompany
this report under `evidence/assistant-image-actions-2026-10-31/`.

Opt-in tests for unrelated live model/Temporal/MinIO/Neo4j/OpenSearch services
remain skipped in the ordinary pytest run. No owned service was restarted to
activate this code: the API and assistant-worker owner must reload them after
pulling. Existing jobs/proposals are retained; the new prompt applies to new turns.
