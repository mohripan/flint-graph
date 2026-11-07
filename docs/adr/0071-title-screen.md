# ADR 0071: A title screen

- Status: accepted
- Date: 2026-11-07
- Issue: #164 (part)

## Context

A game opened straight on its first line. The title screen is the first thing anyone sees, and #164 asks
for one with title art and start, load, settings, gallery and quit. Saves, route traces and the reference
player have strict parity rules, so this should not touch story state.

## Decision

**It is part of the look.** `theme.title` is optional, with `background` (an image) and `music` (a music
file). With either set, the game opens on the title screen; with neither it goes straight to the story,
so every existing story, save and probe behaves as it did. The title itself is the story's title, drawn
as plain text in the story's font.

**It lives in the view.** `vn_view.gd` draws it, and the player, saves and route traces do not know it
exists. The story does not start until Start is pressed, so no line, clip or read mark happens early.

| Button | Does | Shown |
| --- | --- | --- |
| Start | A new game | Always |
| Continue | Loads the saved game | When there is one |
| Gallery | The gallery | When something is unlocked |
| Settings | The menu, with story actions disabled | Always |
| Quit | Leaves the game | On desktop |

The Menu gets **Title screen** to go back. The story waits underneath, and Start from there starts over.

**Sound.** Title music plays until the story's own takes over with the usual crossfade. Browsers that
block sound show the existing start screen first, and its press starts the title music.

**Playtests** show it too, because a creator setting one wants to see it. They offer no Continue, and read
and write no saves, as before.

**In the Studio.** Look → Title screen has art and music pickers, and the preview has a Title screen tab.

**For the assistant.** `set_title_screen` is its own operation (prompt v11). The first attempt put the title
in `set_theme`, and the live model, handed the whole theme, invented every colour: asked for title art, it
turned the text box black. An exact shape cannot touch anything else. What it leaves out stays, and null
removes it. `set_theme` no longer drops a title it did not mention. A file still being generated is left
out, keeping the rest of the choice, as on a stage step.

Runtime 0.11.0, because the player changed. No migration, since the theme is part of the story.

## Alternatives

- **A title screen for every game.** Friendlier at first sight, but it would change every existing game and
  every native probe that expects the first line. A creator can add one in one sentence.
- **Screens as story nodes.** Far more flexible, but a title belongs to no route, and it would put a menu
  into the story format, saves and all four implementations.

## Consequences

- #164's themed text box images, menu backgrounds and a live theme editor beyond Look remain open.
- A new game from the title loses progress that was not saved, as Restart does. The save slot is untouched.
