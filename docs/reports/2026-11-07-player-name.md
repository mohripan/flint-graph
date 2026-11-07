# Naming the player

Players can type a name, and characters and narration then use it. See
[ADR 0072](../adr/0072-naming-the-player.md). This delivers the naming half of #165.

## Verification

Real run, from chat to release, with the real assistant model, a real browser, real Temporal, MinIO and
PostgreSQL and a real builder, in invite mode on an isolated stack:

- Asked to let the player choose a name and be welcomed by it, the assistant proposed the question and a
  default. After Accept the story opens on `What is your name?`.
- Write lists it with its own form: the question, the default, and who takes the name.
- A real playtest asked, with the field focused and showing the default. Typing and Enter led to "Welcome, Zoë.
  The harbor has been waiting for you."
- A real release built on runtime 0.12.0: job `completed`.
- Browser console problems: none.

Real key events in a web build delivered `ë`. They also showed Japanese and emoji arriving as empty boxes in
the built-in font, which led to the font check in the ADR. Playwright's own `keyboard.type` silently loses those
characters by inserting text without key events, so a first run looked like a bug it was not.

Real engine (`test_narrative_player_name_live.py`):

- Frames, state and saves match the Python reference exactly, with a name holding markup, `{name}`, an emoji and
  Japanese, and a native save loads in the reference.
- The same table of typed names is cleaned identically by both.
- The player asks, focuses the field, shows the name as plain text, gives it to the right character only, stops
  Auto at the question, and an empty answer takes the default. Letters typed are not shortcuts.
- A playtest asks too, and writes no files.
- A web-style font refuses what it could only draw as boxes.

Real model bench (`set_player`, `name` node, `{name}`), 20 turns on the local model: 18 right.

- Asked to let the player choose: 3/4. Naming a given character with a given default: 3/4.
- Greeting by a name already set up: 4/4.
- An unrelated line and an unrelated scene brought no naming at all: 8/8.
- The first version scored 15/20. The model often wrote only part of it, so the code now finishes the job.

Commands:

- `uv run pytest`: 2424 passed, 149 skipped.
- With the real engine, `tests/integration/test_narrative_player_name_live.py`, `test_narrative_title_screen_live.py`,
  `test_narrative_godot_live.py`, `test_narrative_player_controls_live.py` and `test_narrative_sound_live.py`: 39 passed,
  1 skipped.
- `uv run ruff check .`, `uv run mypy`, `uv run flint-graph-prompts check`, the offline eval gate,
  `uv run alembic upgrade head --sql` and `docker compose config`: pass.
- `npm --prefix frontend test`: 202 passed. `npm --prefix frontend run build`: clean.

## Limits

- Appearance choices from #165 are not done.
- Only the keyboard path was exercised. Phone virtual keyboards and input-method composition in a web build have
  not been tried on real devices.
- Web games on the built-in font take Latin-script names only.
