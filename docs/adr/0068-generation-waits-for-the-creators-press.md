# ADR 0068: Generation from the assistant waits for the creator's press

- Status: accepted
- Date: 2026-11-07
- Extends: [ADR 0059](0059-credits-and-unlimited-access.md), [ADR 0061](0061-assistant-runs-generation.md)
- Replaces: ADR 0061's **Generate automatically**

## Context

ADR 0061 let the assistant start GPU work by itself. A checkbox in the composer, on by default,
sent actions straight to the dispatcher. That spends someone's credits and GPU time on what a
local model understood them to want, and the user who invited them is the one paying for the GPU.
The user asked for the opposite before showing the Studio to anyone: nothing that uses the GPU
runs from the chat until the person has seen what it will make and what it costs, and agreed.

## Decision

Every generation action, and every child session, appears in the chat as a **card**:

- what it will make, in the words of the request;
- the model, how many results, and their shape;
- what it costs;
- **Cancel** and **Generate** (the button names what it makes), and a link to the page with more
  controls.

Nothing starts until Generate is pressed. There is no setting to skip this.

### The server writes the card

`ActionQuote` is built by `list_actions` for actions that are `offered`, `blocked` or `declined`.
Its `parts` are the price items and quantities admission charges. The Studio used to repeat those
rules to work out a price; it now only multiplies the server's `parts` by the server's prices.
`test_every_card_costs_exactly_what_it_says` presses each kind of card and compares the ledger.

A person who pays nothing (open mode, an operator, an unlimited grant) sees the number and "free
for you", so nobody reads a missing price as a broken card. A balance that is too low disables
Generate and says so; the server refuses at admission whatever a page does.

### States

| State | Meaning |
| --- | --- |
| `offered` | Shows its card, and waits |
| `pending` | Pressed while the queue was full; the dispatcher starts it when there is room |
| `started`, `finished` | Bound to a job; its progress and results replace the card |
| `blocked` | Could not start from the queue; the card stays, with the reason and **Try again** |
| `declined` | Cancelled; nothing was generated and nothing was charged |
| `skipped` | The proposal was rejected first |

`waiting` is gone. An action that needs what its proposal adds stays `offered` with `needs_accept`,
so its card can say so. Accepting the proposal no longer starts anything by itself.

Migration 0051 returns existing `waiting` and `pending` rows to `offered`: they were queued under
the old setting, and asking again costs nothing. The API still accepts `auto_generate` so a tab
opened before the deploy can send a message, and ignores it. The turn column stays as history.

`declined` is not final. **Show again** opens the card locally, and pressing Generate starts it.
`start_action(queued=True)` is how the dispatcher calls it, and only starts what is still `pending`,
so a Cancel that lands after the dispatcher read its queue still wins.

### What the model hears

`proposal.created` now records the proposal's actions, and `action.declined` is new. The model's
history says a card is "not started, waiting for the creator to press Generate", or that the
creator cancelled it, instead of leaving it to assume the file is coming. Older log events without
the field still fold.

Prompt v9 tells it that nothing has started when it replies, and gives it a sentence to copy.

### Charges made by the worker

A press that finds the queue full starts later, in the assistant worker, which has no request. Its
`charge_usage` used to fall back to the code's price table and to charging in open mode, so it
could disagree with the card. `act_for` now gives that session the deployment's prices and open
mode. Operators are not recognised there, because the worker has no sign-in token, but operators
have no grant to charge.

## Chat messages

A chat message is charged when it is sent, as ADR 0059 already did, and the composer shows the
price. It does not get a card: it is the conversation itself. A person with too few credits gets
the 402 and no GPU time. A test now holds this too.

## Alternatives

- **Keep the checkbox, off by default.** One tick away from the behaviour the user does not want
  shown to people, and it needs the card anyway.
- **Ask in words and wait for "yes".** A local model would have to understand the yes, and a
  misunderstanding spends money. A press cannot be misread.
- **Compute the price in the page.** That is what there was. It repeated the server's rules, and
  nothing checked that they agreed.

## Consequences

- Asking for a picture takes one more press. That press is the point.
- Starting work still needs no open page once pressed, since jobs and the queue are durable.
- Failed or cancelled jobs are still not refunded (ADR 0059), so a card's price is what a job costs
  to admit, not a promise of results. Results still wait for approval.
- Generators on the Characters and Assets pages already show their price beside their own button,
  and are unchanged. They are the "more control" a card links to.
