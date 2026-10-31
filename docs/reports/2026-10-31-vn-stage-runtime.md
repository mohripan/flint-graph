# Story format 2 in Godot: stage view, playtests and release builds (#157 slice 3)

This is slice 3 of [ADR 0040](../adr/0040-visual-novel-stage-theme-and-asset-library.md),
following the [design](../superpowers/specs/2026-10-31-vn-stage-and-asset-library-design.md)
and its "Review changes" section. With it, every runtime plays story format 2: the
Python reference, the Godot player, the playtest validator and release builds.
`FLINT_GRAPH_NARRATIVE_PACKAGE_V2_ENABLED` keeps its `false` default until slice 4 gives
the Studio its stage, theme and sprite editors. The owned local API turns it on.

## Delivered

### Godot runtime 0.3.0

- **Player.** `runtime/player.gd` implements the v2 stage rules exactly as the Python
  reference does:
  - stage nodes are atomic, hide before show, and showing at an occupied slot replaces
    its occupant;
  - expressions apply once when a line settles;
  - `stage` and `speaker_color` appear in views and frames;
  - save schema 2 validates the stage (sprites, positions, order, image background);
  - `automatic_transition_limit` is valid at stage nodes.

  Format 1 is untouched.
- **Stage view.** The new `runtime/vn_view.gd`
  ([player contract](../architecture/godot-player-contract.md)) shows:
  - a cover background, and characters in three slots standing on the bottom edge
    with their aspect kept;
  - a themed text box at the bottom, middle or top, with a name box in the speaker's
    colour;
  - centred themed choices, a compact Save/Load/Restart menu, and "Play again" on
    end and fault screens.

  Clicking the stage or text box, Enter or Space advance a line. The creator's font
  loads from verified bytes, with Lora as fallback. Only on-screen images stay decoded.
- **Bootstrap.** The bootstrap accepts `.ttf`/`.otf` assets with per-kind caps (images
  10 MiB, fonts 8 MiB) and starts the stage view for format 2. Exports give fonts the
  same fixed `keep` remap as PNGs, and the export preset includes them.

### Playtests

- **Asset endpoint.** `GET /v1/narrative/projects/{id}/revisions/{revision}/assets/{key}`
  returns the bytes a revision bound when it was saved. It uses the same binding rule
  as saves, still works after the asset is discarded, and answers 404 for v1
  revisions and unknown keys.
- **Studio.** The Studio fetches each asset and checks its SHA-256, count, per-kind
  cap and the 100 MiB total. Only then does it mount the player. It posts
  `load-snapshot` version 2 with the bytes as transferred `ArrayBuffer`s, and starts
  the load deadline after posting. Format 1 keeps message version 1.
- **Bridge.** `bridge.js` accepts only objects cloned into its own realm, with
  `ArrayBuffer` values, the story's exact asset IDs and per-kind caps. Godot pulls the
  assets one at a time: `FlintPreview.take(i)` copies one buffer into the engine's
  in-memory file system (`engine.copyToFS`), and Godot reads it and deletes the file.
  There is no base64, JSON wrapping or `eval`; the preview CSP still allows only WASM
  compilation.
- **Validator.** `preview/validate_story.gd` ports every v2 rule:
  - typed assets, colours, sprites and the closed theme;
  - stage nodes and expressions;
  - the package identity, built from the sorted asset manifest after checking every
    asset's hash.

  The playtest uses `preview/vn_view.gd`, which disables Save and Load like the format 1
  playtest.

### Release builds

- **Input loading.** `load_release_input` accepts v2 revisions. It re-resolves each
  asset to its bound library row and refuses the build (`input_integrity`) if the
  saved NOTICES no longer match what the server would build. It returns where each
  asset's bytes live. The worker fetches them hash-verified after the database
  transaction commits, then reruns the hash, size, PNG and font checks.
- **Builder.** The builder revalidates everything again and ships the assets and their
  remaps in the source ZIP.
- **Child.** The build child accepts exactly the package manifest's asset files, each
  with its exact remap. It refuses unknown, missing, mismatched or oversized assets,
  other remaps, and the previous runtime version.
- **Size budget.** Uncompressed limits are raised to fit a full 48 MiB asset budget
  beside the 37.7 MiB engine:
  - child output: 64 MiB per file, 96 MiB in total;
  - transport: 100 MiB on the wire;
  - Godot stages pack data under `/tmp`, so the child's `/tmp` tmpfs grows from 16 to
    96 MiB.

  The compressed ZIP and publication caps stay at 64 MiB: PNG data does not compress,
  but the engine deflates to about 10 MiB, so a full budget still fits. If one does
  not, the ZIP encoder fails closed. A test covers that bound.
- **Runtime pin.** `runtime_version` is now 0.3.0 in the toolchain, release identity
  and child. Releases pinned to 0.2.0 now fail retries with `runtime_unavailable`,
  which their history shows.

## Verification

- **Unit and integration tests.**
  - `test_narrative_v2_release.py` (12): attaching assets; v2 exports with font
    remaps; the child's asset rules and output bounds; transfer ceilings; the full
    budget ZIP bound; and the builder with real asset bytes.
  - v2 API tests: revision assets are served as bound, including after discard and
    across projects; the release input resolves sources and refuses drifted notices.
  - Frontend: bridge v2 caps and one-time pulls, plus playtest asset checks (74 tests).
- **Real Godot 4.7.2.** `test_narrative_godot_live.py` (21) compares frames, states
  and saves with the reference on two stage routes. It also checks:
  - save validation on nine broken stages;
  - a stage loop fault;
  - font asset verification and tampering;
  - the stage layout probe (1280×720: text box 4–96% wide ending 24 px above the
    bottom; sprites standing on the bottom edge, centred in their slots).

  The preview validator agrees with Python on 31 v2 cases and all v1 cases.
- **Live, owned stack** ([evidence](evidence/vn-stage-runtime-2026-10-31/qualification.json)):
  - A demo project, "Stage & theme demo", has a v2 revision with two generated
    backgrounds, three sprites and an uploaded static Lora font.
  - **Studio playtest** in headless Edge 156: it fetched all six assets, and the
    player ran the opening, the expression change, the entrance and the choice. A
    v1 project still playtests in the reader layout.
  - **Release build** with the rebuilt builder image: it completed. The source ZIP
    holds all six assets with their remaps, the pack holds their exact bytes, and
    NOTICES carries the asset section.
  - **Released build**, played in headless Edge through the route: stage persistence,
    the expression, the entrance, the choice, the move and hide, then
    Save → Restart → Load restoring the fog stage, and the ending.
- **Gates.**
  - full `uv run pytest`: 1648 passed, 85 skipped;
  - narrative integration on the owned PostgreSQL: 62 passed, 6 skipped;
  - `ruff check` and `mypy` clean; `uv lock --check`;
  - offline migration SQL, compose config and the deterministic eval;
  - frontend tests, typecheck and build.

## Notes and limits

- **Opaque sprites.** Generated portraits are opaque, so a character carries its
  scenery onto the stage. Transparent cutouts are the next sprite step.
- **Default font.** The menu and Continue buttons use the engine's default font; only
  story text, names and choices use the theme font.
- **Browser runs.** The live playtests ran in headless Edge driven over the DevTools
  protocol, because the desktop browser pane was hidden: a hidden pane does not render
  frames, so the player never processes input.
