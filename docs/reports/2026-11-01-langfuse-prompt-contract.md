# Langfuse prompt-management contract (#134)

Baseline `77cb2c8`; isolated worktree `C:/Projects/flint-graph-codex-langfuse`,
branch `codex/langfuse-prompt-contract`. This delivers a decision/inventory and
qualification evidence, **not an enabled Langfuse integration**.

- [ADR 0044](../adr/0044-langfuse-authoring-and-reviewed-prompt-locks.md) chooses
  Langfuse authoring with reviewed full-content locks, per-run snapshots, nonblocking
  local resolution, verified remote refresh, approval and rollback.
- [Inventory/matrix](../architecture/prompt-catalog-inventory.md) identifies the
  exact current answer, support, extraction, assistant and image-conditioning sources,
  plus image-content-policy TOML. Runtime enforcement remains application code;
  a later policy migration preserves explicit operator policy choices.
- [ADR 0029 addendum](../architecture/prompt-management-threat-model.md) treats
  prompt/config edits as a code-equivalent supply-chain path. It separates
  prompt management from #79 tracing/evaluation export.

## Upstream qualification

Reviewed official documentation, tagged server/SDK source and version-specific
PyPI metadata on 2026-11-01. Server candidate: **4.72.0**, commit
`7efeac5eebe215b461fa0bc37369dc7f80d7752f`. SDK candidate: **4.15.0**, commit
`5fcae099163513af026ed71dadf5bd85e8177158`. Its wheel was independently downloaded
and SHA-256 verified:
`3612197b162838a90f3e6f9d994758d1388db2664c5a5d0a4411da5988f823eb`.
The application root `pyproject.toml` and `uv.lock` were not changed. The worktree
`uv.lock` bytes hashed to `3747db763ab46ae0da151b2ca2697264b56d314765e848ead4a975897515118d`.

Exact dependency probes (task-local files/environment only):

```powershell
uv export --frozen --all-groups --no-emit-project --no-hashes --output-file notes/base-requirements.txt
# notes/langfuse-compatible.in contains langfuse==4.15.0
uv pip compile notes/base-requirements.txt notes/langfuse-compatible.in --python-version 3.12 --output-file notes/langfuse-compatible.lock
# notes/langfuse-latest.in contains langfuse==5.1.0
uv pip compile notes/base-requirements.txt notes/langfuse-latest.in --python-version 3.12 --output-file notes/langfuse-latest.lock
uv venv notes/sdk-probe
uv pip install --python notes/sdk-probe/Scripts/python.exe -r notes/langfuse-compatible.lock
$env:PYTHONPATH=(Resolve-Path src).Path
$env:FLINT_GRAPH_LANGFUSE_SDK_PROBE='1'
& notes/sdk-probe/Scripts/python.exe -m pytest tests/integration/test_langfuse_prompt_contract.py -q --tb=short
```

4.15.0 resolution/install **passed**, preserving all existing locked dependencies.
The 5.1.0 resolution **failed as expected**: it needs OTel SDK >=1.45 while the
application locks 1.43. SDK 4.16–4.18 have the same new minimum. The current broad
pyproject OTel range does not mean that upgrade is already qualified.
The first isolated test attempt lacked `PYTHONPATH` for the local package;
setting it as above fixed the environment without installing/changing the project.

The real SDK probe **passed 4 tests** under a synthetic `httpx.MockTransport`:

1. Tracing disabled still permits prompt GETs (fresh cache hits issue no second GET), creates no Langfuse tracer provider,
   does not replace the application provider, and emits no observation writes.
2. An event-gated cold fetch waits for the network even with an SDK fallback. That
   fallback loses authored config. The request path therefore needs our approved
   local bundle, rather than a direct SDK call with a fallback string.
   The high-level zero-retry setting still resulted in three generated-client attempts.
3. Passing `max_retries: 0` explicitly to the generated prompt API makes only one
   attempt on a 503 response. The contract requires that option and an absolute
   deadline for future background refresh; the asynchronous path still needs rollout qualification.
4. The SDK leaves absent variables unresolved and ignores extra arguments;
   substituted values are not recursively templated. Strict argument/type checks
   remain a catalog responsibility before dispatch.

This is actual vendor-library behavior under controlled transport, **not a live
Langfuse-server or permission test**. Source/edition checks found protected labels,
project role overrides and audit persistence/viewing gated to Enterprise; instance
OAuth/OIDC configuration and core prompt/version functionality are distinct OSS
features. Tagged source also permits ordinary write-enabled project API keys to
promote protected labels. Citations and pins are in the inventory/matrix.

No containers, volumes or owned processes were started, stopped or reconfigured.
No existing creator project, real Langfuse credential or live model call was used. A future
#136/#137 deployment must qualify actual prompt reads, denied writes, transport
privacy, cache/outage behavior, atomic promotion and rollback on the pinned server.
Web/worker deployment image digests still need qualification before activation;
the candidate here is a version/commit pin, not a prepared deployment receipt.

## Repository verification

Commands from the worktree, with outputs in ignored task-local `notes/`:

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
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe'
$env:FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES='C:/Projects/flint-graph/notes/toolchains/godot-4.7.2/templates'
uv run pytest tests/integration/test_narrative_godot_live.py tests/integration/test_narrative_preview_live.py tests/integration/test_narrative_event_cgs_live.py -q --tb=short
uv run python notes/run-langfuse-postgres.py
```

The PostgreSQL launcher creates a disposable database on the existing local
PostgreSQL service, sets its URL only in the test child environment, and drops
only that database afterward. It invokes
`python -m pytest tests/integration -k 'narrative and not live and not worker_live and not runner_live' -q --tb=short`.
Existing application/worker databases, queues and data are preserved.

Pre-commit verification passed: **1,804 Python tests / 109 skipped**, **107 frontend
tests**, **291 PostgreSQL tests / 11 skipped / 452 deselected**, and **33 native
Godot tests / 1 skipped**. The fourth vendor probe was added after the full suite
was collected; the complete isolated probe passed all four, and a focused default
run confirmed all four are opt-in skips. The Godot skip is the real CG release-build
case, which requires an explicitly supplied current builder image/toolchain; this
change does not modify the runtime or claim a newly qualified release build.

Ruff, mypy, Alembic SQL, Compose validation, frontend typecheck/build and the
deterministic Acme evaluation also passed. The default test run deliberately
skips the vendor SDK probes; their explicit isolated run above passed. Other
opt-in service/model tests retain their existing gates. No new production behavior
was implemented, so no model-output golden baselines or runtime versions changed.
The new tests qualify vendor assumptions before any catalog/resolver implementation.
Builder/preview rebuilding and browser feature testing are not applicable to this
documentation/qualification change; live Langfuse deployment remains unqualified.

After `git fetch origin` and `git rebase origin/master`, the full required checks
were repeated: **1,804 Python tests / 110 skipped**, **107 frontend tests**,
**291 PostgreSQL tests / 11 skipped / 453 deselected**, **33 native Godot tests /
1 skipped**, and **4 isolated SDK tests** passed again. The final full run includes
the fourth opt-in vendor probe, accounting for the additional skip/deselection.
Ruff, mypy, Alembic SQL, Compose validation, frontend typecheck/build and the
offline evaluation passed again. New local document links were also checked.
