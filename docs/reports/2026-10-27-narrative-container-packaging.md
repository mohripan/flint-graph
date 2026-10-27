# Narrative template container packaging correction

Date: 2026-10-27. Follow-up to #119 / commit `15770ae`.

## Failure and correction

The first #119 [CI run](https://github.com/mohripan/flint-graph/actions/runs/40464896128)
passed offline/backend and frontend gates, but failed the existing observability
job when building the application image. Hatch's new explicit runtime template
includes were absent because Dockerfile copied `src` but not `runtimes` before
the final project installation. The installed-wheel test did not exercise this
container build context; the missing copy was an implementation oversight.

Dockerfile now copies `runtimes` before `uv sync --frozen --no-dev`.
`.dockerignore` excludes ignored notes, including task-local engine archives,
working data and verification artifacts. No old CI workflow changes are staged:
the existing `.github/workflows/ci.yml` #109 WIP remains untouched.

## Actual build and runtime proof

Created an owned Git archive of committed `15770ae` source, then copied only the
two Docker/context corrections into that build context. This excludes uncommitted
#120 game-player work and all unrelated #109 WIP. Built a unique image without
replacing application tags or restarting services:

`flint-graph-narrative-build-probe:eaeb412f474848e5821380c7b0c7c6a1`

Evidence: `notes/narrative-docker-eaeb412f474848e5821380c7b0c7c6a1/build.log`
and `smoke.log`. Actual build passed; the first native smoke passed in 1.18s.

The native smoke resolves the local daemon and immutable image ID, then invokes
the registered CLI twice in fresh `--rm --pull=never --network none --cap-drop ALL
--security-opt no-new-privileges --read-only` containers. Only the original public
fixture is bind-mounted read-only; new export files use a bounded `/tmp` tmpfs.
Validation matched the known package hash and source export reported the pinned
Godot version and expected template files, without an API, database, model or
engine executable. No container from the application deployment was changed.

## Regression gate and limits

The new independent `.github/workflows/narrative-container.yml` builds the actual
image and runs `tests/integration/test_narrative_container_live.py` on relevant
changes. It uses read-only repository permission and uv 0.12.3, verified against
the installed CLI and official release tag. The normal offline test run skips
this native check unless `FLINT_GRAPH_NARRATIVE_CONTAINER_IMAGE` is explicit.

One authorized reviewer found no remaining blocker and recommended disabling
implicit image pulls; that flag was added and rerun. This report qualifies image
packaging only. It does not launch inference, verify hosted game sandboxes, change
deployment configuration, or qualify the ongoing #120/#121 gameplay/browser work.
