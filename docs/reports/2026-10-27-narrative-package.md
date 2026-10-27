# Narrative package foundation verification

Date: 2026-10-27. Scope: #117 / M30, the reviewed local package boundary. This
report does not qualify the reference player, Godot export, browser gameplay,
authoring studio, AI generation or production deployment.

## Delivered and reviewed

`load_package(Path)` captures validated story/notices/asset bytes immutably and
returns safe diagnostics, canonical hashes and structural warnings. The original
Lantern Archive fixture has three authored ending routes, typed trust/knowledge/
approach state and two original procedural PNGs, with expectations held separately.
Fixture hash: `057e54a191c2a79d35a52a2d3502d749e214058b79214d5e967a9afb894b3850`.
The manifest digest also matched Windows `Get-FileHash -Algorithm SHA256`.

One authorized read-only reviewer identified presentation inheritance, PNG
transparency/order/metadata and partial-palette concerns. The design now specifies
node-derived presentation, and public loader red/green tests reproduce and reject
the malformed PNG cases. Indexed palettes must be complete in the supported
subset. Captured assets are never reread to determine package identity.

## Checks

| Command / boundary | Observed result |
| --- | --- |
| `uv run pytest tests/unit/test_narrative_package.py -q --tb=short` | Final: 78 passed, 1 skipped, 0.65s |
| `uv run pytest -q --tb=short` | 1135 passed, 24 skipped, 140.75s; before the final partial-palette regression/additional guard, which passed in the final focused run |
| `uv run ruff check .` | Passed after formatting/import/line-length corrections |
| `uv run mypy` | Passed, 168 source files |
| `uv lock --check` | Passed, 104 packages |
| Existing Acme deterministic evaluation command below | Passed; all quality thresholds met |
| `FLINT_GRAPH_ENV=test; uv run alembic upgrade head --sql` | Passed, 1061 output lines; generated SQL only, no database mutation |
| `docker compose config --quiet` | Passed; no services restarted |
| `git diff --check` | Passed |
| Actual fixture loading and manifest hashing through local Python/PowerShell | Passed; no API, database or inference service needed |
| Real Windows directory-junction rejection with intact outside canary | Passed |

```powershell
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
```

The single focused skip is unprivileged file-symlink creation, which this Windows
host disallows. The independent Windows junction/reparse check ran successfully;
ordinary symlink coverage runs on hosts that permit it. The full suite includes
preserved #109 WIP tests in the working tree; this change does not stage or claim
delivery of #109. Opt-in live integrations remain skipped in that normal run.

Frontend commands/browser checks, Godot import/export/playback, live model quality
and hosted build isolation were skipped: #117 changes only package loading and
original fixtures. Engine/browser proof remains mandatory for #119–#121 and M30.

## Limitations and preservation

The supported PNG subset deliberately excludes compressed profiles/text, APNG,
unknown chunks and partial indexed palettes; this is not universal PNG support.
Structural reachability/cycle warnings ignore conditions and cannot prove an
ending is playable. Constructors are internal library values; untrusted packages
enter through the strict loader. Local validation is not a host-filesystem or
engine sandbox. No cloud-save, runtime-AI or Unity support is claimed.

Only narrative source/tests/docs and scoped fixture line-ending rules belong to
the delivery commit. Existing .github/workflows/ci.yml and #109 trace-probe files,
private documents, containers, model settings, workspaces and indexes are retained.
