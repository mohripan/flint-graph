# Godot source export and toolchain qualification

Date: 2026-10-27. Scope: #119 / M30, editable trusted-source export and pinned
native toolchain. The exported bootstrap verifies content and displays a labeled
placeholder; the actual narrative player is #120 and browser acceptance is #121.

## Artifact provenance and local isolation

Official [4.7.2-stable release](https://github.com/godotengine/godot-builds/releases/tag/4.7.2-stable)
archives were downloaded explicitly to ignored `notes/toolchains/godot-4.7.2/`.
Both matched the release's `SHA512-SUMS.txt`; recorded SHA-256s are:

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| `Godot_v4.7.2-stable_win64.exe.zip` | 86013866 | `731980f9608d61333e5baf54a2ef17210acc7a538446c0cb9969f002aca1e953` |
| `Godot_v4.7.2-stable_export_templates.tpz` | 1281349702 | `f298490b8d44d934be425a5a65a51bf15f422428b229a06a6e11d9ffea248011` |

Only exact engine and single-threaded web template members were extracted.
Observed engine: `4.7.2.stable.official.ed1daf0bf`; template version:
`4.7.2.stable`. Extracted member hashes are in `runtimes/godot/toolchain.json`.
No global install, paid provider, application restart or data-service change was
performed. Engine verification subprocesses used owned APPDATA/LOCALAPPDATA/TEMP/TMP.

## Live source/build evidence

Owned evidence directory: `notes/godot-source-aca7004354284e28901158f1cb46c24f`.
Actual commands used the pinned executable against a newly exported source project:

1. `--headless --path <owned game> --editor --import`: clean exit, no script parse error.
2. `--headless --path <owned game> -- --verify-content`: exact
   `CONTENT_OK:057e54a191c2a79d35a52a2d3502d749e214058b79214d5e967a9afb894b3850`.
3. `--headless --path <owned game> --export-release Web <owned web/index.html>`:
   actual HTML, JS, WASM, PCK, audio worklets and icon produced using explicit
   matching custom-template paths in that owned qualification copy.
4. `--headless --path <empty owned directory> --main-pack <web/index.pck> -- --verify-content`:
   clean exit and the same exact marker with no loose source files. This verifies
   PNG keep-file/raw-byte availability inside the real compiled package.

A first diagnostic using `--quiet` suppressed the script marker; rerunning without
it confirmed the check. Exit status alone was not accepted as proof. Actual
browser rendering/input/save/runtime route conformance was not claimed.

## Installed-wheel proof

An owned wheel was built and installed without dependencies into a new venv.
An isolated `python -I` process outside the checkout loaded only that wheel and
exported the original package. The source checkout export and wheel export had
the same 16 files and manifest hash:
`6319f4b9de288cf0e1b6c367213e5658911a9689f64266d9f7568224ce16c7f8`.
Evidence: `notes/narrative-wheel-811e4282986c4d588362422a1d848029`.

Hatch bundles an explicit template file allowlist; runtime text is LF-pinned.
Original template/runtime source is MIT-licensed for exported-copy use, without
changing backend/repository or creator content licenses. Source exports contain
engine/content/runtime notices and no engine binary or template archive.

## Review and failure preservation

One authorized reviewer reproduced deletion of a host-modified child during the
first failure-cleanup implementation. The exporter now has no deletion path:
incomplete new output is retained, a controlled error is returned, and the build
manifest is written last. A public filesystem-boundary regression preserves a
replacement file after injected later I/O failure. Existing targets, including
empty ones, are always refused; actual linked-parent junction checks pass.
The reviewer reran all 8 exporter tests and reported no remaining blocker.

## Checks and limitations

| Command/boundary | Observed result |
| --- | --- |
| `uv run pytest -q --tb=short` | 1209 passed, 25 skipped, 138.23s |
| Four focused narrative test modules | 151 passed, 1 skipped, 2.24s |
| Explicit configured `uv run pytest tests/integration/test_narrative_godot_live.py -q --tb=short` | 1 passed, 2.69s; actual pinned import/hash check and tampered-PNG rejection |
| `uv run python notes/verify_narrative_wheel.py` | Built/installed wheel outside checkout; manifest matched source export |
| `uv run ruff check .` | Passed |
| `uv run mypy` | Passed, 171 source files |
| `uv lock --check` | Passed, 104 packages |
| Acme deterministic evaluation | Passed; unchanged quality thresholds met |
| `FLINT_GRAPH_ENV=test; uv run alembic upgrade head --sql` | Passed, 1061 lines; SQL generation only |
| `docker compose config --quiet` | Passed |
| `git diff --check` | Passed |

The normal full run skips opt-in native tests, other live integrations and the
host's unprivileged file symlink; independent real Windows junction tests pass.
The full local tree still includes preserved #109 WIP tests; no #109 files are
part of this delivery. Engine execution is explicit, not a normal offline gate.

Frontend build/typecheck, browser gameplay, AI story/art quality, other native
platforms, hosted code sandboxing, cloud saves, Unity export and production release
qualification are skipped/not delivered in this source-export slice. Local source
integrity is not authenticity or protection from a hostile host. See the
[contract](../architecture/godot-export-contract.md) and
[toolchain runbook](../runbooks/godot-toolchain.md).

The first remote CI image build exposed a missing Docker runtime-template copy;
see the [container correction and real image proof](2026-10-27-narrative-container-packaging.md).
