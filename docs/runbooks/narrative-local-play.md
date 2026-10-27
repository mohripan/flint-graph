# Validate and play an authored game locally

Implemented: package validation and reference terminal/scripted playback (#117,
#118). These commands do not launch the existing API/frontend, use a model, ingest
documents, modify workspaces or install Godot. Engine export/playback is separate
Milestone 30 work.

```powershell
uv run flint-graph-narrative validate tests/fixtures/narrative/lantern_archive
uv run flint-graph-narrative play tests/fixtures/narrative/lantern_archive --interactive
```

The original Lantern Archive fixture has three endings. Press Enter to advance
dialogue, type a listed choice number, or `q` to stop. Listen, then read the letter
to restore the lantern; leave for the quiet ending; accuse for the hasty ending.
The portraits/backgrounds are package assets, but terminal playback is text only.

For a reproducible scripted route, create a UTF-8 file outside the package, for
example `notes/quiet-actions.json`, containing:

```json
["advance", "choose:leave"]
```

Then run:

```powershell
uv run flint-graph-narrative play tests/fixtures/narrative/lantern_archive --actions notes/quiet-actions.json --save-out notes/quiet-save.json
```

The JSON result contains final state/view and normalized route frames. Save output
refuses an existing filename; choose a new path rather than deleting unrelated
data. To restore without more actions, create `notes/no-actions.json` containing
`[]` and run:

```powershell
uv run flint-graph-narrative play tests/fixtures/narrative/lantern_archive --actions notes/no-actions.json --load notes/quiet-save.json
```

State is bound to the complete source package hash. Changes to story, notices or
assets invalidate old saves explicitly. Scripted traces are bounded to 8 MiB and
10,000 actions; interactive output does not record a full route. An error prints
a safe JSON code to stderr and returns nonzero. See the
[runtime/save contract](../architecture/narrative-runtime-contract.md) for exact
limits and the [package contract](../architecture/narrative-package-contract.md)
for supported files, nodes and PNG subset.

This reference player is the oracle for later real Godot/browser conformance.
Passing a route here does not qualify the engine exporter, production operations
or AI story/art quality.
