# Agent threat-model design verification

Scope #80, Milestone 29. Delivered architecture-specific data flow/trust
boundaries, 16-risk register, exact-operation approval design, ownership and
rollout gates, ADR 0029, synthetic required-case catalog and asset integrity test.
No runtime policy registry, sandbox, approval token, cache, budget reservation or
new tool is enabled by this change. No OWASP certification, adaptive attack pass,
independent security sign-off or production-readiness claim.

OWASP review covers current 2026 LLM category numbering, the official ASI 2026
release/category explanation and the v1.1 agent threat taxonomy. Exact resource
versions/URLs and mutable-date discrepancies are recorded in the threat model.
LLM PDF retains release-date placeholders; Agentic Threats PDF v1.1 is newer than
its landing page. ASI PDF full text/immutable source byte hashes were not available:
web parsing failed and direct archival downloads met an upstream browser challenge.
Those are not recorded as successful PDF review/download/hash checks. The official
ASI explanation and LLM appendix were cross-checked instead. Re-archive/review
before external compliance use or upstream category change.

The code review found user-info intake URLs and DNS validation separate from
actual transport resolution. Focused remediation issues #103 and #104 were
created; no production exploit was attempted or claimed. Other gaps map to
#81/#82/#75/#76/#77/#83/#43/#50/#63/#8 rather than duplicated completion claims.
Catalog cases are redacted synthetic requirements; their asset test validates
coverage/labels, not the enforcement they describe.

## Verification and current deployed evidence

Passed in this change:

- Asset test failed before catalog/design existed, then passed with all 16 risks
  mapped to required deny/abstain/clarify/encoding/budget-stop assertions.
- PostgreSQL opt-in focused memory/security plus URL/faithfulness/catalog suite:
  55 passed in 17.07s. Existing stale-source/policy/index/failed-turn, request
  limits/rate and unsupported-final-answer boundaries remain covered. These
  fixtures are not a new real-model security gate.
- `uv run ruff check .`; `uv run mypy` (160 source files); deterministic Acme
  evaluation gate; `git diff --check`; Compose/lock checks recorded at commit.
- Actual read-only public-run and public-conversation GETs using a foreign
  workspace selector returned 404. No private resource was read; no mutation,
  stream execution, inference or external side effect occurred.
- API `/health/live` and frontend localhost:5173 returned 200.

Earlier in the same session, before this documentation/catalog-only change:
971 backend passes/15 skips, PostgreSQL signed-token conversation/query API
136 passes/five skips, migration SQL 1061 lines, fresh public financial/reset
captures and actual desktop/mobile read-only frontend reopen passed (#102 report).
Those establish narrow existing controls/usefulness, not attack-case acceptance.

Not rerun for this documentation/catalog-only change: complete backend suite,
frontend unit/build/full browser suite, offline migration SQL or another paid/local
model capture. Not performed: adversarial probes on private/third-party targets,
source deletion, parser exploit, privileged tool/sandbox, inter-agent/cache,
production network, approval/replay, cost-reservation or operator telemetry
qualification. Full runtime adversarial enforcement remains #81, and deployment
residual risks need explicit operator review. CI results are linked in the issue
after pushing, not presumed here.
