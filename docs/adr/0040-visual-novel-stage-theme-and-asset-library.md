# ADR 0040: Visual novel stage, theme and asset library (story package v2)

Date: 2026-10-31. Status: accepted for implementation (tracking #157, #128, #161,
#164; the user chose this order on 2026-10-31). This records intent, not delivered
behavior.

## Context

Package v1 renders every screen only from its current node. A `line` may name one
background and one portrait, missing visuals clear their slot, and choices and
endings clear all visuals (spec 2026-10-27). That rule kept saves reproducible.
But a visual novel keeps its scene on screen: the background and the characters
present persist, while lines only change who speaks and how they look. The Godot
runtime also lays the story out like a document (title, toolbar, picture strip,
text panel), whereas the user expects a full-screen stage with a styled textbox,
usually at the bottom, using their own fonts. Studio snapshots are text-only: there
is no way to bring images or fonts into a story, and release builds reject assets.

## Decision

1. **Package v2 adds persistent stage state.** `schema_version: "2"` stories add:
   - a `stage` node type, which sets or clears the background and shows, moves or
     hides characters at `left`, `center` or `right`;
   - an optional line `expression` that changes the speaker's on-stage sprite;
   - per-character `sprites` (expression → image asset) and an optional name
     colour;
   - a closed, bounded `theme` (textbox position, width, colours, corner radius,
     name box, choice style, built-in or uploaded font and size);
   - typed asset kinds (`image`, `font`).
   Stage nodes execute automatically like `set` nodes, atomically and within the
   same 1,000-step bound. Stage state (background plus ordered characters with
   sprite and position) is part of execution state, persists through lines,
   choices and endings, and is saved by save schema `2`.
2. **v1 is preserved.** v1 packages, releases and saves keep their exact semantics
   and the existing reader layout. The Studio upgrades a project only through an
   explicit action that creates a new revision; nothing is rewritten silently. A v1
   story whose lines carry visuals is not upgraded automatically.
3. **One runtime contract.** The Python reference player and the Godot player
   implement the same v2 semantics and produce identical normalized traces,
   including stage state. Godot renders v2 with a visual novel layout: full-screen
   stage, character layer, themed textbox overlay, name box, centred choices and a
   compact menu. Fonts load from verified package bytes; text stays plain.
4. **The project asset library is the only source of story assets.** Images
   (PNG, alpha kept) and fonts (TrueType/OpenType) enter by upload, with a
   recorded rights declaration, licence and notice (a declaration, not ownership
   verification), or by local generation (ADR 0039, candidates until approved).
   A revision may reference only approved library assets of its own project, by
   SHA-256. Previews and builds fetch the bytes create-only and hash-verified;
   NOTICES gain a deterministic section built from the immutable asset metadata.
5. **Backgrounds** are generated through the existing ADR 0039 job pipeline with a
   landscape size and a no-people prompt. Character sprite generation (transparent
   full body, expression and pose sets) follows as its own slice on this format.

## Alternatives and consequences

Extending v1 with carried-over visuals would silently change the meaning of
existing packages and saves. Keeping per-line visuals would force creators to
repeat the background on every line and could not express characters entering and
leaving. A free-form layout or arbitrary styling language would bring the script
and styling risks the package format excludes. The closed theme can widen later
behind new versions.

Consequences:
- Four implementations must agree: Python validation and player, the GDScript
  preview validator, the Godot player, and the editor model. Conformance traces
  guard that agreement.
- The playtest bridge carries asset bytes (bounded, hash-checked), and the release
  builder accepts assets.
- New projects can default to v2 only after all of these land.

## References

- [Design](../superpowers/specs/2026-10-31-vn-stage-and-asset-library-design.md).
- [Portable runtime spec](../superpowers/specs/2026-10-27-portable-story-runtime-design.md),
  [ADR 0035](0035-authored-narrative-games-and-portable-godot-export.md),
  [ADR 0039](0039-local-gpu-image-generation-in-an-isolated-child.md).
