# ADR 0074: A balance on your own server

Status: accepted, 2026-11-07

## Context

The person running the server had no number to look at. Open mode showed nothing at all, an operator's pill said
"Unlimited", and cards said "free for you". The owner wants to see what generating costs, and to see it the way the
people they invite will. The owner chose this among three options: a real balance that never blocks, one that stops
at zero, or only a spent counter.

## Decision

Open-mode users and operators have a **balance that counts down and never stops them**. It starts at
`access_default_credits`, is charged at the same prices, appears in the same ledger, and is shown at the top of the page
and on Usage. It stops at zero rather than going negative. Generating still works, and the ledger keeps the true cost of
each thing made, even where the balance could not fall further.

**It lives in its own table, `own_credits`, and is not a grant.** A grant gives access. Creating grants for these people
would leave anyone removed from the operator list, or anyone who used a server before it moved to invite mode, with
working access. A test holds this: the balance alone gives no access.

**Usage made this way is marked `own_server`,** and never counts against an allowance. Without this, someone who
later joined with a key would find their caps already used up, as a test found during this work.

**`unlimited` keeps its meaning,** that nothing is enforced. A new `keeps_going` says the balance is real. An invited
person with an unlimited key still sees "Unlimited", because an operator chose that for them.

Locking the person's row serializes their charges, so two first charges cannot both create the balance.

## Consequences

- At zero the number stays at zero. There is no way to top up your own balance yet. An operator's adjustments work on
  grants only.
- Nothing is backfilled: the balance starts full on the first charge after this ships, and earlier work is not counted.
- Every charge in open mode now writes rows, which it did not before. A failed write fails that job's admission,
  like any other part of the admission transaction.
