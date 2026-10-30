# Manual studio and local Godot playtest

Studio is the default workspace page. It uses the authorized project/revision API
from #122; member or higher can create and save, viewer can inspect saved sources
and playtest. Ask, Documents and Setup remain available. The API status indicator
reports process reachability; search readiness still gates the document Ask flow.

Create a story, edit scenes/characters/state, connect destinations and save a
revision. The scene list and forms are alternatives to the route map. Map display
is bounded to 250 scenes/1,000 connections with notices; list filtering/pagination
can reach the remainder. The graph shows structural links, without predicting
conditions. Use History to inspect immutable snapshots. Copying a snapshot into a
new draft explicitly fetches the current head; saving still uses compare-and-swap.
Conflicts retain the author's text in a server revision and leave the current head
intact. Inspect both versions before choosing a draft. Source mode keeps raw invalid
or duplicate-key JSON intact; only strict successful saves can return it to forms.

Ctrl/Command+S saves. Undo/redo retains at most 50 snapshots and 8 MiB of UTF-8
history, coalescing typing in one field; drafts are in memory until explicitly saved.
Page/project/workspace navigation and browser unload warn about unsaved changes.
Only selected workspace/project IDs are stored locally. Authorization failures clear
displayed studio content and invalidate pending requests. Reload workspaces to
recover access. Archive/restore remains available through the admin API.

## Build the trusted preview explicitly

Use the verified official Godot 4.7.2 engine/templates from the
[toolchain guide](narrative-web-play.md). Ordinary startup/tests never install or
download them. On Windows, from the repository root, with task-local verified files:

```powershell
uv run python tools/narrative/build_preview.py --engine notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe --templates notes/toolchains/godot-4.7.2/templates --parent-origin http://localhost:5173 --output C:/Projects/flint-graph/notes/my-new-preview
uv run python tools/narrative/serve_preview.py --build notes/my-new-preview --port 5192
```

Output must be a new directory under a real existing parent. Failed builds remain
inspectable with logs; choose a new output for retries. The helper verifies exact
engine/template hashes and builds only repository-owned adapters plus the shared
Player/GameView/parser/font. It embeds no creator project. The manifest records
source/build hashes. The server loads a verified immutable file snapshot, serves
an allowlist only, binds 127.0.0.1 and rejects credentials. Keep it running separately.

Start the frontend in another terminal (API proxy target can be overridden):

```powershell
cd frontend
$env:VITE_FLINT_GRAPH_PREVIEW_ORIGIN='http://127.0.0.1:5192'
$env:FLINT_GRAPH_API_TARGET='http://localhost:8000'
npm run dev -- --host localhost --strictPort
```

Open **http://localhost:5173**, using the exact parent origin supplied at build time.
The child is **http://127.0.0.1:5192**. Different ports on the same host do not isolate
cookies; the parent refuses same-host preview configuration. The child server only
trusts its configured localhost parent. No CORS proxy to the application is exposed
from the child. Use the normal persistent backend for real authoring; the disposable
database used in the delivery report is only a qualification fixture.

## Play a saved revision

Playtest labels the revision number; Save & playtest first saves and then plays only
the acknowledged revision. History can play a specific older/conflict revision.
The parent sends only canonical source/notices, revision ID and content hash through
an exact origin/window/nonce-bound channel. The nonce stays in the iframe fragment.
The Godot adapter strictly validates the text-only story and exact package identity
before creating the shared player. It receives no application token, workspace ID
or API URL. The iframe cannot open popups, navigate the top page, submit forms or
download. Local preview CSP permits trusted WASM compilation, without general eval.

Playtest progress stays in memory; its Save/Load buttons are disabled. Restart uses
the shared deterministic player. Escape closes the preview and returns focus to its
opener. Close/timeouts/access loss remove the iframe/listener. Normal exported-game
Save/Load behavior is unchanged. `?qa=1` on the editor explicitly enables the shared
read-only runtime probe in the child; normal URLs expose no probe.

## Build and download a release

**Releases** opens the server-backed release dialog. Choose a saved revision; it
defaults to the current one and lists conflict copies explicitly. Then select
**Build release**. Unsaved edits are never built; the dialog offers to save them
first. Builds run on the separate narrative worker, so closing the dialog or
reloading the page does not lose them. Members can cancel active work and retry
failed or cancelled attempts. Viewers can follow history and download.

A ready release offers **Godot source**, **Browser build** and **Release details
(JSON)**. Each download is fetched with your session and checked for size and
SHA-256 in the browser before it is saved. **View saved revision** opens that
revision's snapshot, from which **Playtest this revision** plays exactly what was
built. Building requires the operator setup in the
[worker runbook](narrative-build-worker.md). Without it, new requests return a
clear "not configured" error while authoring and preview keep working.

## Verification and limits

Run `npm test`, `npm run typecheck`, `npm run build` in frontend. Run Python gates
from AGENTS.md. For the actual dynamic validator boundary:

```powershell
$env:FLINT_GRAPH_NARRATIVE_GODOT_BIN=(Resolve-Path notes/toolchains/godot-4.7.2/engine/Godot_v4.7.2-stable_win64.exe).Path
uv run pytest tests/integration/test_narrative_preview_live.py -q --tb=short
```

Without explicit engine configuration this native test is an explicit skip, not a
mock success. Test real browser author/save/reload/history/conflict, desktop/390px,
keyboard Enter/choice keys/Escape and actual scrolling. Inspect screenshots and
console/network errors. See the [delivery report](../reports/2026-10-30-narrative-studio.md).

This delivery qualifies the local separate-host topology. Durable build jobs and
authorized release artifacts are delivered by #124; see the
[Releases UI report](../reports/2026-10-30-narrative-releases-ui.md). Production
HTTPS/cookie scope/gateway hosting, isolated creator-code compilation and asset
authoring are later work.
No paid model or inference service is enabled by these flows.
