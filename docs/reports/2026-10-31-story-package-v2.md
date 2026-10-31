# Story package v2: stage, expressions, theme and asset binding (#157 slice 2)

This is slice 2 of [ADR 0040](../adr/0040-visual-novel-stage-theme-and-asset-library.md),
following the [design](../superpowers/specs/2026-10-31-vn-stage-and-asset-library-design.md)
and its "Review changes" section. v2 stays behind
`FLINT_GRAPH_NARRATIVE_PACKAGE_V2_ENABLED`, off by default. Slice 3 (the Godot runtime,
playtest bridge and release builds) is needed before creators can play v2 stories.

## Delivered

### Format and validation

`schema_version: "2"` adds:
- typed assets: `image` (`.png`) and `font` (`.ttf`/`.otf`);
- character `color` and `sprites` (up to 32 expressions, each an image asset);
- a closed, all-optional `theme` (textbox position, width, colours and radius; name
  box; choice colours; font asset and size);
- `stage` nodes (background set or clear, `hide`, and `show` at left, center or right);
- a line `expression`.

The stage rules from the review are enforced with stable error codes:
- a stage node must have an effect;
- `hide` and `show` entries are unique, and positions are unique;
- no character may be both hidden and shown;
- assets must be the right kind;
- an expression needs a speaker who has that sprite.

A forward analysis warns (`expression_off_stage`) only when a line's speaker is off
stage on every path. v1 validation keeps its exact fields and check order; only the
`"2"` schema value moved from rejected to accepted.

### Reference player

- Stage state starts empty, persists across lines, choices, endings and faults, and is
  part of `state`, `view` and `frame`.
- Stage nodes apply atomically within the 1,000-step bound: hide first, then show, and
  showing at an occupied slot replaces its occupant. Characters stay in left, center,
  right order.
- An expression applies once, when its line settles. Saves record the result; loading
  never reapplies it.
- Save schema `2` validates the stage (known image background, known characters and
  sprites, unique positions in order). The `automatic_transition_limit` fault is
  valid at stage nodes.
- v1 views, frames and saves are unchanged and have no `stage` key.

### Save path

- **Binding.** v2 saves bind each story asset by SHA-256 to an asset in the same tenant
  and project that was approved at some point; the earliest such row decides, and the
  rows are locked. Unknown, unapproved or foreign hashes all give the same 422
  (`unknown-asset`). Kind and font-extension mismatches give `asset-kind`. Assets over
  the size budget give `asset-budget` (`FLINT_GRAPH_NARRATIVE_PACKAGE_V2_ASSET_BUDGET_BYTES`,
  default 48 MiB). Discarding an asset later never breaks a saved binding.
- **NOTICES.** The server rebuilds an "Asset notices" section after a fixed marker. It
  uses only immutable fields (story asset ID, kind, SHA-256, licence, source and
  generator model, notice), grouped by identical text. Anything a client sends after
  the marker is replaced. Re-saving gives identical notices and content hash.
- **Upgrade and gate.** `POST /v1/narrative/projects/{id}/upgrade` creates the v2
  revision of a v1 story explicitly. It is idempotent and refuses v1 stories with
  per-line pictures. Entering v2 is gated by the flag; stories that are already v2 stay
  editable when the flag is off.

### Editor model and assistant

- **Editor.** Types cover v2. Stage steps belong to scenes like state changes, show as
  a readable summary in the script, can be removed with routes reconnected, and block
  deleting a character they place. v2 drafts load in the Studio.
- **Assistant.** Renaming a character keeps its sprites and colour. The story outline
  shows stage steps, expressions and each character's expressions. The pinned prompt
  template is unchanged.

## Verification

- Unit tests:
  - v2 format: 34;
  - v2 player: 16;
  - the existing package, player and story-edit suites, with two cases updated from
    `"2"` to `"3"` as the unsupported version;
  - assistant context and operations.
- Integration: v2 save path (upgrade, gate, binding, notices, budget) and the project,
  asset and assistant APIs pass on SQLite and the owned PostgreSQL (68 passed,
  4 skipped).
- Frontend: `npm test` 71, typecheck and build.
- Gates: full `uv run pytest`, `ruff check`, `mypy`, `uv lock --check`, offline
  migration SQL, compose config and the deterministic eval.

There is no browser qualification for this slice: nothing user-visible changes while
the flag is off. The owned API keeps it off until slice 3.
