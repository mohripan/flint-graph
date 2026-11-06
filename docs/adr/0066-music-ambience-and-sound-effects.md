# ADR 0066: Music, ambience and sound effects

Status: accepted (2026-11-07)

## Context

Games had voices and no other sound, while music and ambience carry much of a visual novel's mood.
#163 asks for typed audio operations, saves that restore what was playing, per-channel volume, and
playback that respects browser autoplay rules.

## Decision

1. **Two audio file kinds.** Music and ambience are Ogg Vorbis, up to 10 minutes and 10 MiB, because
   an uncompressed loop of a few minutes would not fit. Sound effects stay canonical WAV of up to 60
   seconds, like voice clips. The story asset kind for Ogg files is `music`.
2. **Ogg files are kept byte for byte.** The server checks the container and identification header
   without decoding: one whole Vorbis stream, mono or stereo, a common sample rate and a duration
   within the limit. Page checksums are left to the decoder, because a SHA-256 already guards the
   bytes in a package. Other codecs in an Ogg file are refused with a message saying what to upload.
3. **Three optional fields on a format 2 stage step.** `music` and `ambience` name a track, or null to
   stop it, and keep playing across screens until changed. `sound` names a clip that plays once on
   arrival.
4. **What is playing is state, and a sound effect is not.** `music` and `ambience` live in `stage`,
   so saves restore them and route traces carry them. Both are left out while silent, so a story
   without sound saves exactly the bytes it always did, and older saves load as silence. `sound` is
   reported by the view for that arrival only, like an effect (ADR 0065).
5. **Tracks crossfade over 1 second.** Each channel has two players for this. Skip, Load and Restart
   switch instantly, and lines passed while skipping play no effects.
6. **Players control each channel.** There are volume sliders for voice, music, ambience and sound
   effects, plus Mute all (the M key). They are stored on the device and last only for the session in
   a playtest. Settings files from older players keep working.
7. **The start screen covers all sound.** Where a browser will not start sound by itself, the first
   click or key opens the story and starts its sound, for music as well as voices.
8. **The library has Music and Sound effects sections** with durations and a Listen button. The stage
   panel has Music, Ambience and Sound effect controls, and shows what earlier scenes left playing.
9. **The assistant uses files from the library** (prompt v8), and says so when a file it would need
   is not there. Generating music is separate work.

## Consequences

Runtime 0.10.0 and migration 0050, which only widens the library's constraints. Downgrading fails while
music or sound files exist, because removing a creator's files is the owner's decision.

A runtime change has a cost that a new asset kind makes visible: playtest and release code each have
their own list of file kinds and limits. Runtime files and kinds are listed in `pyproject.toml`,
`export/__init__.py`, `build_child.py`, `build_preview.py`, `previewProtocol.ts`, `bridge.js`,
`bootstrap.gd` and `export_presets.cfg`. A real playtest and a real release are what prove them all,
and both are part of this delivery's verification.

Loop points inside a track and captions for sound effects (#163) are not done. A track always loops
from its end back to its start.
