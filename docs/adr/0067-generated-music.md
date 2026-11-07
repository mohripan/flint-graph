# ADR 0067: Generated music

- Status: accepted
- Date: 2026-11-07
- Issue: #170
- Extends: [ADR 0066](0066-music-ambience-and-sound-effects.md), [ADR 0068](0068-generation-waits-for-the-creators-press.md)

## Context

ADR 0066 let a story play Ogg Vorbis music, but a creator had to bring their own. ACE-Step 3.5B
(Apache-2.0) is already verified under `notes/models/`. A visual novel usually needs a handful of
tracks that loop, so generated music is worth having if it is reviewed like any other generated file.

## Decision

Music follows the same fenced pipeline as images and voices: outbox, relay, Temporal workflow with IDs
only, a claimed activity, an isolated child, a distrusting parent, a candidate, and approval.

- **`runtimes/musicgen`** has its own locked environment with pinned `ace-step`, torch and soundfile.
  The child receives `description, seconds, seed, steps` and writes one `0.ogg`. Its environment
  is minimal, with no credentials.
- **It loops.** The child crossfades the end of a track into its start with equal power and trims
  the overlap, so a track is about 2 s shorter than asked. The parent allows 4 s.
- **The parent trusts nothing:** one file, within `MUSIC_LIMIT`, valid Ogg Vorbis, about the requested
  length. Anything else fails the job and publishes nothing.
- **Limits.** 15 to 180 seconds, 10 credits a track, with a new `music` usage kind (10 a day, 60 in
  total by default). It needs about 7 GiB of free GPU memory and refuses with `gpu_busy` below that.
  `NARRATIVE_MUSIC_RELEASE_OLLAMA_MODEL` frees the assistant's model first on a shared card.
- **In the Studio.** Assets → Music has a generator with a length choice and Cancel. Music stays listed
  while empty, since that view is where it is made.
- **For the assistant.** `generate_music` is one more action with a card (prompt v10). It is removed from
  the grammar where the server cannot make music, and the model is told to suggest an upload. It
  describes mood, instruments and pace. It cannot sing or make short sound effects, which are uploads.
- **Credit.** Notices credit ACE-Step with the track, and each track stores its model and seed.

A track is a normal `music` asset once approved, so nothing changes in the game runtime, the story
format or saves. A made-up file ID in a stage is dropped while its track is being generated, and a
step that only existed to play it is left out, because the file has no ID until it is approved.

## Alternatives

- **Generate on the API or assistant worker.** Heavy dependencies would leak into processes that must
  stay small. Every other engine is an isolated child, for the same reason.
- **Keep a lock on the Ollama model while generating.** That is #191's job. Until then this uses the
  same best-effort release as images and voices.
- **Sound effects from the same model.** It makes music. A door slam from it would not be a door slam.

## Consequences

- Nobody has listened to the output yet. It was analysed as non-silent and tonal, and that is all.
- `music` is a kind with a database check, so a new generation kind must update `usage_charges`,
  `KINDS`, `_NOUNS` and `usageModel.ts`, or a real key gets a 500. Tests in open mode do not see this;
  `test_every_card_costs_exactly_what_it_says` does.
- Torch 2.11 fails to import without a username, so the child gets a fixed `USERNAME`, not the real one.
