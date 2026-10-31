# Studio editors for stage, theme and expressions (#157 slice 4)

This is the last slice of [ADR 0040](../adr/0040-visual-novel-stage-theme-and-asset-library.md).
Creators can now build a visual novel in the Studio: backgrounds and characters on
stage, expressions per line, a styled text box with their own font, and the upgrade of
format 1 stories. Story format 2 is the default: `narrative_package_v2_enabled` now
defaults to on, and new projects start on v2. With it off, new projects stay on v1.

## Delivered

- **Look tab.** The theme editor covers:
  - the text box: position, width, background with opacity, text, border and corner
    radius;
  - the name box: shown or hidden, and its colours;
  - choice colours;
  - the font (built-in Lora or an approved TTF/OTF) and its size.

  Fields equal to the defaults stay out of the story, and Reset removes the theme.
  The live preview is drawn to scale (container query units over a 1280-wide stage)
  with the runtime's rules: the theme font, the speaker's colour filling the name box
  with readable ink, the choice placement, and the story's first background and
  sprite.
- **Scene stage.** A panel above each scene's lines edits the stage step that opens
  the scene: background (keep, none, or a library image), characters placed with an
  expression and a slot, and who leaves.
  - **Keeping the scene.** Writing the step keeps the scene's ID: the stage step
    takes the ID, and the old opening node moves just after it. Folder placement,
    incoming routes and the story's entry stay put. Clearing the step folds the next
    node back under the ID.
  - **Earlier scenes.** "From earlier scenes" comes from a forward analysis that
    mirrors the validator's: every path is followed, line expressions count, and
    disagreeing paths show "varies by path". It runs on a deferred copy of the story,
    so typing stays fast.
- **Lines.** When the speaker has expressions, an expression picker sits under the
  speaker. Changing the speaker drops an expression the new speaker lacks.
- **Characters → On stage.** Each character has a name colour and expression sprites
  chosen from approved sprites, images or portraits. Removing an expression still in
  use is refused, with the use count. Approving a transparent sprite refreshes the
  pickers.
- **Assets in the story.** Picking a library file binds it by SHA-256 under a
  readable unique ID derived from its name (reserved device names and the 256-asset
  limit are respected). The same file always reuses its key. Editor operations prune
  story assets nothing refers to, so games never ship stray files. One shared,
  refreshable list of approved assets serves every picker.
- **Upgrade and new projects.**
  - A format 1 story shows "Use stage & theme" in Look, Characters and each scene.
    It calls the idempotent upgrade endpoint and loads the new revision.
  - `create_project` takes the schema from the flag.
  - Tests that need a v1 project now create one explicitly.

## Verification

- **Frontend.** 80 tests (5 new for the stage model: binding, theme, scene stage
  steps, inherited stage, and expressions and sprites), typecheck and build.
- **Server.** Narrative unit and integration suites, including a new test that new
  projects start on v2 unless disabled. Full `uv run pytest`, `ruff check` and `mypy`.
- **Live, owned stack**
  ([evidence](evidence/vn-studio-editors-2026-10-31/qualification.json)): headless Edge
  156 drove the real Studio at 1366×900 and 390×844.
  - **Scene stage.** The scene stage showed the bound background thumbnail and the
    placed characters. The background picker listed approved backgrounds, and
    choosing one and placing a second character worked.
  - **Earlier scenes.** A later scene showed the inherited stage (fog background,
    Quen smiling at left, Mira at right) and Mira leaving.
  - **Look and Characters.** The Look tab moved the text box to the top at 70% width
    with a larger font. The character sheet listed expressions with their uses.
  - **Save and playtest.** Saving produced revision 4, which the server accepted. The
    Godot playtest of it showed the text box at the top at 70% width, the new
    background, both characters and the uploaded font.
  - **Release.** A real release build of revision 4 completed (web ZIP 14.1 MB).
  - **Upgrade.** A format 1 project showed the upgrade notice with the form disabled;
    upgrading created revision 3 and enabled the form.
  - **Layout.** At phone width the page has no horizontal scroll and the preview
    comes first.
  - **Fixes from the run.** A squeezed speaker picker (the expression now sits under
    it) and a centred "Place a character" link.

## Limits

- The preview approximates Godot's text layout with the browser's; line breaks can
  differ slightly.
- The stage panel edits only the step that opens a scene. Stage steps elsewhere still
  show as summary rows with Remove, and can be edited in Source.
- Library pickers list up to 384 approved assets per project.
