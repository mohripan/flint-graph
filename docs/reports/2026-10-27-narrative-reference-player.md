# Reference player and local CLI verification

Date: 2026-10-27. Scope: #118 / M30. Package foundation #117 is committed as
`2af546c` with [passing CI](https://github.com/mohripan/flint-graph/actions/runs/40460669254).
This report qualifies reference execution and local saves, not Godot/browser
parity, a studio UI, AI quality or production readiness.

## Observed behavior

The player executes authored lines, choices, typed Boolean/integer/enum state,
ordered assignments, conditions and endings. Automatic steps are bounded to
1,000 per action; integer overflow rolls back its complete set node. Empty
visible choices fault explicitly. Invalid actions/saves preserve the session.
Views are node-derived; callback generations can reject stale same-node actions.

The registered `flint-graph-narrative` command ran in real subprocesses against
the original fixture, with fresh owned files under
`notes/narrative-cli-bf058bcc738d414d987219005288d47e`:

| Route | Frames | Observed ending | Expected state and save restore |
| --- | --- | --- | --- |
| `patient_inquiry` | 6 | `restored` | Passed |
| `leave_in_peace` | 3 | `quiet` | Passed |
| `rush_to_judgment` | 3 | `hasty` | Passed |

These are actual local CLI/filesystem runs with no API, database or provider.
The captured JSON includes normalized frames; expected actions/end states come
from the separately authored fixture labels. These three traces are not an
exhaustive state-space proof.

## Review findings and corrections

One authorized reviewer found that a valid ~2.6 MiB story can create a ~1.3 MiB
save, exceeding the original 1 MiB load limit. The shared player/CLI save cap is
now 6 MiB and the valid large-state self-save/CLI restore tests pass. Package
source bounds constrain every enum string; the additional MiB covers bounded
integer growth and metadata.

The reviewer also identified multiplicative trace serialization. Scripted CLI
frames now have a cumulative 8 MiB ASCII-JSON budget checked before retaining
the next frame. A large-state route fails safely with `trace_size_limit` instead
of serializing gigabytes. Interactive output explicitly has no complete recorded
trace. Terminal control text is escaped and choice-number parsing is bounded.
Reviewer recheck: 7 passed, 56 deselected; no remaining blocker identified.

## Checks

| Command | Result |
| --- | --- |
| `uv run pytest -q --tb=short` | 1199 passed, 24 skipped, 140.94s |
| `uv run pytest tests/unit/test_narrative_player.py tests/unit/test_narrative_cli.py tests/unit/test_narrative_package.py -q --tb=short` | 141 passed, 1 skipped, 2.07s |
| `python notes/verify_narrative_cli.py` | Registered CLI validate, all three route/save/restore subprocesses passed |
| `uv run ruff check .` | Passed |
| `uv run mypy` | Passed, 170 source files |
| `uv lock --check` | Passed, 104 packages |
| Acme deterministic eval command below | Passed; quality thresholds met |
| `FLINT_GRAPH_ENV=test; uv run alembic upgrade head --sql` | Passed, 1061 lines; SQL generation only |
| `docker compose config --quiet` | Passed |
| `git diff --check` | Passed |

```powershell
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
```

Normal full-suite skips are opt-in live checks plus this Windows host's unavailable
unprivileged file symlink; its real directory-junction test passes. The local full
suite includes preserved #109 WIP tests, which are not part of this commit.
Frontend type/build/browser checks, engine gameplay/export conformance, live
model calls and hosted worker isolation are skipped for this pure runtime/CLI
slice; actual Godot/browser qualification remains #119–#121.

## Preserved boundaries

No API route, data migration, workspace, private document, existing frontend,
container or model configuration changed. No save is a signed achievement or
history attestation. File writes are explicit new-save paths and refuse existing
files; cloud saves, save migration, arbitrary code execution and Unity export
are not implemented. The validated engine/toolchain download for the next issue
is task-local under ignored notes and is not installed globally or committed.
