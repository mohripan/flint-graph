# A title screen

A game can now open on a title screen with art and music, set in Look or by asking the assistant. See
[ADR 0071](../adr/0071-title-screen.md). This delivers part of #164.

## Verification

A real run from chat to release used the real assistant model and image worker, a real browser, real
Temporal, MinIO and PostgreSQL, and a real builder, in invite mode on an isolated stack:

- Asking for a lighthouse background showed a card. Generate made real candidates, and one was approved.
- Asked to use it as the title screen art with the Harbor theme as its music, the assistant proposed
  `set_title_screen`. After Accept the theme held exactly `{"title": {"background": ..., "music": ...}}`, and
  both files were in the story.
- Look → Title screen previewed it.
- A real playtest opened on the art and title with Start and Settings. Enter started the story.
- A real release built with no errors on runtime 0.11.0: job `completed`, with its artifacts published.
- Browser console problems: none.

The first version of this put the title in `set_theme`. The real model then invented a whole colour scheme,
which only showed up in a real run, and is why it now has its own operation.

Real engine, game and playtest (`test_narrative_title_screen_live.py`): it opens on the title with the art and
title music, shows Continue only with a save, leaves the story unstarted until Start, ignores shortcuts, offers
only settings from the title, hands over to the story's music, goes back and continues from the same place, and
starts over from Start. A playtest writes no files. Blocked browser sound starts the music on the first press.

Real model bench (`set_title_screen`), 20 turns on the local model, 19 right before the fix below:

- Art: 4/4. Art and music: 4/4. Removing the music and keeping the art: 4/4.
- An unrelated scene touched no theme: 4/4.
- Moving the text box: 3/4. The miss wrote null for every other field, which is now tidied away in code, with a
  test. The live bench was not rerun for that last fix.

Commands:

- `uv run pytest`: 2381 passed, 144 skipped.
- With the real engine, `tests/integration/test_narrative_godot_live.py`, `test_narrative_player_controls_live.py`,
  `test_narrative_sound_live.py` and `test_narrative_title_screen_live.py`: 34 passed, 1 skipped.
- `uv run ruff check .`, `uv run mypy`, `uv run flint-graph-prompts check`, the offline eval gate,
  `uv run alembic upgrade head --sql` and `docker compose config`: pass.
- `npm --prefix frontend test`: 200 passed. `npm --prefix frontend run build`: clean.

## Limits

- Nobody has judged the look on a phone-sized real device; the layout scales and was checked in the desktop
  playtest only.
- Themed text box images, menu backgrounds and the rest of #164 remain open.
