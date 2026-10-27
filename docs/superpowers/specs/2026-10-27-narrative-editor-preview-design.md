# Manual narrative editor and isolated Godot preview

Scope: M31 #123, following delivered #122. The user authorized autonomous
issue-by-issue continuation and one review agent. This focused design proceeds
under that standing instruction; it adds no paid provider, hosted creator-code
compiler, asset upload or release publishing. Existing Q&A/data remain available.

## Direction and alternatives

Build a writing desk for developers of branching games: project collection,
scene list/forms, navigable route map, characters, typed variables/conditions,
revision history and a playtest of a specific saved revision. A chat interface
does not serve this manual authoring task.

Reuse the actual Godot Player/GameView for preview. A second React interpreter
would create semantic drift. Compiling every revision on an API request would
introduce the isolated-worker/build ledger boundary reserved for #124. Instead,
explicitly build the trusted preview runtime once with the already-pinned engine,
and deliver validated text snapshots through a narrow channel. Ordinary API or
frontend startup never downloads/executes an engine.

Visual direction: cool Ink `#182635`, Slate `#4e6577`, Fog `#dce5ea`, Paper
`#f0f4f6`, Lamp `#d5ae68`, derived from the authored player. Use restrained Lora
for story headings/reading, system sans for controls and monospace for stable IDs.
The signature is the functional route spine: actual scene/choice connections,
not dashboard statistics or a prompt box. A readable writing area takes priority
over decoration. Scope styles to the studio and preserve existing Ask styling.

## Additive application flow

Add Studio as the default workspace page while retaining Ask, Documents and Setup.
Update the generic workspace gate copy to include stories rather than implying
documents are required. Reuse auth/workspace providers and same-origin API calls;
manual creation/playtesting must not consult search readiness or model availability.
The health indicator must distinguish API reachability from optional search-service
readiness so a working narrative API is usable without the old projection stack.

List/create projects with bounded server pagination. Store only selected project
IDs per workspace in localStorage; no source, drafts, tokens or private notices.
Reopen loads the actual server head. Viewer has read-only forms/history/preview;
member or higher edits/saves; lifecycle actions preserve #122's admin policy.

On desktop, a scene rail and writing desk sit beside a route/inspector panel.
Each pane has useful height and visible scrolling. Mobile uses a single primary
scroller with accessible panel selection and wrapped controls; no tiny nested
bottom-left result pane. Provide list/form alternatives to the map. Bound map
rendering to 250 nodes with an explicit limit notice; scene filtering/pagination
can reach every node. All source strings render as text, never HTML or script.

## Draft editing and revision state

Keep a working source object/notices in memory, separate from loaded immutable
revision, current project head and any pending request. Manual controls cover:

- line/speaker/next, ending text/key, choices and option targets;
- character display names and stable IDs;
- boolean/int32/enum declarations and initial values;
- state assignments/increments and ordered branches;
- typed comparison and bounded all/any/not condition trees.

Generate stable ASCII IDs and globally unique text IDs; do not silently rewrite
references when deleting a referenced item. Show missing-reference/type diagnostics
at their backend code/location and offer navigation to the relevant form.
Invalid drafts remain editable; only backend-validated saved revisions may preview.
An optional advanced source view must preserve invalid raw text until corrected;
it must not silently discard duplicate keys or coerce values into a successful save.

Show Saved/Unsaved/Saving/Retry/Conflict clearly. Bound undo history by retained
bytes, not just count. Save supplies the explicit base and a stable key/body for
lost-response retry. Edits after a pending attempt get a fresh identity; retries
of unchanged work reuse it. Do not autosave every keystroke or silently rebase.

A 409 with a recovery ID means the server retained the draft; show that result,
keep the working text and expose the saved conflict plus current head. Loading
history is read-only. Explicitly copying an old/conflict revision into a new draft
against a freshly fetched current head is allowed; no automatic merge/overwrite.
Other 409/503 errors do not mean a new conflict copy exists. Do not duplicate
forks on repeated clicks of an already-acknowledged request.

Warn before abandoning unsaved work on project/page/workspace navigation and
browser unload. On 401/403, sign-out or workspace change, abort/invalidate pending
requests and clear old source/history/preview. Late responses must never populate
a new project or revive inaccessible content. Already displayed snapshots are
not continuously revoked, matching the existing request-time membership contract.

## Trusted preview artifact and data boundary

Treat server-approved IDs such as `constructor` and `prototype` as own map keys,
using Map, null-prototype dictionaries or explicit own-property checks. Do not
mistake inherited JavaScript properties for scenes/variables. Test those valid IDs.

