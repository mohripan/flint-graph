# Host Godot runner qualification

Scope: #124's host adapter connecting validated text packages to the qualified
trusted image. It returns private source/web ZIP bytes; it does not publish,
complete releases, dispatch Temporal work or expose downloads. The ordinary API's
release switch remains disabled. Execution services from6a2089e have green
CI41029339390.

The runner checks immutable image/toolchain identity, Linux/amd64/nonroot profile,
fixed entrypoint, environment-key allowlist and absence of image volumes/commands.
It captures a freshly exported nineteen-file source inventory and independently
checks manifest hashes, canonical source/notices and package identity. Only a
new token-marked private directory under the configured scratch root is used.

Docker `create --pull=never` precedes effective inspection and another caller
ownership/cancellation check; only then does the engine start. Actual network,
root/user, capabilities, resources and mounts must match the designed boundary.
Checks continue during engine polling, archive transport and before returning.
The fixed seven-file USTAR passes the bounded decoder and independent status hash
checks. Web output includes runtime/Godot/font licenses, font provenance and
creator notices. Source keeps editable export instructions. HTML is not served
under the application origin.

CLI stdout/stderr have independent byte caps and nonblocking deadlines. Archive
reads have byte limits plus a cancellation/deadline-aware nonblocking reader.
Owned subprocess and decoder tasks are joined before cleanup finishes, including
repeated cancellation. Container cleanup resolves the exact name to an immutable
ID, checks its execution label and removes that ID. Confirmed absent containers
still permit scratch deletion. Unconfirmed daemon/ownership cleanup retains only
the verified private directory with a safe `.cleanup` marker; an automatic startup
sweep remains pending. Scratch deletion verifies exact resolved path, parent,
prefix and owner, preserving its parent and siblings.

## Review and real fault checks

Review found an output-cap pipe deadlock, decoder lifetime gaps, skipped scratch
cleanup and repeated-cancellation leaks. Initial fault tests hung; root/reviewer
stopped only their separately verified owned pytest processes before fixing them.
External CLI protocol fixtures exercise actual processes/pipes without mocking
runner methods; they do not claim engine execution. Tests cover8 MiB stdout/
stderr with retained memory below4 MiB, failed creation without a container,
corrupt source manifests, stalled archive descendants and repeated cancellation.
They assert the archive CLI is gone and no unhandled loop exceptions remain.
The reviewer's exact25-cancel/1ms reproduction then returned in0.22 seconds with
stopped CLI, no scratch and no late exceptions.

Two actual image cases passed: build an original text fixture and independently
verify source ZIP hashes/canonical story and licensed web output; cancel a build
task during real engine execution and verify owned cleanup preserves a sibling
file exactly. Both assert no matching running or stopped container remains.
[Receipt](evidence/narrative-build-runner-2026-10-30/qualification.json) records
package/image/toolchain and actual ZIP hashes/sizes. Proof ZIPs remain in ignored
operator output. Browser play from authorized downloads remains later acceptance;
these private proof bytes are not published releases.

## Verification

Passed:

- `uv run pytest tests/unit/test_narrative_build_runner.py tests/unit/test_narrative_release_artifacts.py -q --tb=short`:
  58 passed; final runner-only run9 passed. Reviewer independently passed57 cases
  and the repeated-cancellation reproduction before the source-manifest case.
- `uv run pytest -q --tb=short`:1324 passed,54 skipped in179.64 seconds.
  Skips include explicitly opt-in native/services and backend-specific parameters.
- Explicit image/toolchain and fresh evidence destination:
  `uv run pytest tests/integration/test_narrative_build_runner_live.py -q --tb=short`:
  final2 passed in12.27 seconds after the small immutable-ID/stopped-container
  checks; those final changes also passed the focused suite.
- `uv run ruff check .`; `uv run mypy` (185 files); `uv lock --check`.
- Deterministic Acme evaluation, offline Alembic SQL through0018 (1212 lines),
  `docker compose config --quiet` and `git diff --check`.

PostgreSQL/browser matrices were not repeated because their behavior did not
change. No models were called. Frontend/API/local preview remain available;
unrelated #109 work and user data remain intact. Keep #124 open for activity/
worker integration, startup recovery, immutable object publication/downloads,
Temporal interruption recovery and Releases UI/end-to-end qualification.
