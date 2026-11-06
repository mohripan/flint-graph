# Stage transitions and effects (#162; runtime 0.9.0, prompt v7)

Delivered [ADR 0065](../adr/0065-stage-transitions-and-effects.md). A format 2 stage step can have a
`transition` (cut, fade, dissolve or slide) and an `effect` (shake or flash). A change with no
transition plays a 0.2 second dissolve, so existing stories stop popping without any edit. Players
can turn all motion off with **Reduce motion** in the menu, and a browser's reduced-motion preference
sets the default. The Studio's stage panel has both controls, and the assistant can use both.

Neither field is in saves or route traces. The view keeps the old screen above the new one until it
has gone, so the stage underneath is always the settled one.

## The assistant

Prompt v7 adds both fields to the exact stage shape and tells the model to leave `transition` out for
an ordinary change. Real runs of the local model, with thinking off:

| Request | Right | Median |
| --- | --- | --- |
| Fade to a new background | 3 of 3 | 5 s |
| Dissolve to a new background | 2 of 3 | 6 s |
| Lightning flash with no new background | 3 of 3 | 4 s |
| An explosion shakes the screen | 3 of 3 | 6 s |
| An ordinary scene: must use neither field | 3 of 3 | 5 s |

The miss was an `unknown_reference` that the repair loop did not recover from.

The regression run found a weakness that also exists in v6: asked to add a voiced line, the model
often wrote `"voice": {"mode": "full"}` and forgot `generate_voice`, which leaves the line silent. It
scored 3 of 6 on v7 and 5 of 6 on v6. A new line marked for voice now gets the action if the model
left it out, using the character's voice or a default. After that change:

- Voiced line, 8 repeats: **8 of 8**.
- Scene and narration cases, 24 repeats: 23 of 24. The miss wrote only an expression action.
- Scenes nobody asked to voice, 15 runs: **no voice action appeared**, so this adds no surprise cost.

These are small samples from a stochastic model, so they show direction and not precise rates.

## Verification

Tests were written first. Real engine runs used Godot 4.7.2 from the verified toolchain.

- `uv run pytest -q`: **2203 passed, 132 skipped** (opt-in integrations).
- `tests/unit/test_narrative_transitions.py`: 21 passed. It covers the closed sets, format 1, the view,
  and that saves and route traces are unchanged.
- `tests/integration/test_narrative_transitions_live.py`, with the engine: **3 passed**. It compares
  reported values with the reference player, compares settled screens with motion on and off, and
  covers a press, Auto, a save during a transition, shake, a single flash, reduced motion, Skip,
  Restart and Load.
- All real-engine suites together: **49 passed, 1 skipped**. The skip is the Linux release test,
  which needs the builder pins and was run separately.
- `test_narrative_event_cgs_live.py -k linux_release` with a builder image for this runtime:
  **1 passed**.
- `tests/integration/test_narrative_preview_live.py`: the preview validator agrees with the server on
  the closed sets.
- `npm --prefix frontend test`: 186 passed. Typecheck and production build passed.
- `uv run ruff check .`, `uv run mypy`, `uv run flint-graph-prompts check --base-ref HEAD`, the offline
  migration SQL, `docker compose config` and the deterministic evaluation: passed.

Real browser check in Edge on an isolated stack, whose launcher rebuilt the playtest for this runtime:
a slide with the old screen moving away over the new one and the text hidden until it lands, the
screen after a fade, and the Transition and Effect controls in the stage panel. Screenshots lag the
timing, so the browser run does not prove the dark middle of a fade; the native test covers it.

A failing test first showed a bug from runtime 0.4.0: any character without a custom position logged
an engine error on every layout, because `get_meta` treats a null default as no default. It is fixed,
and the native probe now fails on that message.

## Limits

- The panel edits the stage step that opens a scene. A mid-scene step shows its transition in the
  script view and changes through the assistant or Source.
- Characters have no enter or exit motion of their own; they take part in the screen's transition.
- A press within 0.2 seconds of a stage change finishes the dissolve instead of advancing.
- Parity compares reported values and settled positions, not rendered pixels.
- Rate estimates above come from small samples.
