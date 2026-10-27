# Milestone 30: portable story runtime and Godot proof

Status: acceptance passed, 2026-10-27; final browser-tooling CI/issue closure pending.
[Tracking issue #112](https://github.com/mohripan/flint-graph/issues/112).
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

- #120: trusted Godot runtime 0.2.0, playable responsive UI, strict saves/parser,
  stale-input protection and native reference/save conformance.
  [Contract](../architecture/godot-player-contract.md),
  [evidence](../reports/2026-10-27-godot-player.md).

- #121: actual served single-threaded web export, 16-step browser input proof,
  three endings, save/reload/restore, desktop/mobile long-text scrolling and
  retained screenshots. [Developer guide](../runbooks/narrative-web-play.md),
  [dated browser proof](../reports/2026-10-27-narrative-web.md).

Reference playback, Godot gameplay/source export and browser acceptance work.
No model, database,
workspace, existing frontend or application service configuration was changed.

## Delivery boundary

The actual engine/browser acceptance has passed; #121's tooling/docs commit must
also pass ordinary CI before issue/milestone closure. M31 project/revision APIs
and authoring editor remain pending. M30 proves a short original authored game,
not AI story/image quality or a complete production studio.
