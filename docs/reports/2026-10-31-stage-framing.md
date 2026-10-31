# Stage framing: character size and free placement (runtime 0.4.0)

The user asked (2026-10-31) for characters drawn larger and placed freely, as visual
novels usually show them. Full-body sprites stay the generated source; the game shows
them from roughly the thighs up, with the bottom edge of the screen cutting them off.
Before this, the stage fitted every whole figure into a third of the screen, so
characters looked small and far away.

## Delivered

- **Format (story format 2, additive).**
  - A character may have `stage: {scale, top}`. `scale` is the drawn height as % of
    the screen (40–300). `top` is the top edge as % of the screen height (−50–100;
    the default is `max(0, 100 − scale)`, so tall figures start at the top and
    shorter ones stand on the bottom).
  - A `show` entry may carry `x` (0–100), its horizontal centre. Slots (left, center,
    right) still decide who replaces whom.
  - `x` belongs to that placement: it is part of the stage state, views, frames and
    saves, survives expressions, and is dropped when the character is placed again
    without it.
  - Stories, saves and releases without these fields behave exactly as before.
- **Runtimes.** The Python validator and player, the Godot player, the stage view and
  the playtest validator implement the rules. Godot draws framed figures from the top
  edge, keeping the aspect, and clips them at the stage. Runtime 0.4.0 replaces 0.3.0
  in the toolchain, release identity and build child, with a rebuilt builder image.
- **Studio.**
  - Characters → On stage has a **Size on stage** control (height and top edge) with
    a live preview on the story's first background.
  - Each placement in a scene's stage panel has a **Place** slider and a reset to the
    slot default.
  - The Look preview draws the sprite with the same framing math (`figureBox`, which
    mirrors the stage view).

## Verification

- **Unit tests.** `test_narrative_stage_framing.py` covers bounds and stable codes,
  `x` through expressions, re-placement and saves, rejection of bad saved values,
  older saves staying valid, and format 1 refusing framing. The frontend model has a
  `figureBox` and framing test (81 frontend tests).
- **Real Godot 4.7.2.**
  - A framed route matches the reference frames and saves.
  - The layout probe measured a 160% figure from 4% down at x 30: 1152 px tall, half
    as wide, centred at 384 of 1280.
  - The playtest validator agrees with Python on the new cases.
- **Live, owned stack** ([evidence](evidence/stage-framing-2026-10-31/qualification.json)).
  The user's revision 8 was copied into a separate "Framing QA" project. Headless
  Edge then set Quen to 165%/3% and Mira to 150%/6% in the character sheet, and moved
  Mira to 72%.
  - **Save and playtest.** The edits saved as revision 3. The Godot playtest measured
    Quen 1203 px tall from 22 px down and Mira 1094 px tall from 44 px down, centred
    at 72%.
  - **Release.** A real release build on runtime 0.4.0 completed.
