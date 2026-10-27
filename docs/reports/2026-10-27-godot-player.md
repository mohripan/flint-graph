# Godot narrative player delivery

Date: 2026-10-27. M30 / #120. Runtime **0.2.0**, compiler **0.1.0**,
Godot **4.7.2.stable.official.ed1daf0bf**, Windows x86-64.

The trusted source export now plays authored narration and choices, renders
current-node artwork and supports local Save/Load/Restart. It needs no backend,
model or account. The [player contract](../architecture/godot-player-contract.md)
defines execution, strict parsing, local save publication and UI boundaries.

## Real engine and review evidence

The pinned executable is checked against SHA-256
`ab1824f85bfd8e0e4128182c000c4003a3e042245b2967848d089b2a04b22424`
before execution. Both matching single-threaded Web templates are checked against
the committed toolchain record. Engine subprocesses use owned temporary exports,
isolated profiles and 90-second timeouts; parse errors fail qualification even
when the process returns zero. No global installation or implicit download occurs.

All three original Lantern Archive routes match the Python reference frame for
frame, including variables and endings. A native save at the first choice restores
without replaying assignments and can also be loaded by the Python reference.
The unchanged original package hash is
`057e54a191c2a79d35a52a2d3502d749e214058b79214d5e967a9afb894b3850`.

Native adversarial checks exercise strict duplicate-key/UTF-8/surrogate/depth/
integer parsing, incompatible and malformed saves, invalid/stale actions, both
overflow bounds, empty choices, automatic loops and a valid save larger than
1 MiB. Rejections preserve state and callback generation.

The single authorized review agent found two UI/file failures: truncating the
previous save before a successful write, and accepting a generation-zero callback
after Restart replaced the Player. Regression tests failed before the fixes.
Candidate write/flush/readback/rename now preserves actual prior bytes through
three injected failures; buttons bind both instance and generation. Both tests
passed independently in the review agent's real engine rerun.

Review also found missing non-resource font notices in the Web export filter.
They are now explicit includes. A real built PCK loaded under a separate probe
root reproduces exact story/content/runtime/engine/font-notice hashes without
loose-source fallback. Lora bytes/license provenance was independently checked.
An actual wheel installed without dependencies outside the source checkout exports
the same 23-file manifest as source: evidence
`notes/narrative-wheel-da78330e4a8743628d019d10da855f0b` (after normalizing
provenance JSON to the committed LF format; upstream font/license bytes unchanged).

## Verification

| Command | Observed result |
| --- | --- |
| `uv run pytest -q --tb=short` | 1209 passed, 39 skipped, 138.27s |
| Configured `uv run pytest tests/integration/test_narrative_godot_live.py -q --tb=short` with engine and templates | 15 passed, 44.69s; actual native routes, saves, UI and Web PCK |
| `uv run python notes/verify_narrative_wheel.py` | Passed; installed wheel manifest equals source |
| `uv run ruff check .` | Passed |
| `uv run mypy` | Passed, 171 source files |
| `uv lock --check` | Passed, 104 packages |
| Acme deterministic evaluation command from AGENTS.md | Passed, unchanged thresholds |
| `FLINT_GRAPH_ENV=test; uv run alembic upgrade head --sql` | Passed, 1061 lines; generation only |
| `docker compose config --quiet` | Passed |
| `git diff --check` | Passed |

The full offline run collected before the final additional invalid-action test;
that opt-in native test also passed separately (1 passed, 14 deselected, 2.71s).
The skipped cases include unconfigured live integrations/native engine and the
host's unprivileged file symlink; real Windows junction checks pass. Preserved
unrelated #109 WIP participates in the local full run but is excluded from commits.

Actual browser input/layout checks were performed during this work, including a
blank-canvas startup failure that native state-machine tests did not catch. Its
fix and final screenshots/route evidence are recorded separately under #121;
native success alone is not browser qualification. The existing React authoring
frontend is unchanged and was not built in this slice. No paid model quality,
cloud saves, other native platforms, hosted build sandbox or complete game studio
is claimed.
