# Scene hierarchy and script editor for long-form stories (#169)

The user found the one-card-per-line scene list unusable for long visual novels and
asked for Unity/Godot-style grouping with drag and drop. Delivered:

- **Scenes, not lines.** The Studio groups consecutive lines and state changes with
  the choice, condition or ending that closes them into one scene (an editor
  projection; the story format and runtime are unchanged). The rail lists scenes.
- **Hierarchy.** Nested folders (route → chapter → folder, up to four levels) with
  drag and drop (pointer events: mouse, touch and automation), drop indicators,
  edge auto-scroll, Alt + arrow moves, F2 rename, collapse, search that reveals
  matches inside collapsed folders, and only visible rows rendered.
- **Shared layout.** Migration 0021 stores an editor-only, versioned layout per
  project (`GET/PUT /v1/narrative/projects/{id}/layout`): viewers read, members
  write, stale saves return 409 and the client adopts the newer layout. Layout
  never changes story content, revisions, packages or exports. New scenes appear
  beside the scene they grew from.
- **Script editor.** Selecting a scene shows every line in order with its speaker,
  inline state changes, "Add line below"/Ctrl+Enter, removal that reconnects
  routes, the closing choice/condition/ending form, and a safe whole-scene delete.
- **Studio shell.** The GraphRAG Ask and Documents pages are hidden; their code and
  API remain for project lore sources and story questions later.

## Long-form measurement

A generated story through the real API: 20 chapters × 80 scenes, 5 lines each plus
a branching choice — 9,602 nodes, 8,000 dialogue lines, 2.46 MB, saved in 0.31 s.
In the browser against the owned API:

- 1,602 scenes listed with 28 rows in the DOM; search over all scenes in 5 ms.
- Typing in a line took ~270 ms per keystroke at first: every choice's route picker
  rendered all 9,602 nodes (19,240 `<option>` elements) and each edit re-parsed the
  story. Pickers now list scenes from a memoized list, edits reuse the edited
  object and undo snapshots are built lazily: ~21 ms per keystroke.
- Real mouse drags moved scenes with the expected before/after semantics and saved
  (layout versions 2–4); Alt+↑ moved a scene and kept focus (version 5). A status
  message above the list shifted rows under the pointer; messages now render below.
- At 375×812 the Scenes tab shows the tree full width and opens a one-column script.

About 8,000 lines is roughly 200k words (~550 pages) and already near the package
limit of 10,000 nodes and 5 MB. A 20-hour, ~800-page game needs the long-form
package/storage work tracked in #172 (with #157).

## Verification

- Layout API: 28 passed on SQLite and the owned PostgreSQL (`FLINT_GRAPH_NARRATIVE_PG_URL`).
- Frontend: `npm test` 55 passed (scene projection, tree moves/limits/normalization,
  line insert/remove, layout API), `npm run typecheck`, `npm run build`.
- Backend gates: full `uv run pytest`, `uv run ruff check .`, `uv run mypy`,
  `uv lock --check`, offline migration SQL (1327 lines), compose config, diff check
  and the deterministic evaluation.

On Windows the Vite dev server sometimes kept stale transforms after edits; touching
the changed files refreshed them. Production builds were unaffected.