Create an explicit local build helper using the pinned Godot 4.7.2 executable
and matching single-threaded templates. It copies only trusted preview adapters
plus the same Player/GameView/strict parser/font resources used by exports into
a new owned project. Record runtime/toolchain/source/build hashes and keep failed
outputs inspectable. No arbitrary creator scripts/plugins or per-revision engine
process is accepted. Use an original text-only bootstrap; no private project is
embedded in the shared static build.

The preview adapter validates bounded text-only source before constructing the
player, verifies the M30 package hash from exact canonical source/notices and
starts at the revision entry. Reuse the shared deterministic state machine and
visual controls; preview may disable persistent Save/Load to avoid leaving private
playtest state at rest. Normal exported-game behavior remains unchanged. Validate
the web adapter against the Python validator and real native/browser fixtures,
including malformed messages, before claiming it safely accepts dynamic content.

The parent fetches a full authorized revision itself and sends only revision ID,
canonical source/notices and package hash. It never sends bearer tokens, cookies,
workspace membership, prompts, provider keys or API URLs. Previewing an older
revision explicitly labels its identity; unsaved changes are not implied to play.

## Origin isolation and message protocol

Different ports are insufficient cookie isolation. The first qualified local
topology is **editor `http://localhost:5173`**, preview on a different loopback host
**`http://127.0.0.1:<owned-port>`**, API behind Vite's same-origin proxy.
Preview refuses same-host app/child
configuration and never sets cookies or accepts Authorization. Its server serves
only the trusted public build allowlist, not notes/repository directories. Bind
local tooling to loopback. Public production preview hosting needs its own
cookie-scope/HTTPS/gateway qualification and is not claimed by this local proof.

Embed with sandbox permitting scripts and the child's own separate origin, but
no top navigation, popups, forms or downloads. Use restrictive CSP with exact
frame-ancestors, same-host engine resources and no application-network access.
Allow trusted WASM compilation through `wasm-unsafe-eval`, not general
`unsafe-eval`; qualify the actual build under that CSP. No eval or creator HTML
is needed. Keep any Godot JavaScript callback strongly
referenced as required by the official bridge API. Native engine absence remains
a release-blocking explicit skip, not a mock fallback.

The child has one configured trusted parent origin from server-owned configuration,
never a parent origin accepted from an arbitrary message. Parent validates exact
child origin and event.source; child validates exact parent origin and window.parent.
Use a cryptographically random nonce in the URL fragment per disposable iframe
instance (not a query/referrer/server-log value) and strict
protocol/version/field/type/size allowlists. Lifecycle: ready -> one load-snapshot
-> loaded/error -> optional close. Ignore replay/out-of-order/unrelated messages.
Content hash/revision acknowledgments must match the requested snapshot. There is
no arbitrary action, fetch, shell, script or navigation message.

Restart occurs within the trusted game controls; a new requested revision uses
a fresh iframe/nonce. Escape exits preview and returns focus to the host playtest
control, avoiding a canvas keyboard trap. On timeout, close, project change or
access failure, remove listeners and iframe and drop source references. A nonce
binds a window instance, not authorization; the authenticated parent/API remain
part of the trusted computing base.

## Verification seams and delivery

Use tests before behavior at the public editing helper/API transport/message
interfaces, then actual application browser flows. Keep Node's existing test
runner; no speculative UI framework migration. Test graph/reference edits,
typed conditions, immutable base handling, stable retries, persisted conflicts,
bounded history and stale-response suppression. Treat message payloads as data.

Actual browser proof must create a project, author characters/scenes/choices and
state, save, play a selected revision in the actual Godot iframe, follow a gated
route, reopen/reload and recover a concurrent edit. Inspect desktop and 390px
layouts, all relevant scroll areas, keyboard focus/Escape and console/network
errors. Set a synthetic app-origin cookie and verify the isolated preview receives
neither it nor Authorization; reject wrong-origin/window/nonce/oversized messages.
No model or document index may be required. Retain dated screenshots/reports.

Run frontend outcome tests/typecheck/build and relevant backend/native gates.
Reuse the single review agent. Deliver focused commits (editor, trusted preview,
acceptance/docs as appropriate), preserve #109 WIP and existing Q&A/data, push and
require green CI before closing #123. Continue #124 afterward; do not claim a full
production studio, release sandbox, hosted preview deployment or AI/art quality.

Primary references reviewed 2026-10-27:

- [Godot JavaScriptBridge](https://docs.godotengine.org/en/stable/classes/class_javascriptbridge.html).
- [Godot custom Web shell](https://docs.godotengine.org/en/stable/tutorials/platform/web/customizing_html5_shell.html).
- [Godot shell API](https://docs.godotengine.org/en/stable/tutorials/platform/web/html5_shell_classref.html) warns it may lag 4.7; actual pinned-engine proof is required.
- [RFC 6265 cookie scope and port isolation](https://www.rfc-editor.org/rfc/rfc6265.html).
