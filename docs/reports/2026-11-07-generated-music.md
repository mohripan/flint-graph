# Generated music

Creators and the assistant can now make instrumental tracks that loop, from a description, with
ACE-Step 3.5B on the GPU. See [ADR 0067](../adr/0067-generated-music.md) and the
[runbook](../runbooks/narrative-music-generation.md).

## Verification

A real run used the real assistant model, the real ACE-Step worker, real Temporal, MinIO and
PostgreSQL and a real browser, in invite mode with a real key, on an isolated stack (ports
8321/5321/5322). The user's Studio was left alone.

- Asking for "a gentle piano music track, about 30 seconds long" showed a card: "gentle piano, soft,
  peaceful, slow | ACE-Step 3.5B | 30 seconds | Instrumental, loops | 10 credits". No job existed yet.
- Generate cost 10 credits and the job finished in 73 s: Ogg Vorbis, 27.9 s, 437 KB.
- The track appeared in the chat. Listen really played it in the browser, for 27.9 s.
- Approve worked. Assets → Music showed the generator and the track.
- Cancel from the Music panel stopped a running job, and it kept no track.
- Asked to play it from the start, the assistant wrote a stage step with that file. Accepted, it saved,
  with ACE-Step credited in the notices. A real playtest loaded it and played to the end with no errors.

The real run found three problems no fake could:

- The usage tables and a database check did not know the `music` kind. A real key got a 500.
- Torch 2.11 fails to import without a username, which the child's minimal environment did not have.
- With music off, the model reached for a voice clip instead. It is now told plainly.

**Nobody has listened to this music.** The earlier analysis found it non-silent and tonal. Whether it
sounds good, loops cleanly or suits a story is unverified, and needs a person.

Real model bench (`generate_music`), 24 turns on the local model: 23 right.

- Asked for music: 4/4. Asked with a length: 4/4. A library track preferred when named: 4/4.
- Unrelated scene: no music action, 4/4. A sound effect: no music action, 4/4.
- Music turned off: 3/4. The miss proposed a voice clip, which failed validation and took 179 s.

Commands:

- `uv run pytest`: 2327 passed, 140 skipped.
- `tests/integration/test_narrative_music_api.py` also passes on disposable PostgreSQL, which runs
  migration 0053.
- `uv run ruff check .`, `uv run mypy`, `uv run flint-graph-prompts check --base-ref HEAD`, the offline
  eval gate, `uv run alembic upgrade head --sql` and `docker compose config`: pass.
- `npm --prefix frontend test`: 199 passed. `npm --prefix frontend run build`: clean.

## Limits

- No per-track waveform or preview beyond Listen.
- The same best-effort release of the assistant's model as images and voices; #191 owns doing better.
- Not run in a release build with a generated file. It is an ordinary `music` asset, and ADR 0066's
  real release used fixtures of the same kind.
