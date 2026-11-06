# Standard player controls (#164, #160; runtime 0.8.0)

Delivered [ADR 0064](../adr/0064-standard-player-controls.md). Format 2 games now have:

- **Log**: the session's lines with speaker names and the choices taken, shown as plain text.
- **Auto**: advances after the text, a reading time and any voice clip. It never answers a choice.
- **Skip**: runs through read lines and stops at the first new line or choice. Rewritten lines count
  as new.
- **Text speed**: Instant, Fast, Normal (the default) or Slow. The first press finishes the line.
- **Hide**: hides the interface. Any press brings it back without advancing the story.
- **Quick save and load**: a second slot in the same format as the regular save.
- **Speaker focus**: dims the characters who are not speaking, and can be turned off.

Save, Load, Restart, Gallery, License and the settings moved into **Menu**. The stage keeps five
buttons, which fit a phone. Keys: L, A, S, H and Esc, plus F5 and F9 on desktop. Scrolling up opens
the log and a right click hides the interface.

Story format, save format, route traces and the Python reference player are unchanged, so existing
stories and saves keep working. Voice volume settings from older players are kept.

## The launcher now handles a new runtime

A runtime change used to stop `tools/narrative/studio.py` until someone rebuilt the playtest by hand,
and it left releases failing until the builder was rebuilt and its pins were edited. The launcher now
rebuilds both from the verified toolchain in `notes/toolchains/godot-4.7.2`, stores them in
`notes/studio-builds`, and uses them for that run. It does not edit `studio.local.env`. A failed
builder build warns and leaves the Studio running, because only releases need it.

## Verification

Tests were written first. Real engine runs used Godot 4.7.2 from the verified toolchain.

- `uv run pytest -q`: **2176 passed, 129 skipped** (opt-in integrations).
- `tests/integration/test_narrative_player_controls_live.py`, with the engine: **3 passed**. It covers
  reveal, focus, the backlog and its limit, auto, skip, hide, quick save, the menu, stored settings,
  old and malformed settings files, and that a playtest writes no files.
- The other real-engine suites (`godot_live`, `preview_live`, `event_cgs_live`, `line_voices_live`,
  `player_terms_live`) with the engine: **46 passed**.
- `test_narrative_event_cgs_live.py -k linux_release` with a builder image built for this runtime:
  **1 passed**. It runs the real fenced Docker and Godot build and checks the exported package.
- `tests/unit/test_narrative_studio_launcher.py`: **18 passed**.
- `npm --prefix frontend test`: 185 passed. `uv run ruff check .` and `uv run mypy`: passed.

Real browser check in Edge on an isolated stack, whose launcher rebuilt the playtest by itself: the
log, Auto and its lit button, Hide, the menu at 1400 px, Escape closing the menu before the playtest,
and the toolbar at 390 px. Playtest Save and Load are disabled, as before.

A native test first showed the muted-browser flow needed the instant speed, because it presses once
per line. Probes that press once per line now set it. Two console messages were checked: the empty
hash update came from the validator hashing empty notices and is now guarded, and the blocked blob
image is Godot's page icon, which the playtest's policy blocks on purpose.

## Limits

- The backlog is not stored in saves, so it starts empty after reopening a game.
- There is one regular slot and one quick slot, not a save list.
- Quick save has no key in browsers, because they keep F5. Web players use the menu.
- Speaker focus is a player setting, not a creator setting.
- Not done yet from #164: theme images, the title screen and keyboard-only testing with a screen
  reader. Not done yet from #160: enter and exit animation, flip and side portraits.
- Format 1 stories keep their simple view.
