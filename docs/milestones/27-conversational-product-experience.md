# Milestone 27: Conversational product experience

Status: in progress; epic [#84](https://github.com/mohripan/flint-graph/issues/84).

| Issue | Scope | State |
| --- | --- | --- |
| [#96](https://github.com/mohripan/flint-graph/issues/96) | Authorized conversation/ordered-turn/run ledger | implemented and locally verified |
| [#62](https://github.com/mohripan/flint-graph/issues/62) | Bounded grounded follow-up execution | in progress; memory not delivered |
| [#73](https://github.com/mohripan/flint-graph/issues/73) | Accessible new/reopen/thread Ask UI | planned |
| [#74](https://github.com/mohripan/flint-graph/issues/74) | Fresh multi-turn quality and isolation gates | planned |
| [#75](https://github.com/mohripan/flint-graph/issues/75) | Memory architecture, invalidation and lifecycle qualification | planned |

The ledger is workspace-shared and preserves real server-backed order, identity,
idempotency and restart/reopen. Its turns still execute independently; capability
detection says so. See [contract](../architecture/conversation-contract.md),
[ADR 0026](../adr/0026-conversation-ledger-foundation.md) and
[verification report](../reports/2026-10-10-conversation-ledger.md).

Acceptance for the full milestone still needs source-revalidated follow-ups,
isolated new-chat context, safe handling of failed/unsupported/provisional turns,
long-history/reservation bounds, UI/browser verification and realistic fresh
multi-turn model tests. Coordinate #80/#81 guardrails, #82 budgets, #83 cache
qualification and #63 reference-only durable execution. No complete memory or
durable query execution claim follows from storage alone.
