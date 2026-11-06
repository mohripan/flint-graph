# ADR 0064: Standard player controls live in the view

Status: accepted (2026-11-07)

## Context

The exported player had Continue, numbered choices, one save slot, a gallery and a voice slider.
People trying a visual novel expect more: reading earlier lines, leaving it to play by itself,
skipping what they have already read, and text that appears over time. #164 lists these, and #160
asks for the speaker to stand out when several characters are on stage.

Story state has strict parity rules across the Python reference player, Godot, saves and route
traces. A control that touched any of those would make every future change harder and could put
existing saves at risk.

## Decision

1. **Controls never touch story state.** They live in `vn_view.gd` and a small `reading.gd`, and
   only call the same `act` a Continue press does. The reference player, story format, save format
   and route traces are unchanged, so every existing story and save keeps working.
2. **The stage keeps a short toolbar**: Log, Auto, Skip, Hide and Menu. **Menu** holds Save, Load,
   Quick save, Quick load, Restart, Gallery and License, plus text speed, auto speed, voice volume
   and speaker focus. Five buttons fit a 390 px phone, and the old row did not.
3. **Text appears over time by default.** The speeds are Instant, Fast, Normal and Slow, with Normal
   as the default. The first press finishes a line and the next one moves on, wherever the press
   comes from.
4. **Auto waits for the line.** It waits out the text, a reading time based on its length, and any
   voice clip. It never answers a choice or leaves an ending.
5. **Skip stops at new text.** A read mark is the node ID plus a hash of the line, so a line the
   creator rewrote counts as unread. Skip stops at the first unread line or choice. Lines passed
   while skipping stay silent, and the line it stops on plays its voice.
6. **The backlog is this session's reading.** It keeps speaker names and the choices taken, shows
   story text as plain text, and holds the latest 300 entries. Loading a save marks the jump instead
   of clearing it. It is not stored in saves, so it starts empty after reopening the game.
7. **Quick save is a second slot in the same format.** The keys are F5 and F9 on desktop. Browsers
   keep F5 for themselves, so web players use the menu.
8. **Speaker focus dims the others.** It applies only when the speaker is on stage with someone
   else, so narration and off-screen speakers dim nobody. Players can turn it off. It is a player
   setting for now, not a creator setting.
9. **Settings and read marks stay on the device.** `settings.json` moves to schema 2 and still
   reads schema 1 files, so a player's voice volume survives the update. Read marks are written at
   most every 5 seconds. Playtests keep all of this in memory, and tell the page while an overlay
   is open so Escape closes the overlay before the playtest.
10. **The launcher rebuilds what a new runtime makes stale.** After a pull that changes the runtime,
    `tools/narrative/studio.py` builds a new playtest and release builder from the verified toolchain
    under `notes/toolchains/godot-4.7.2`, stores them in `notes/studio-builds`, and uses them for
    that run. `studio.local.env` is not rewritten. If a builder build fails, the Studio still starts
    and warns that releases will fail, because writing, generating and playtesting do not need it.
    Nothing is downloaded automatically.

## Consequences

Runtime 0.8.0. Exports from earlier runtimes keep working but do not gain these controls until they
are rebuilt. Format 1 stories keep their simple view without these controls.

Still open in #164: theme images, a title screen and the theme editor's preview of these controls.
Still open in #160: enter and exit animation, flip, side portraits and a creator setting for focus.
