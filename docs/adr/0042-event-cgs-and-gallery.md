# ADR 0042: Event CG overlays and the player gallery

Date: 2026-10-31. Status: accepted implementation contract for #161 presentation.

Story format 2 stage nodes gain optional `cg`: an image asset ID sets the overlay,
`null` clears it, and omission carries it forward. The image covers the 16:9 stage
using the background's cover-fit rule, above backgrounds and characters and below
dialogue, choices and controls. Stage changes and expressions still update the
underlying state. No art generation, database migration or new asset kind is needed.

Stage views, frames and save schema 2 carry `cg`. Older saves missing that field
load it as `null`; loading validates the whole save before changing state and never
replays stage effects. Existing validation codes apply: `unknown_reference` for an
unknown image, `invalid_asset_kind` for a font, `invalid_id` for a malformed ID,
and `unknown_field` for `cg` in format 1, including `null`.

The gallery lists every distinct CG asset in first structural-use order: depth-first
from the entry, following choice options in declared order and branches true then
false, visiting nodes once. Remaining unreachable nodes follow in sorted ID order.
This is independent of JSON object order, runtime choices and loops. Unseen entries
remain locked and reveal neither their image nor asset name. A CG unlocks when it
is present on a settled line, choice, ending or fault screen, or on a valid loaded
screen. Automatic set-and-clear steps that never reach a screen do not unlock it.

Unlocks are monotonic session state outside slot saves. Godot persists a bounded,
versioned `user://flint_graph/gallery-<story id>.json` using verified sibling writes
and atomic replacement. Restart and loading an earlier slot retain unlocks. Missing
or corrupt gallery files start locked; unknown stored IDs are filtered. Persistence
is local and best effort, like saves. The Studio preview overrides both gallery read
and write hooks, retaining unlocks only until its iframe closes.

The Gallery control opens a paused overlay with locked entries, unlocked image
viewing and Close gallery. Underlying story and toolbar buttons cannot receive
focus or actions. In preview, Escape closes the gallery first and then the iframe.

Python, Godot, preview validation/bridge and the editor model share conformance
fixtures. Runtime 0.5.0 and a freshly prepared builder pin ship this behavior;
older release identities fail closed under the existing runtime availability rule.
