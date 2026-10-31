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

## Start everything

The scene stage panel shows effective background/CG thumbnails. **From earlier
scenes: …** means the image is inherited and stays visible; it does not mean the
background is empty. **None from earlier scenes** means no image is carried,
and **Varies by path** means incoming routes disagree. Choosing **No background**
or **Clear CG** explicitly clears that layer; **Keep earlier** removes the local
override. Merely inspecting a scene does not copy inherited state into its nodes.

Background generation started in Assistant also appears in Assets, with progress
visible under every asset filter. Returning to Assistant restores the same server
job instead of offering a duplicate generation. See the
[assistant image-action report](../reports/2026-10-31-assistant-image-actions.md).

```bash
uv run python tools/narrative/studio.py
```

The launcher reads `studio.local.env` at the repository root, a git-ignored copy of
[`tools/narrative/studio.env.example`](../../tools/narrative/studio.env.example)
that documents every line. `FLINT_GRAPH_*` lines are the app's settings and go only
to the API and workers. `STUDIO_*` lines choose the services, ports, Docker
containers and playtest build. In order, it:

1. starts the listed Docker containers that are stopped (PostgreSQL, MinIO,
   Temporal), then waits for them and, when the assistant or image worker runs, for
   Ollama;
2. refuses to start when a port is taken, `frontend/node_modules` is missing, or the
   playtest build was made for another frontend origin or Godot runtime version
   (rebuild it as below);
3. applies `alembic upgrade head` (`--no-migrate` skips it);
4. runs the API, the release worker and relay, the assistant and image workers, the
   playtest server and the frontend, prefixing each line of output with its name,
   and prints `ready` once the API, playtest and frontend answer.

Ctrl+C stops every process it started. Closing the window or killing the launcher
ends them too. `check` runs steps 1 and 2 only. `STUDIO_SERVICES` runs a subset,
for example `api,preview,frontend` without the GPU and model workers. After editing
the image content policy or settings, restart the launcher.

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
The Godot adapter strictly validates the story and exact package identity before
creating the shared player. For story format 2 the Studio first fetches each image and
font from `GET .../revisions/{id}/assets/{key}` (the bytes bound at save), checks
every SHA-256, and sends them as transferred `ArrayBuffer`s (message version 2); the
player pulls them one at a time into its in-memory file system and checks the hashes
again. Format 1 keeps message version 1. Playtest needs
`VITE_FLINT_GRAPH_PREVIEW_ORIGIN` (for example `http://127.0.0.1:5192`) set for the
frontend dev server. It receives no application token, workspace ID
or API URL. The iframe cannot open popups, navigate the top page, submit forms or
download. Local preview CSP permits trusted WASM compilation, without general eval.

Playtest progress stays in memory; its Save/Load buttons are disabled. Restart uses
the shared deterministic player. Escape closes the preview and returns focus to its
opener. Close/timeouts/access loss remove the iframe/listener. Normal exported-game
Save/Load behavior is unchanged. `?qa=1` on the editor explicitly enables the shared
read-only runtime probe in the child; normal URLs expose no probe.

## Stage, look and expressions (story format 2)

New projects start on story format 2. A format 1 story shows **Use stage & theme**
(Look, Characters and each scene). It saves a new revision; save or undo pending
changes first. Stories with per-line pictures from format 1 cannot be upgraded.

- **Assets:** approve or upload backgrounds, sprites and fonts first. Pickers list
  approved assets only. Choosing one adds it to the story under an ID made from its
  name; files the story no longer uses are dropped from it.
- **Assets → CGs:** browse full-scene illustrations and other image uploads. **Upload CG**
  selects the CG / image kind; PNG files use the same rights declaration and approval
  rules as other library files. Choose an approved image in **Write → Stage → Event CG**
  to show it in the story. The CGs view keeps the background generator out of the way.
- **Characters → On stage:** set a name colour (with opacity) and add expressions. Each expression
  is an approved sprite, image or portrait. Removing an expression the story still
  uses is refused, with a count of where it is used. **Size on stage** sets how tall
  the character is drawn (as % of the screen) and where the top edge sits; above 100%
  the figure is cut off below the screen, as visual novels usually show characters.
  The preview uses the story's first background.
- **Write → Stage:** the panel above a scene's lines writes the stage step that opens
  the scene. Choose a background (or keep the earlier one, or none), place
  characters with an expression at left, center or right (each with a **Place**
  slider to move them anywhere across the screen), and tick who leaves. "From
  earlier scenes" shows what is already on stage on every path; "varies by path" means
  routes disagree. The scene keeps its ID, folder and routes.
- **Lines:** when the speaker has expressions, an expression picker sits under the
  speaker; it changes their sprite from that line on.
- **Write → Stage → Event CG:** choose an existing story image or an approved library
  image. It fills the stage over the background and characters, while dialogue and
  choices keep running. **Clear CG** reveals the stage underneath; **Keep earlier CG**
  leaves the previous overlay alone. The scene preview shows the same layering.
  Source stage steps use `"cg": "image_id"` or `"cg": null`; only format 2 accepts it.
- **Player → Gallery:** every CG is listed in stable first-use order. Seen CGs unlock;
  other entries show Locked. Gallery pauses the story until closed. Exports retain
  unlocks locally across Restart, Load and reopening, independently of save slots,
  in `user://flint_graph/gallery-<story id>.json`. Old slot saves remain valid and
  restore without a CG. Playtest unlocks stay in memory until it closes. Escape
  closes its gallery before closing the playtest.
- **Look:** text box position, width, colours and corner radius; the name box;
  choice colours (text box, name box and choice backgrounds have an opacity slider);
  and the font (built-in Lora or an uploaded static TTF/OTF) and its
  size. The preview is drawn to scale with the runtime's rules. **Reset to defaults**
  removes the theme.

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
