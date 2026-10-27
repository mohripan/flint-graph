# Milestone 30: portable story runtime and Godot proof

Status: in progress, 2026-10-27. [Tracking issue #112](https://github.com/mohripan/flint-graph/issues/112).
The user approved the written design and autonomous implementation with one
review sub-agent. [Plan](../superpowers/plans/2026-10-27-portable-story-runtime.md).

## Delivered boundaries

- #117: strict local package loader, immutable source/asset snapshot, schema/type/
  condition/reference validation, safe inventory/PNG bounds, canonical identity,
  structural warnings and original three-ending fixture with route expectations.
  See the [contract](../architecture/narrative-package-contract.md) and
  [verification](../reports/2026-10-27-narrative-package.md).
- #118: deterministic reference player, bounded actions/trace output, typed state,
  atomic overflow faults, strict revision-bound save/load and a local validate/play
  CLI. [Runtime contract](../architecture/narrative-runtime-contract.md),
  [try it](../runbooks/narrative-local-play.md), and
  [live subprocess verification](../reports/2026-10-27-narrative-reference-player.md).
- #119: trusted editable source export, explicit pinned Godot 4.7.2 toolchain,
  wheel-packaged templates, source/asset hashes and notices. Real import/content
  verification, tamper rejection, web build and Web PCK integrity passed.
  [Contract](../architecture/godot-export-contract.md),
  [toolchain guide](../runbooks/godot-toolchain.md),
  [evidence](../reports/2026-10-27-godot-source-export.md).

Reference terminal/scripted playback and Godot source export work; Godot gameplay
and browser acceptance remain pending. No model, database,
workspace, existing frontend or application service configuration was changed.

## Remaining acceptance

- #120: real Godot runtime/player and reference/save parity.
- #121: actual served web export, browser input/layout proof and developer guide.

M30 remains open until actual engine/browser acceptance passes. Documentation,
valid structure and offline fixtures do not substitute for running the game.
