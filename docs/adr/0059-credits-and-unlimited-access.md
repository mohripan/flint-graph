# ADR 0059: Credits, prices and unlimited access

Status: accepted (2026-11-06)

## Context

[ADR 0058](0058-invite-only-access-and-usage-limits.md) lets an operator hand out many
invitation keys and email invitations, revoke them, and give each person per-kind
limits. Every admission counts one unit, whatever the model:
- a Kokoro line costs the same as an IndexTTS-2.5 line;
- a background costs the same as a FLUX.2 pose.

The operator wants:
- to give each person a budget of **credits** that cheap work spends slowly and
  expensive work quickly;
- to top up, set or take away that budget after the person joined;
- an **unlimited** key for themselves.

## Decision

1. **Prices are a code table** (`flint_graph.application.credit_prices`), one entry per
   price item, each with a kind, a label and a unit.
   - `FLINT_GRAPH_ACCESS_CREDIT_PRICES` (JSON) may override individual items.
   - Unknown items, or prices outside 0–100,000, refuse to start the API.
   - Every voice model in the catalog must have an item; a test enforces this.

   | Item | Credits | Unit |
   | --- | ---: | --- |
   | `image.expression` (face repaint) | 1 | image |
   | `image.standard` (portrait, background, look) | 2 | image |
   | `image.sprite` (transparent cutout) | 3 | image |
   | `image.high_res` (2× hires, sprite or not) | 5 | image |
   | `image.cg` (event CG) | 6 | image |
   | `image.pose_repair` | 6 | image |
   | `image.pose` | 8 | image |
   | `voice.kokoro-82m` | 1 | line |
   | `voice.chatterbox-turbo` | 2 | line |
   | `voice.chatterbox`, `voice.chatterbox-multilingual`, `voice.qwen3-tts-voices` | 3 | line |
   | `voice.qwen3-tts-clone` | 4 | line |
   | `voice.indextts-2.5` | 5 | line |
   | `assistant.deterministic` | 1 | turn |
   | `assistant.ollama` | 2 | turn |
   | `assistant.anthropic` | 10 | turn |
   | `release.build` | 25 | build |
   | `training.style` | 20 | 100 training steps, rounded up |
   | `training.character` | 25 | 100 training steps, rounded up |
   | `training.character_reference` | 30 | 100 training steps, rounded up |

   - The assistant is priced per provider: each provider runs one model, configured
     for the whole server. An operator who changes that model sets its price with
     the override.
   - Training is priced per 100 steps: a 400-step run uses about 20 times the GPU
     time of a 20-step run.

2. **Each grant has a credit balance.** An invitation carries the credits it grants
   (`FLINT_GRAPH_ACCESS_DEFAULT_CREDITS`, default 500, when the operator gives
   none); joining copies them into the grant.
   - Admission costs `price × quantity`. The quantity is the number of images or
     lines, or 1 for a turn or build, or the training's 100-step blocks.
   - The cost is checked and deducted in the job's admission transaction, after its
     idempotency check, under the grant's row lock (as in ADR 0058). A replayed
     request is free, a refused one costs nothing, and two parallel requests cannot
     both spend the last credits.
   - Too few credits answers **402 `out-of-credits`**. It names the cost, the
     balance and the action ("Generating 4 sprites costs 12 credits, but you have 5
     left.") and carries both numbers in `errors`.
   - A balance never goes below zero. Failed or cancelled jobs are not refunded in
     this slice: the operator tops up instead.

3. **The per-kind limits stay, as rate caps.** Credits are the budget; the limits
   protect shared GPU capacity, and their unit is the thing made (images, lines,
   turns, builds, trainings), not credits.
   - Both must pass: a charge refused by a cap answers 429 `usage-limit` naming the
     kind, as before, and spends no credits.
   - The defaults keep their values. Operators may clear lifetime caps now that
     credits bound the total.

4. **Every balance change is written to a credit ledger** (`credit_ledger`), with
   the change, the amount, the balance after it, the price item and job for
   charges, the operator for adjustments, and an optional note. Changes:
   - `join`: the invitation's credits;
   - `charge`: an admitted job;
   - `add`, `remove`, `set`: operator adjustments. Removing more than the balance is
     refused: set the balance to 0 instead;
   - `unlimited`, `limited`: an operator turning unlimited on or off. The amount is
     zero and the balance is kept.

   A person sees their own ledger; an operator sees anyone's.

5. **Unlimited.** An invitation or grant may be unlimited: no credits are spent and
   no caps apply, as for an operator.
   - Usage is still recorded, and the per-workspace active-job limits still apply.
   - An unlimited invitation stores zero credits and no caps. If an operator later
     turns unlimited off, the person can generate nothing until they get credits.
   - Only operators create unlimited invitations, and the form warns that the key
     is a bearer secret worth unlimited GPU time.
   - The deployment's own operator should be listed in
     `FLINT_GRAPH_ACCESS_ADMIN_EMAILS`, which already means unlimited. An unlimited
     key covers another sign-in, or an operator who is not listed.

6. **Older grants.** Grants and invitations made before this migration have no
   balance (`NULL`). They keep ADR 0058's behaviour, with caps only, until an
   operator sets a balance. Adding or removing credits needs a balance first.

7. **The Studio shows the price before it starts.** `GET /v1/access/me` returns
   the balance, whether the person is unlimited, and the price table.
   - The header shows the balance, or "Unlimited".
   - Each control that starts paid work shows its cost next to the button, and
     warns when the cost is more than the balance.
   - The balance reloads after a paid request or a 402/429.
   - Open mode, operators and unlimited people see no prices.

## Consequences

- Operators can make cheap and expensive work different, and change prices without
  a release.
- A price change applies to new admissions only; the ledger keeps what each job
  cost.
- The Studio repeats the item rules (which image item, how many training blocks)
  to show a price; the server is authoritative and tests pin both.
- Refunds for failed jobs, credit expiry, per-workspace budgets, self-service
  purchase and invoices remain follow-ups.
