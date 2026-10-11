# ADR 0029: Deterministic agent trust and approval boundaries

- Status: accepted design baseline; runtime remediations are not all implemented
- Date: 2026-10-11
- Track: security / Milestone 29, #80; enforcement #81, budgets #82

## Context and alternatives

FlintGraph already has OIDC/membership, tenant-filtered reads, verified extraction
evidence, final-answer support checks and narrow revalidated prior-year context.
These do not establish permission for future tools, sub-agents, summaries or
artifact execution. The local runtime still uses dev auth and request-bound SSE.

1. Give models/user-selected tools ambient worker credentials and rely on prompt
   rules or a second model judge: insufficient authority boundary.
2. Put scoped operations, resource authorization, budgets and approval consumption
   in trusted server code, keeping model/source output as untrusted proposals:
   selected. Incremental qualification precedes capability rollout.
3. Enable every tool in a nominal sandbox first: containment alone does not bind
   tenant ownership, network access, side effects or financial truth.

## Decision

Models never authorize membership, capability grants, credential access, egress,
side effects, budget changes or approvals. A child execution inherits an
intersection of parent capabilities and current workspace policy, never a union.
Source documents, retrieved chunks, answers, summaries and agent messages are
data with provenance; schema validity, citation existence and multiple agreeing
models do not make them trustworthy instructions or correct financial facts.

Current operations retain their existing role contracts. New execution/tool
capabilities default off until a typed policy gate and qualified enforcement seam
exist. A received message or document cannot enable them. No arbitrary model code,
SQL, URL, shell command, artifact preview or dynamically discovered plugin is
executed merely because it appears in generated output.

Sensitive actions require a trusted exact-operation approval record binding actor,
tenant, parent run, operation/version, canonical argument digest, resource/version,
destination, maximum reservation, expiry and single-use identity. Reauthorize and
consume atomically immediately before the action; changed inputs, roles, versions,
expired/replayed grants or absent cost ceilings deny. Cancellation prevents new
dispatch; already committed external effects need explicit compensation. Approval
does not grant a missing role. This is a required design, not an existing token API.

Credential material remains outside model context and inter-agent envelopes.
Accountable server facts, not reasoning text, drive audit/usage. Unknown usage
remains unknown. Every child/retry must draw from the same parent reservation;
measuring usage after a call is not prevention. Caches are explicitly scoped by
workspace/authorization, source/index/model/policy versions, with invalidation.
Inference KV state is not the conversation system of record.

## Delivery and residual risk

The [threat model](../architecture/agent-threat-model.md) records implemented,
partial and proposed boundaries and synthetic required cases. Its catalog tests
validate governance assets, not runtime attack resistance. Rollout requires
negative tests at actual capability/transport/storage/render boundaries, separate
usefulness and adversarial model measurements, deployment controls and a reviewer
accepting residual risk. No OWASP certification or complete safety is claimed.

The URL review found credential-bearing URL dispatch and separate DNS
validation/connection resolution. Track them as #103 and #104; neither is fixed
by this ADR. Production operator telemetry, worker/parser isolation, durable
query claims, approval tokens, budgets and broad memory/tool rollout remain
#43/#8/#63/#81/#82/#75/#77. Existing data/volumes/providers and offline baselines
are unchanged.
