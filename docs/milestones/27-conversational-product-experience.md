# Milestone 27: Conversational product experience

Status: in progress; epic [#84](https://github.com/mohripan/flint-graph/issues/84).

| Issue | Scope | State |
| --- | --- | --- |
| [#96](https://github.com/mohripan/flint-graph/issues/96) | Authorized conversation/ordered-turn/run ledger | implemented and locally verified |
| [#97](https://github.com/mohripan/flint-graph/issues/97) | Revalidated bounded prior-year follow-ups | implemented; qualification recorded separately |
| [#98](https://github.com/mohripan/flint-graph/issues/98) | Authorized title search/rename for the sidebar | implemented; qualification recorded separately |
| [#62](https://github.com/mohripan/flint-graph/issues/62) | Broader grounded follow-up execution | in progress; narrow prior-year slice only |
| [#99](https://github.com/mohripan/flint-graph/issues/99) | Capability-gated thread UI, discovery, evidence and request-bound recovery | implemented and locally qualified; CI recorded in the issue |
| [#100](https://github.com/mohripan/flint-graph/issues/100) | Member-only queued conversation stream execution | implemented; verification and CI recorded separately |
| [#101](https://github.com/mohripan/flint-graph/issues/101) | Named transcript and keyboard focus lifecycle | implemented; browser/live qualification recorded separately |
| [#73](https://github.com/mohripan/flint-graph/issues/73) | Accessible new/reopen/thread Ask UI | in progress; first UI slice #99, full acceptance remains open |
| [#74](https://github.com/mohripan/flint-graph/issues/74) | Fresh multi-turn quality and isolation gates | planned |
| [#75](https://github.com/mohripan/flint-graph/issues/75) | Memory architecture, invalidation and lifecycle qualification | planned |

The ledger is workspace-shared and preserves real server-backed order, identity,
idempotency and restart/reopen. The prior-year slice now resolves a bounded
follow-up using only a revalidated immediately previous question, never answer
text as evidence. Capabilities distinguish this from general chained memory.
See [contract](../architecture/conversation-contract.md),
[ADR 0026](../adr/0026-conversation-ledger-foundation.md) and
[ledger verification](../reports/2026-10-10-conversation-ledger.md) and
[follow-up verification](../reports/2026-10-10-prior-year-followups.md).
See [first thread UI verification](../reports/2026-10-11-conversation-thread-ui.md)
for desktop/mobile, read-only/retry/recovery/isolation and fresh real-model evidence.
The first thread UI follows [ADR 0028](../adr/0028-capability-gated-conversation-thread-ui.md).
It is capability-gated and retains the independent-question view; browser-side
history concatenation is not used. The backend enforces queued conversation
execution authorization from actual turn references and current membership,
independently of recovery controls. See [authorization verification](../reports/2026-10-11-conversation-stream-authorization.md).

Acceptance for the full milestone still needs source-revalidated follow-ups,
isolated new-chat context, safe handling of failed/unsupported/provisional turns,
long-history/reservation bounds, UI/browser verification and realistic fresh
multi-turn model tests. Coordinate #80/#81 guardrails, #82 budgets, #83 cache
qualification and #63 reference-only durable execution. No complete memory or
durable query execution claim follows from storage alone.
