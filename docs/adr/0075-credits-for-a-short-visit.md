# ADR 0075: Credits for a short visit

Status: accepted, 2026-11-07. Replaces the balance in [ADR 0074](0074-a-balance-on-your-own-server.md).

## Context

People invited to the Studio are meant to play around for about 15 minutes, and GPU time costs the owner money. A
default of 500 credits allowed far more than that. A release build was the most expensive single item at 25 credits,
though it uses no GPU, only some CPU and storage. The owner also decided that their own credits can be unlimited,
replacing the balance from ADR 0074.

## Decision

- **New invitations grant 100 credits by default.** Grants already made keep what they have.
- **A release build costs 5 credits**, less than one set of sprites. Its cost is real but small, and a share-worthy game
  at the end of a visit is the point of being here.
- **On your own server, credits are unlimited.** Open-mode users and operators see "Unlimited", and Usage shows what
  they have used so far, with the same history. Charges are still recorded, marked `own_server`, so the owner can see
  what things cost, and they never count against a later allowance. The `own_credits` table is gone (migration 0057).
  Their old starting entries go, and "left" figures clear; anyone who also holds a grant keeps every entry.

A test holds a typical 15-minute visit to the default: ten chat replies, two sets of high-resolution sprites, a set of
backgrounds, five voiced lines, a song and a build come to 88 credits, and doing it twice over would not fit.

## Consequences

- 100 credits is an estimate of a visit, not a measurement. Nobody has timed one yet.
- Other prices are unchanged. A 200-step character training run costs 50 credits, half a visit, and holds the GPU far
  longer than anything else. It stays opt-in; consider a cap if it is ever offered to invited people.
- An operator can still give someone more with an explicit amount or an unlimited key.
