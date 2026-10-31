# ADR 0043: Asset folders and voiced dialogue lines

Date: 2026-10-31. Status: accepted and delivered (tracking #163 groundwork, #128, #161).
Design: [spec](../superpowers/specs/2026-10-31-asset-folders-and-line-voices-design.md).
Delivery: [report](../reports/2026-10-31-asset-folders-and-line-voices.md),
[runbook](../runbooks/narrative-voice-generation.md).

## Context

Generated portraits, sprites, expressions, backgrounds and CGs pile up in one flat
asset grid. Creators also want voiced dialogue: visual novels are usually only partly
voiced, with some lines spoken in full, some marked only by a short sound such as
"fufu" or "hmm", and many silent. Kokoro-82M (Apache-2.0, pinned and verified under
`notes/models/`) is small enough to run on the CPU without competing with the image
model or the assistant for the 12 GB GPU.

## Decision

1. **Folders are editor organization only.** A project has a tree of named folders
   (three levels at most); each asset sits in at most one. Moving or renaming never
   touches asset bytes, hashes, story packages, revisions or releases. Deleting a
   folder moves its contents to the parent. Unsorted generated items are still easy
   to find through automatic groups derived from existing columns (by kind, by
   character, to review), which need no manual filing.
2. **Story format 2 gains `audio` assets and a line `voice`.** Audio assets are
   canonical 16-bit PCM WAV files (`assets/<id>.wav`; mono or stereo; 16–48 kHz; at
   most 60 s and 10 MiB). A line may carry
   `voice: {"mode": "full" | "vocalization", "text"?: "fufu", "audio"?: <audio id>}`.
   Absence means silent, the default. A voice needs a speaker; `text` is required
   for a vocalization and refused for full voice. A voice without `audio` is an
   intent that plays nothing until a clip is chosen. Views and frames carry
   `voice`: the clip of the settled line, else `null`. Saves are unchanged.
3. **Generation copies ADR 0039.** A CPU-only child in `runtimes/voicegen` (its own
   uv lock, Kokoro and Misaki with a bundled spaCy model and eSpeak NG fallback, no
   network) is started with `python -I`, a minimal environment and a watchdog by the
   opt-in `narrative_voice_worker`. That worker owns its outbox topics, a fenced
   Temporal workflow on its own task queue, and create-only, hash-verified storage.
   Each character profile stores a Kokoro voice ID. A job speaks up to 24 texts in
   one voice; every clip becomes a candidate `voice` asset with provenance (model,
   voice, text, mode, seed). Only approval makes a clip bindable.
4. **Uploads.** Voice clips may also be uploaded with the existing rights declaration.
   Uploads are normalized to the canonical WAV form before hashing.
5. **Playback in four implementations.** The Python reference, the Godot player
   (runtime 0.6.0), the preview validator and the editor model agree on the rules
   through shared conformance fixtures. Godot plays a line's clip when the line
   settles and stops it on the next screen, and the menu has a voice volume setting
   stored locally (memory-only in Studio playtests). Builds ship WAV assets with the
   same exact-bytes `keep` remap as images and fonts.

## Consequences

- WAV is uncompressed: about 48 KB per second of mono 24 kHz speech. The existing
  48 MiB asset budget fits a partly voiced story; fully voiced long stories need a
  compressed format later (Ogg Vorbis with #163).
- Kokoro speaks English voices only in this slice (`a`/`b` voices). Other languages
  need extra Misaki dependencies.
- Releases built on runtime 0.5.0 keep their pinned identity; rebuilding them needs
  the new builder image.
- The assistant may read voice fields but cannot set them yet; voice actions follow.
