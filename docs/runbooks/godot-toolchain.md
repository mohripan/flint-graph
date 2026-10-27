# Export source and qualify a local Godot toolchain

Current source proof: M30 #119. Reference playback is already available in
[the local play runbook](narrative-local-play.md). The current exported bootstrap
verifies data; authored game UI/playback follows in #120.

## Source export without an engine

Choose a new directory with an existing parent:

```powershell
New-Item -ItemType Directory -Path notes -Force
uv run flint-graph-narrative export-godot tests/fixtures/narrative/lantern_archive --output notes/my-first-godot-project
```

No engine/download/model is needed for this command. Existing directories are
refused, including empty ones. If a new export fails midway, keep its partial
directory for inspection and choose another new path; the tool never deletes or
overwrites creator files. A manifest is written last. Read the generated README,
runtime/content notices and [export contract](../architecture/godot-export-contract.md).

## Explicit pinned engine setup

Use the official [4.7.2-stable release](https://github.com/godotengine/godot-builds/releases/tag/4.7.2-stable):

- `Godot_v4.7.2-stable_win64.exe.zip` (86,013,866 bytes).
- `Godot_v4.7.2-stable_export_templates.tpz` (1,281,349,702 bytes).
- `SHA512-SUMS.txt` from the same release.

Verify each complete archive against its named SHA-512 entry and the committed
SHA-256s in `runtimes/godot/toolchain.json` before extraction/execution. Keep an
explicit task-local directory; ordinary application startup/tests never fetch
these files. Extract only the exact expected engine members and
`templates/web_nothreads_debug.zip`, `templates/web_nothreads_release.zip`,
`templates/version.txt`. Do not run arbitrary archive members or install globally.

The development qualification used
`notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe` and recorded
`4.7.2.stable.official.ed1daf0bf`; matching templates reported `4.7.2.stable`.
It isolated APPDATA/LOCALAPPDATA/TEMP/TMP per engine subprocess. Different
platforms/versions are not qualified by the Windows result.

## Repeat the native acceptance test

After verifying an explicitly selected engine executable:

```powershell
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN=(Resolve-Path notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe).Path
uv run pytest tests/integration/test_narrative_godot_live.py -q --tb=short
```

The test verifies the executable SHA-256, exports to an owned temporary directory,
imports it with the real engine, checks the fixture hash, and rejects a tampered
PNG. It uses a temporary engine profile, not your ordinary editor settings.
Without the explicit environment setting it skips and cannot qualify a release.

For a manual check using your chosen project and qualified engine:

```powershell
& .\notes\toolchains\godot-4.7.2\engine\Godot_v4.7.2-stable_win64_console.exe --headless --path notes/my-first-godot-project --editor --import
& .\notes\toolchains\godot-4.7.2\engine\Godot_v4.7.2-stable_win64_console.exe --headless --path notes/my-first-godot-project -- --verify-content
```

Require `CONTENT_OK:<package hash>` and clean exit, not just project-file presence.
Avoid `--quiet` for this proof: it suppresses the script's content marker.

## Web build boundary

The committed Web preset selects single-threaded Compatibility rendering. Install
matching templates explicitly in your chosen Godot environment, or set that owned
project's `custom_template/debug` and `custom_template/release` preset fields to
the verified task-local `web_nothreads_*` ZIP files. Those machine-specific paths
are qualification overrides, not part of the portable source export.

```powershell
New-Item -ItemType Directory -Path notes/my-web-build -Force
$taskWebOutput=Join-Path (Resolve-Path notes/my-web-build).Path 'index.html'
& .\notes\toolchains\godot-4.7.2\engine\Godot_v4.7.2-stable_win64_console.exe --headless --path notes/my-first-godot-project --export-release Web $taskWebOutput
```

Use an existing owned build directory and an absolute output path if running from
a different working directory. Check generated HTML/JS/WASM/PCK files and actual
content behavior. Producing a web build is not browser gameplay qualification;
the real input/layout/save checks remain #121. Never expose this local bootstrap
as a production authoring/build service or execute creator-provided plugins.
