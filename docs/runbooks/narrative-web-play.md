# Author, validate and play a local narrative game

M30 delivers a portable authored game and editable Godot source. It does not yet
include the M31 browser authoring editor. Gameplay and these local commands need
no searchable corpus, database, model endpoint or platform account.

## Edit and validate

Start from the original CC0 sample in `tests/fixtures/narrative/lantern_archive`.
Copy it to a **new** directory, edit `story.json` in your editor, and keep
`NOTICES.txt` plus referenced PNGs. Never edit a previously released package in
place. Stable node/text/character/asset IDs and typed variables follow the
[package contract](../architecture/narrative-package-contract.md).

```powershell
uv run flint-graph-narrative validate tests/fixtures/narrative/lantern_archive
uv run flint-graph-narrative play tests/fixtures/narrative/lantern_archive --interactive
```

For your own copied package, replace the source argument with its directory.
Validation rejects missing references, incompatible values, unsafe files, invalid
PNG bytes and executable content. Structural warnings are not a guarantee that
every condition-dependent route is reachable. Test your intended routes.

```powershell
Set-Content -Path notes/my-new-route.json -Value '["advance","choose:listen","advance","choose:ask_letter","advance"]' -Encoding utf8NoBOM
uv run flint-graph-narrative play tests/fixtures/narrative/lantern_archive --actions notes/my-new-route.json
uv run flint-graph-narrative export-godot tests/fixtures/narrative/lantern_archive --output notes/my-new-godot-game
```

The output parent must already exist and the target must be new, including when
empty. A failed export is retained for inspection; use another new target.

## Play and customize Godot source

Open the exported `project.godot` with qualified **Godot 4.7.2 stable**, GDScript,
Compatibility renderer. The bootstrap verifies captured content and starts the
player. Use Continue/Enter/Space, numbered choices or click/tap, Save/Load/Restart.
Tab focus has an outline. Long passages scroll inside the fixed toolbar.

Downloaded source is yours to customize under its runtime/content/font/engine
licenses. Re-export creates a new project; custom engine scripts/UI do not sync
back into story JSON. The source compiler only accepts data and PNGs; it does not
execute arbitrary creator plugins. Unity and other Godot versions/platforms need
their own support and qualification.

For manual engine import and Web export with verified matching templates, use
the [pinned toolchain guide](godot-toolchain.md). Serve the generated web directory
over HTTP rather than opening HTML as a file. Serve only intended public build
files, never the repository, `notes/`, private drafts or a whole user directory.

## Repeat the fixture Web qualification

Explicitly obtain and verify the engine/templates as described in that guide.
This helper builds both the original sample and an owned 70-paragraph scrolling
variant with the same trusted runtime. It checks executable/template hashes,
import/content markers, output artifacts and records hashes/logs. It never
downloads tools, installs globally, overwrites an output or starts a server.

```powershell
uv run python tools/narrative/qualify_web.py --engine notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe --templates notes/toolchains/godot-4.7.2/templates --output notes/my-new-web-qualification
uv run python -m http.server 5190 --bind 127.0.0.1 --directory notes/my-new-web-qualification/web
```

Open `http://127.0.0.1:5190/sample/index.html` to play; `/long/index.html`
exercises scrolling. Choose another available port if necessary. A successful
build report initially says `browser_qualified: false`: building is not playing.

For repeatable input proof, use an explicitly selected **agent-browser 0.39.0**
binary and an isolated named session. Load its matching `skills get core` guide
first. Start/open the session before the Node helper; this also avoids an idle
daemon startup inheriting synchronous process pipes on Windows.

```powershell
$taskBrowserCli='C:\path\to\agent-browser-win32-x64.exe'
& $taskBrowserCli --allowed-domains 127.0.0.1 --session narrative-local-qa open http://127.0.0.1:5190/sample/index.html
node tools/narrative/verify_browser.mjs --browser-cli $taskBrowserCli --session narrative-local-qa --url http://127.0.0.1:5190/sample/index.html --long-url http://127.0.0.1:5190/long/index.html --output notes/my-new-browser-evidence
& $taskBrowserCli --session narrative-local-qa close
```

The helper is specific to the original fixture and its long-text variant, not an
arbitrary game's quality gate. It drives actual keys/mouse, checks all endings,
save/reload/Load, desktop/mobile control bounds, long-scroll Continue and browser
errors/console. Its optional `?qa=1` snapshot inspects rendered state and never
drives actions. Review the screenshots visually as well as the JSON result;
Canvas layout is not fully covered by DOM assertions. The normal URL exposes no
QA object. Check that normal mode also loads, accepts input and looks correct.

## Save and browser limits

One local save slot is isolated by package hash. Editing content produces a new
hash and a different slot; v1 deliberately has no silent migration. Save stages
and verifies bytes before replacing the previous slot. Invalid loads preserve the
running session. Browser persistence is best effort: private mode, quota, site
data deletion, browser profile or origin changes can remove access. No account,
cloud save, authoritative achievement or production hosting guarantee is implied.

The [dated browser report](../reports/2026-10-27-narrative-web.md) records actual
qualified engine/browser/viewport versions and retained screenshots. Mobile proof
is a 390×844 Chromium viewport, not physical iOS/Android device certification.
