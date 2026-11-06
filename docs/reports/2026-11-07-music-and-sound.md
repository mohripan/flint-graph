# Music, ambience and sound effects (#163; runtime 0.10.0, prompt v8, migration 0050)

Delivered [ADR 0066](../adr/0066-music-ambience-and-sound-effects.md). A format 2 stage step can start
or stop music and ambience and play a sound effect. Tracks crossfade, keep playing across scenes and
come back from a save. Players get a volume slider per channel and Mute all. The library has Music and
Sound effects sections, and the stage panel has a control for each. The assistant uses files from the
library. Generating music is not part of this delivery.

A story without sound saves exactly the bytes it did before, and older saves load as silence.

## The assistant

Real runs of the local model with thinking off, using a library of two music files and one sound:

| Request | First version | After the fixes below |
| --- | --- | --- |
| Start the theme from the beginning | 3 of 3 | 4 of 4 |
| Rain loop as ambience in a new scene | 0 of 3, then 0 of 4 | **4 of 4** |
| Play a sound effect, then a line | 3 of 3 | 4 of 4 |
| Start the theme and stop it before the end | 2 of 3 | 2 of 4 |
| Asked for music that is not in the library | 1 of 3, then 2 of 4 | **4 of 4** |
| An ordinary scene: must use none of these | 3 of 3 | 4 of 4 |

The two fixes:

- **Writing order.** The reply said "rain loop as ambience" while the proposal wrote `music`. A grammar
  writes fields in schema order, and `ambience` sorted before `background`, so a model that had written
  the background could only reach `music`. A stage step now lists what is seen before what is heard.
- **Missing files.** The model invented IDs such as `piano_track`. Repair messages now list the files
  of that kind and say to leave the field out and suggest uploading one. An empty `show` list is
  removed instead of costing a repair, and a repair for a step that changes nothing says what to do.

The remaining weak case, stopping the music at a later point, leaves the music playing to the end. The
creator sees that in the proposal, and nothing is lost.

Because field order touches every stage step, earlier cases ran again: the general set scored **20 of
20**, and transitions scored **30 of 30**. These are small samples from a stochastic model, so they
show direction and not precise rates.

## What a real run found

A browser playtest with music would not open, while every automated test passed. The playtest has two
of its own lists of file kinds and limits (`previewProtocol.ts`, `bridge.js`), and neither knew music.
A test now covers one and both are fixed.

The listing route and the upload route each had their own list of kinds as well, which the new API
tests found. The first real release build then failed with `input_integrity`, because the build's input
check had its own list of file types too. That is fixed, and the release test now checks the file inside
the exported game.

## Verification

Tests were written first. Real engine runs used Godot 4.7.2 from the verified toolchain.

- `uv run pytest -q`: **2249 passed, 137 skipped** (opt-in integrations).
- `tests/unit/test_narrative_sound.py`: the Ogg check against real files and damaged ones, the format,
  saves, older saves and the library's rules.
- `tests/integration/test_narrative_sound_live.py`, with the engine: real Vorbis decoding, parity with
  the reference player, crossfade, one-shot effects, stopping, saves, Restart, Skip, volumes, mute,
  the start screen and a playtest writing no files.
- `test_actual_linux_release_build_carries_music`, with a builder image for this runtime: the real
  fenced Docker and Godot build, with the music file checked inside the exported game's pack.
- `tests/integration/test_narrative_asset_library_api.py` and `test_narrative_package_v2_api.py`, on
  SQLite and on real PostgreSQL: uploads, refusals, served bytes, binding into a revision, notices and
  playtest serving.
- All real-engine suites together: **53 passed, 2 skipped**. The skips are the Linux release tests,
  which need the builder pins and were run separately.
- `npm --prefix frontend test`: 187 passed. Typecheck and production build passed.
- `uv run ruff check .`, `uv run mypy`, `uv run flint-graph-prompts check --base-ref HEAD`, the offline
  migration SQL, `docker compose config` and the deterministic evaluation: passed.

Real browser check in Edge on an isolated stack with migrations applied by its launcher: uploaded two
real Ogg files, chose music in the stage panel, saved, saw the file credited in the notices, played it
with Listen, and opened a playtest. The player's own state reported the track playing in the web build.
Headless Edge allows sound by itself, so the browser run did not show the start screen; the native test
covers that path. Nobody listened to the output, so audio quality and crossfade smoothness are unverified.

## Limits

- Uploaded music must be Ogg Vorbis. MP3 and other formats are refused, with a message saying what to
  upload, and there is no conversion yet.
- A track loops from its end to its start, with no loop points.
- No captions or visual cues for sound effects yet (#163).
- The stage panel edits the step that opens a scene. Mid-scene steps change through the assistant or
  Source.
- The launcher notices a runtime change by its version, so changing player files without a version bump
  leaves an old playtest build in place.
