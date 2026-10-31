# Godot authored player

M30 / #120, trusted runtime **0.4.0** (story format 2 with stage framing, ADR 0040), qualified with Godot
`4.7.2.stable.official.ed1daf0bf` on Windows x86-64. The exported source runs
without the backend, a model, credentials or an account. The compiler supplies a
strictly validated immutable package; arbitrary creator scripts are not inputs.

## Execution and display

`runtime/player.gd` implements the [reference runtime](narrative-runtime-contract.md):
line, choice, atomic set, ordered branch and end nodes; boolean, enum and signed
32-bit integer state; exact conditions; a 1,000 automatic-transition limit; and
explicit overflow/empty-choice faults. Actions are accepted only at the right
settled node. Invalid or stale actions preserve state and callback generation.

`runtime/strict_json.gd` validates bounded UTF-8 JSON, duplicate keys, string
escapes, surrogate pairs, integer grammar and depth before constructing values.
Godot's permissive general JSON parser is insufficient for the save contract.
Floating-point literals and implicit boolean/integer conversions are rejected.

`runtime/game_view.gd` displays plain story text, speaker, current-node background
and portrait, choices, Continue, Save, Load and Restart. Choice/end/fault screens
clear prior artwork. Only the current two decoded textures are retained; compressed
asset bytes come from the verified bootstrap snapshot. No URLs or story markup
are executed. Enter/Space advance lines, digits 1–9 choose visible options, and
Tab moves between focusable controls. Other choices remain clickable.

The main reading area scrolls inside a fixed toolbar. Text wraps at the actual
viewport width; below 600px it uses smaller margins/artwork and 20px dialogue.
Controls have at least 46px height and a visible focus outline. The Lora font is
vendored with OFL license and content-addressed provenance under `fonts/`; source
and compiled exports preserve those notices. This is a starter player, not the
M31 authoring editor, a screen-reader-qualified UI or a localization guarantee.

## Story format 2: the stage view

Runtime 0.3.0 plays `schema_version: "2"` stories with `runtime/vn_view.gd`; format 1
keeps `game_view.gd` and its exact behavior. `player.gd` adds the persistent stage
(background plus characters at left, center or right), stage nodes applied atomically
within the transition bound, line expressions applied once when a line settles,
`speaker_color` and `stage` in views and frames, and save schema 2 with full stage
validation. Native conformance compares frames, states and saves with the Python
reference on stage routes.

The view draws the background to cover the screen, each character's sprite at its
slot standing on the bottom edge with its aspect kept, and the themed text box:
position (bottom, middle or top), width, colours, corner radius and a name box that
takes the speaker's colour when set. Choices are centred buttons in the theme's
colours; Save, Load and Restart sit at the top right; end and fault screens offer
Play again. Clicking the stage or text box, Enter or Space advance a line. A
creator font loads as a `FontFile` from its verified package bytes, with Lora as
fallback; text stays plain (BBCode off). Only on-screen images stay decoded.

Runtime 0.4.0 adds framing. A character's optional `stage` framing sets the drawn height as
% of the screen (40–300) and the top edge as % of its height (−50–100, default
`max(0, 100 − scale)`). Taller figures continue below the screen, which clips them;
without framing a sprite fits its slot as before. A placement's optional `x` (0–100)
is its horizontal centre and is part of the stage state and saves; the slot still
decides who replaces whom.

## Local saves and stale input

Save JSON is bounded to 6 MiB and tied to the complete package hash. It contains
settled node, typed variables, status, ending/fault and schema version, without
executable objects or paths. Load validates everything before replacing session
state. A different package, malformed save or unavailable storage leaves the
running state unchanged. Restoring redisplays without repeating assignments.

`runtime/save_store.gd` uses `user://flint_graph/<package hash>/game.json`.
It writes a random sibling candidate, flushes, reads back exact bytes and only
then renames over the previous save. Write, verification and rename failures
preserve the previous file. Failed candidates remain inspectable; no automatic
deletion/retry is performed. This is a local filesystem publication sequence,
not a promise against power loss or a hostile host. Browser persistence uses
Godot's local storage support and remains best effort; private mode, quota, site
data deletion or a different origin can lose access. There is one slot per
package revision, no cloud sync and no silent save migration.

Action buttons capture both the Player instance and its generation. Restart
creates a new instance; a queued callback from its predecessor is rejected even
when both instances start at generation zero. Loads invalidate prior callbacks.

## Qualification and inspection

The opt-in native suite executes the pinned real engine, with isolated temporary
profiles and timeouts, against original routes, malformed saves, numeric/Unicode
boundaries, invalid actions, automatic faults, large saves and real UI signals.
Save fault injection occurs at the native filesystem boundary and checks actual
previous bytes. A separate verified-template test builds the actual Web PCK and
reads content and licensing bytes from the pack without loose source fallback.
Ordinary tests never download/start an engine; absent explicit tool paths skip
native qualification and cannot qualify a release.

Browser exports accept an optional exact `?qa=1` flag. It publishes a data-only
copy of the current rendered view, controls, local-save availability, notice and
viewport as `window.__flintNarrativeQA`. It exposes no action bridge, variables,
private drafts or model context and is absent by default. Browser tests use real
mouse/keyboard input; this snapshot is inspection rather than gameplay control.
It must not be used as a production authorization or anti-cheat boundary.

See the [toolchain runbook](../runbooks/godot-toolchain.md),
[native delivery evidence](../reports/2026-10-27-godot-player.md) and M30 #121 for
the separately recorded browser qualification.
