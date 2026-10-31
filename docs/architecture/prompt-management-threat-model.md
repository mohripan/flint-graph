# ADR 0029 addendum: prompt-management deployment boundary

Date: 2026-11-01. Design for #134; enforcement/activation remains #135–#140.
Read with [ADR 0029](../adr/0029-deterministic-agent-trust-and-approval-boundaries.md),
[the existing threat model](agent-threat-model.md) and
[ADR 0044](../adr/0044-langfuse-authoring-and-reviewed-prompt-locks.md).

Langfuse adds an instruction-authoring supply chain at B11, not a new authority
for B1 membership, B9 approvals/budgets or B10 model credentials. Protect prompt,
schema, model-config and image-policy integrity, per-run identity and private
inputs. Actors include a mistaken/hostile author, a stolen promotion/runtime key,
a compromised server/SDK, and a source author attempting template injection.

| Threat | Required boundary / negative qualification |
| --- | --- |
| Label moved to unreviewed instructions or relaxed image rules | Admit only identities in the deployed reviewed lock; flag drift and retain the complete approved bundle. Label changes alone cannot deploy |
| Server returns the right version number with altered template/config/schema | Recompute all hashes locally and compare; quarantine before rendering; test each independent mismatch |
| Template config adds a shell tool, endpoint, secret lookup or unlimited tokens | Strict typed fields and application ceilings; reject unknown capabilities/config; prompts cannot grant permission |
| Missing policy resolves to empty lists or a later retry uses another policy | Complete policy fallback and immutable job snapshot; reject missing historical bundle rather than changing it |
| SDK cold cache stalls a request or stale cache silently activates new text | Requests read the local approved map only; background SDK cache is untrusted staging; exercise cold/outage/expiry/label movement |
| A label update divides one answer/extraction/proposal across versions | Snapshot the entire bundle before dispatch; preserve it across repairs, activity retries, restarts and queued jobs |
| Prompt management uploads private rendered input or creates a second telemetry sink | Templates/config only; local compile; tracing disabled explicitly; runtime read-only key and ingestion/media denial. Inspect actual network traffic during rollout |
| A broad runtime key alters prompts, even when protected labels exist | Separate read/author/release credentials; verify read succeeds and write/label mutation fails against the pinned server. Enterprise UI protection does not replace this |
| Untrusted variables introduce new template syntax or instruction delimiters | Declared type/exact-key validation, one substitution pass, safe serialization and separately versioned delimiter-hardening tests; server authorization remains independent |
| Build/rollback bundle substituted or old artifacts deleted | Reviewed content-addressed bundle artifacts, retained historical locks, atomic publication and audited rollback; fail invalid readiness / missing historical job identity |

Production promotion records actor/reviewer, old/new bundle, numeric versions,
schema/config hashes and evaluation reference. Records carry no tenant payload.
Missing Enterprise audit features do not waive this requirement. Operators own
network/auth hardening and separate storage for any future Langfuse deployment;
do not reuse or alter the current application/worker fixtures for this design.

Residual risks: a maintainer-approved malicious prompt can still harm output
quality; keyword/negative image policy cannot prove output suitability; privileged
server/build compromise remains a supply-chain risk. Prompt control does not
replace deterministic approval, provenance or resource gates. The isolated SDK
probe qualifies vendor behavior under a synthetic transport, not live access
control or resistance to attacks on a deployed Langfuse instance.
