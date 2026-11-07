# Saying when the GPU is asleep

The user asked that whenever someone generates, in chat or anywhere else, a sleeping GPU is explained
rather than looking broken. See [ADR 0069](../adr/0069-saying-when-the-gpu-is-asleep.md). This delivers
the Studio side of #201, and the state store #197's controller will write to.

## Verification

An isolated stack ran in invite mode with no GPU workers at all, and a small script wrote what a
controller would. A real browser showed:

- Controller never seen: "The GPU won't wake up", on the card.
- `stopped`: "The GPU is taking a nap. We switch it off when nobody is using it, to save money, so the
  first request waits about 3 minutes while it wakes up", on the card, with the time from the setting.
- Sending a chat message while asleep cost its 2 credits, and the same message sat under the waiting
  reply, beside Stop.
- `starting`, `no_capacity` and `daily_cap` each showed their own words.
- Assets and Characters showed it at the top. Write showed nothing.
- Phone width: no sideways scrolling. Browser console problems: none.

Not exercised: a real controller or a real sleeping machine, because neither exists yet (#197, #198).
The messages were driven by writing the controller's row.

Commands:

- `uv run pytest`: 2278 passed, 137 skipped.
- `tests/integration/test_narrative_gpu_status_api.py` also passes on disposable PostgreSQL, which runs
  migration 0052.
- `uv run ruff check .`, `uv run mypy`, the offline eval gate, `uv run alembic upgrade head --sql` and
  `docker compose config`: pass.
- `npm --prefix frontend test`: 196 passed. `npm --prefix frontend run build`: clean.

## Limits

- No per-job queue position or estimate (#192).
- A wake-up time is only as good as the number configured. Nobody has measured a real cold start yet.
