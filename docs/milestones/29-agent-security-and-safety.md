# Milestone 29: Agent security and safety qualification

Status: in progress; [epic #86](https://github.com/mohripan/flint-graph/issues/86).

| Issue | Scope | State |
| --- | --- | --- |
| [#80](https://github.com/mohripan/flint-graph/issues/80) | Architecture-specific OWASP-informed threat model | design baseline and synthetic required-case catalog; verification recorded separately |
| [#81](https://github.com/mohripan/flint-graph/issues/81) | Trusted policy/approval/egress/adversarial runtime enforcement | planned; current membership/evidence controls are not full acceptance |
| [#103](https://github.com/mohripan/flint-graph/issues/103) | Reject credential-bearing URL intake | identified remediation, not yet implemented |
| [#104](https://github.com/mohripan/flint-graph/issues/104) | Connection-bound DNS/redirect enforcement | identified gap; no demonstrated production exploit or fix yet |

See [ADR 0029](../adr/0029-deterministic-agent-trust-and-approval-boundaries.md) and
the [risk register](../architecture/agent-threat-model.md). Model/source/agent
messages cannot authorize membership, capabilities, budgets or side effects.
Future tools, summaries, shared caches and artifacts remain gated off until
their actual boundaries are qualified. Governance/catalog checks are not runtime
attack-resistance tests or certification. Coordinate #75/#76/#77/#82/#83/#43,
Milestones 18/20/22/28 and independent usefulness/financial-quality gates.
