# Generation cards

The user asked, before showing the Studio to anyone: when the chat leads to GPU work, do not start
it; show a card with what it will make and what it costs, with Cancel and Generate. See
[ADR 0068](../adr/0068-generation-waits-for-the-creators-press.md).

## What changed

- **Generate automatically is gone.** It was on by default, so the assistant could spend credits and
  GPU time with no press at all. Now nothing starts until Generate. The API ignores the old field.
- **The card** shows what will be made, the model, how many, the shape and the price, with Cancel,
  Generate and a link to the page with more controls. The server writes it.
- **The price is the charge.** The Studio no longer repeats the server's rules to guess a price.
- **Cancel** spends nothing, tells the model, and can be undone with Show again.
- **Worker charges** now use the deployment's prices and respect open mode. Before, a press that
  waited for a full queue could cost something other than what the page showed.
- **Prompt v9.** The model says nothing has started and that Generate starts it.

Credits and chat: both already existed (ADR 0059). Every job and every chat message is charged at
admission; this delivery adds tests that hold each to what the Studio shows.

## Verification

The real model and the real image worker ran on an isolated stack, in invite mode with a real key:
its own database, bucket and queues, on ports 8321/5321/5322. The user's Studio was left alone.

- Sending "Generate a background of a rainy harbor street at night." cost 2 credits and showed a card
  reading "a rainy harbor street at night | Animagine XL 4.0 | 4 options | Widescreen | 8 credits, you
  have 198".
- No job existed after 6 s with the worker running, and the balance did not move.
- Cancel left the balance alone. Show again brought the card back.
- Generate cost exactly 8 credits. The job completed with 4 candidates.
- A new character's sprite (20 credits) had Generate disabled until its proposal was accepted.
- At a balance of 3 the card read "you have 3" and "You don't have enough credits for this."
- At phone width there was no sideways scrolling. "Open Characters" went to Characters.
- Browser console problems: none.

Real model replies (12 turns on the local model, 4 each for a background, a sprite and a voice):
all 12 proposed the right action and told the creator to press Generate. A strict wording check
passed 8 of 12: the others also said "I'll create…" or "I'll choose…" before that sentence. That
is loose wording, not a false claim, so it was left. On v8 the same requests usually ended at "I'll
get started on that" or "ready for review shortly".

Commands:

- `uv run pytest`: 2258 passed, 137 skipped.
- `tests/integration/test_narrative_assistant_actions.py`, `test_narrative_assistant_children.py` and
  `test_narrative_generation_cards.py` also pass on disposable PostgreSQL, which runs migration 0051.
- `uv run ruff check .`, `uv run mypy`, `uv run flint-graph-prompts check --base-ref HEAD`: clean.
- The offline eval gate, `uv run alembic upgrade head --sql` and `docker compose config`: pass.
- `npm --prefix frontend test`: 189 passed. `npm --prefix frontend run build`: clean.
- The general assistant bench on prompt v9: 10 of 10 right, median 3 s.

## Limits

- Failed or cancelled jobs are still not refunded (ADR 0059).
- Operators are not recognised in the worker, because it has no sign-in token; they have no grant to
  charge, so this only matters to someone who joined with a key before being made an operator.
