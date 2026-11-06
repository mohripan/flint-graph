# Credits, prices and unlimited access (ADR 0059)

The user asked whether there can be many keys, so some can be removed and others
added. They also wanted to give each person some credits, with cheap generation
costing less than expensive generation, and an unlimited key for themselves.

ADR 0058 already allowed many keys, each revocable. This delivery adds credits on top
of its per-kind limits: [ADR 0059](../adr/0059-credits-and-unlimited-access.md).

## What changed

- **Price table** in `src/flint_graph/application/credit_prices.py`: 21 items across
  images, voice lines (one per catalog model), assistant turns (one per provider),
  release builds and trainings (per 100 steps).
  - `FLINT_GRAPH_ACCESS_CREDIT_PRICES` overrides single prices; unknown items or
    prices outside 0–100,000 stop the API from starting.
- **Balances.** An invitation grants credits (`FLINT_GRAPH_ACCESS_DEFAULT_CREDITS`,
  default 500, when none is given); joining copies them into the grant.
  - `charge_usage(item, units, quantity)` checks the per-kind caps first and then the
    balance. It deducts in the job's admission transaction under the grant row lock,
    so replays are free and refusals cost nothing.
  - Images pick their item from what they make, through the shared `_queue_job`.
    Poses and repairs pass their own item.
  - Voices are priced by the character's model, the assistant by the server's
    provider, and training by target, reference conditioning and 100-step blocks.
- **402 `out-of-credits`** names the action, its cost and the balance, for example
  "4 × Standard image costs 8 credits (2 each), but you have 3 left.", with
  `credits_needed`/`credits_left` in `errors`. Caps still answer 429 `usage-limit`.
- **Credit ledger** (`credit_ledger`): join, charge, add, remove, set, unlimited and
  limited, each with the amount and the balance after it.
  - Charges carry the item, quantity and job.
  - Adjustments carry the operator and an optional note.
- **Unlimited** invitations and grants spend nothing and have no caps.
  - An unlimited invitation stores 0 credits and no caps, so turning it off fails
    closed.
  - Operators remain unlimited without a grant.
- **Operator API:** `POST /v1/admin/access/grants/{id}/credits` (add, remove, set, with
  a note), `POST …/unlimited`, and `GET …/credits` (history). People read their own
  history at `GET /v1/access/credits`.
- **`GET /v1/access/me`** adds `credits`, `unlimited`, `prices` and `assistant_item`.
- **Migration `0044_access_credits`.**
  - Nullable `credits` and `unlimited` on invitations and grants.
  - `usage_charges.item`.
  - The `credit_ledger` table.
  - Older grants keep `NULL` credits and stay on caps only until an operator sets a
    balance.
- **Studio:**
  - The header shows the balance, or "Unlimited credits".
  - Every control that starts paid work shows its cost and turns red when the
    balance is short: backgrounds, CGs, character images, expressions, poses, pose
    repairs, scene and line voices, voice samples, training, release builds,
    assistant turns and accepted image suggestions.
  - The voice model picker shows the price per line.
  - The balance reloads after each paid request and after a 402 or 429.
  - **Usage** shows the balance, caps, the active price list and the credit history.
  - **Invitations** sets credits or unlimited on new invitations, warns about
    unlimited keys, and gives each person Add/Remove/Set, Make unlimited and
    History.
- **Join page:** a proxy 5xx or a failed fetch now says the server can't be reached,
  instead of showing "502 Bad Gateway" under the key form.

## Verification

- Backend tests:
  - `uv run pytest tests/unit/test_access_credits.py tests/unit/test_access_keys.py tests/integration/test_access_credits_api.py tests/integration/test_access_invitations_api.py`:
    18 passed.
  - With `FLINT_GRAPH_NARRATIVE_PG_URL` pointed at a throwaway PostgreSQL 17
    container: 14 passed (SQLite and PostgreSQL). The PostgreSQL runs migrate each
    schema with Alembic.
- Full `uv run pytest` on the final code: 2058 passed, 124 skipped.
- Static checks:
  - `uv run ruff check .` and `uv run mypy` (304 files): clean.
  - `ruff` now allows the `×` used in price messages.
- Frontend:
  - `npm --prefix frontend test`: 150 passed. The new credit-model tests mirror the
    server's item rules.
  - `npm --prefix frontend run typecheck` and `run build`: clean.
- Offline eval gate (`flint-graph-eval run … --config-name deterministic`): exit 0.
- Migration SQL: `alembic upgrade head --sql` renders 0043 → 0044 (with
  `FLINT_GRAPH_ENV=test`).
  - On the QA PostgreSQL, 0044 downgraded to 0043 and upgraded again cleanly.
- **Live QA** used a separate PostgreSQL container, two dev-auth APIs (an operator on
  8291 and a guest on 8292) and their own Vite servers (5291/5292). The user's Studio
  and the shared fixtures were not touched. Over HTTP:
  - The guest is refused before joining, then joins with a 20-credit key.
  - 4 backgrounds leave 12 credits.
  - Five parallel 4-credit requests admit exactly three and refuse two with 402. The
    balance ends at 0, never below.
  - The ledger shows join plus four charges.
  - The operator adds 50 with a note; the audit shows the operator's email.
  - While unlimited, a 4-image job spends nothing. With unlimited off again, spending
    resumes.
  - An unlimited key stores 0 credits and no caps.
- In the browser pane:
  - The guest's header showed 48, then 40 credits after a job started from the page.
  - "Generate 4 backgrounds" showed "8 credits", then "8 credits · you have 3" in red
    at a balance of 3.
  - Submitting anyway showed the 402 sentence in the form.
  - Usage listed the prices and the full history with operator notes.
  - The operator's header showed "Unlimited credits".
  - Invitations added 25 credits with a note (3 → 28) and showed the history.
  - Ticking Unlimited showed the bearer-key warning and hid credits and caps.
  - The only console error was the intended 402.

## Limits and follow-ups

- Failed or cancelled jobs are not refunded; operators top up by hand.
- Prices are per admission and per item, not measured GPU seconds. A slow job costs
  the same as a fast one of its item.
- The Studio repeats the server's item rules to show a price beforehand. The server
  decides the charge, and tests pin both sides.
- Credit expiry, per-workspace budgets, self-service purchase and invoices are not
  part of this slice.
