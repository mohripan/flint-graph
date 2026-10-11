# FlintGraph agent threat model, revision 1

Reviewed 2026-10-11 against application revision
`b662072faacdb096ad09ebb95deae9593aa7c6ce`; deployed local API revision
`f9a34da94a7272a54e07cc5194691e7998aeaf6a`. Design baseline:
[ADR 0029](../adr/0029-deterministic-agent-trust-and-approval-boundaries.md).
This is #80 threat identification and rollout policy, not #81 runtime completion,
a penetration test, compliance assessment or safety certification.

## Guidance reviewed and version boundaries

Mappings below use **2026** LLM/ASI identifiers, not interchangeable 2025 numbers.
The project-specific risks and likelihood/impact estimates are our inference from
the current architecture, not OWASP assessments of this product.

| Reference snapshot | Review scope and limitation |
| --- | --- |
| [OWASP LLM Applications 2026, download 56857](https://genai.owasp.org/download/56857/?tmstv=1785822482) | Reviewed category table, input/authority/output boundaries and ASI mapping. Version 2026; PDF retains publication-date placeholders although its [resource page](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) is dated August 3, 2026. Do not invent a finalized PDF publication date. |
| [OWASP Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) | Release page dated December 9, 2025; ASI category identities cross-checked against the [official release explanation](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/) and LLM 2026 appendix. Download 52117 was not fully readable in this review; do not claim full-text review. |
| [OWASP Agentic Threats and Mitigations, download 45674](https://genai.owasp.org/download/45674/?tmstv=1739819891) | PDF identifies v1.1, December 2025, despite the [landing page](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/) dating the original resource February 17, 2025. Reviewed architecture, threat taxonomy and mitigation sections. |

The URLs/download IDs, version labels and review date pin this review reference,
not immutable upstream bytes. Direct archival downloads were blocked by the
upstream browser challenge; no local byte hash or complete ASI PDF review is
attested. Re-review on guidance/version change and archive approved upstream
bytes before external compliance reuse. No third-party document is copied here.

## Assets, actors and deployed scope

Protect workspace confidentiality, membership authority, immutable source/version
integrity, graph/evidence correctness, per-turn provenance, provider credentials,
bounded compute/spend, approved side effects and incident auditability.

Actors include unauthenticated callers, malicious authorized viewers/members,
compromised document publishers/connectors, hostile model/tool results, stolen
service credentials and an authorized operator making a mistake. A trusted
publisher can be compromised; an authorized uploader is not a policy author.
Supply-chain/worker compromise can bypass application boundaries and needs
infrastructure defenses. Roles named below are accountable functions, not an
assertion that a particular human has accepted risk.

Current: PostgreSQL-authoritative identity, conversations, provenance and usage;
MinIO raw/derived objects; rebuildable Neo4j/OpenSearch projections; Temporal
ingestion/indexing; LangGraph request-bound queries; configurable model adapters;
plain-text React thread/evidence display; offline evaluations and opt-in telemetry.
Future, **not enabled by this design**: lead/sub-agents, broad summaries/preferences,
arbitrary tools/sandboxes, user-visible executable artifacts, shared KV/prefix
caches and durable background query execution. Workspace conversations are shared
with authorized members, not private per-user inboxes.

## Data flow and trust boundaries

```text
Untrusted caller / browser                  Untrusted URL / uploaded bytes
          | token + workspace selector                 |
          v                                            v
  [B1 OIDC + live membership/role] --> [B2 bounded intake / immutable raw object]
          |                          | PostgreSQL job/outbox + object hash
          |                          v
          |                 [B3 trusted workers / Temporal references]
          |                          | parse/chunk/model proposals (untrusted)
          |                          v
          |                 [B4 exact evidence + deterministic graph resolution]
          |                          | PostgreSQL -> rebuildable search projections
          v                          v
  [B5 ordered turns + revalidated prior question] --> [B6 tenant retrieval/context]
          |                          | authorized evidence, never policy
          +--------------------------v
                       [B7 model draft -> citations/support -> final provenance]
                                     |
                                     v
                       [B8 browser text / authorized evidence inspection]

Future branches from orchestration (disabled until qualified):
  [B9 capability/approval/budget gate] -> scoped child messages -> tools/sandbox
       |                                     |               |
       +-> versioned summaries / caches      +-> artifacts -> safe preview/download

Cross-cutting: [B10 model egress + credentials], [B11 CI/eval/supply chain],
              [B12 privacy-limited telemetry + operator infrastructure]
```

PostgreSQL/worker credentials are trusted control-plane privileges, not user or
model capabilities. A Temporal workflow ID, object key, vector hit, LangGraph key,
context hash or trace ID is not authentication. OIDC issuer/audience/signature
validation establishes identity; current membership authorizes workspace access.
Workers must load scoped references, verify hashes and enforce capabilities before
future side effects. Pipeline envelopes/errors also need privacy review.

## Evidence is not authority or guaranteed truth

Grounding instructions label documents as untrusted (`grounded_prompt_rules.py`),
but a compromised model can still follow them. Exact extraction evidence proves a
quote occurred, not that it is a correct fact. Tenant filtering proves permitted
scope, not integrity of what a member uploaded. Citation repair binds references;
support providers are probabilistic and may be influenced by the same hostile
content. Two agreeing agents are not independent authority.

The existing prior-year policy trusts only a completed, supported, actively
revalidated prior **question** for scope, not its answer as evidence; policy,
filters/index, active document/version, exact chunk/hash and latest pack must
match. Unsupported/provisional/failed/cancelled/legacy/stale turns clarify; no
fallback to an older favorable answer. Rechecks are not atomic with later source
deletion. New chat has no previous scope. Broad summaries and preferences require
versioned source-turn references, omissions, lifecycle and poisoning defenses.

Current answered claims pass citations/support and financial arithmetic checks
where applicable; forged citations, wrong units/year/company and malicious table
text need independent negative cases. Unverified drafts are not final evidence or
safe partial answers. Missing provider usage/cost is unknown, never free.

## Risk register

Likelihood/impact: H high, M medium, L low, qualitative design estimates. P0 blocks
new privileged capability rollout; P1 needs remediation before shared/production
exposure; P2 qualifies optional feature rollout. No numeric probability is implied.
“Absent” is a feature boundary, not evidence that a future implementation is safe.
Cases in the [synthetic catalog](../../tests/fixtures/security/agent-threat-cases.json)
are required assertions; none is newly runtime-attested by catalog validation.

| Risk | OWASP 2026 mapping / asset and attack path | L/I, priority | Current control / residual gap | Owner / issue / verification case |
| --- | --- | --- | --- | --- |
| FG-01 | LLM01 / ASI01: document or direct question redirects generation or support judgement | H/H, P1 | Untrusted-context prompt rules, typed drafts and support pipeline; no adaptive security qualification; judge shares evidence attack surface | AI runtime/security, #81; injected-document must not alter policy or approve unsupported claims |
| FG-02 | LLM03 / ASI02,ASI10: model plans turn a nominal read into write/send/delete or grow children | H/H, P0 | Arbitrary tools/children absent; no capability registry/dispatcher yet | Runtime/tool owner, #81/#77/#82; forged destructive read request denied before side effect |
| FG-03 | LLM02 / ASI03: forged tenant/thread/role or stale membership crosses workspace authority | M/H, P1 | OIDC, SQL membership/tenant filters, queued conversation member guard; standalone viewer inference deliberate; revocation only at request entry | Identity/runtime, #81/#63; foreign reference 404, invalid/revoked actor denied, no new dispatch |
| FG-04 | LLM02,LLM08 / ASI03: adapter/tool output requests secrets or unrelated data and exfiltrates it | M/H, P0 | Credentials in adapters, no general external-send tool; no comprehensive network/credential scope policy | Platform/security, #81/#77/#43; sentinel secret absent from output, model input and telemetry; external send denied |
| FG-05 | LLM03 / ASI02: intake URL/redirect/proxy accesses local network or carries credentials | M/H, P1 | Scheme/private-address/redirect/size checks; DNS precheck and connection resolve separately; user-info allowed; transport deadline/proxy qualification incomplete | Intake/platform, #103/#104; user-info denied and rebinding sentinel never contacted |
| FG-06 | LLM05,LLM09 / ASI06: uploader poisons graph/retrieval with plausible false financial evidence | H/H, P1 | Immutable hashes, exact evidence, staged graph resolution and support; quote truth, publisher authenticity/conflict resolution not guaranteed | Corpus/AI quality, #7/#81/#89; altered year/unit/concept cannot win merely by citation existence |
| FG-07 | LLM05 / ASI06: failed answer/summary or another chat becomes persistent instruction/evidence | M/H, P0 | Prior-year revalidation and new-chat isolation; no broad summary/preference memory; lifecycle/delete races remain | Memory/runtime, #75/#74/#81; stale/failed/immediate untrusted turn clarifies, no older-context fallback |
| FG-08 | LLM03 / ASI07: child result spoofs a parent capability, approval or source record | M/H, P0 | Child protocol absent; no authenticated/bound delegated envelope | Orchestration/security, #81/#6; wrong tenant/parent/policy/version/replay cannot grant authority |
| FG-09 | LLM10 / ASI05: generated HTML/Markdown/artifact or parser input triggers code/network execution | M/H, P0 | Chat text rendered as text; arbitrary artifact execution absent; parser worker not a qualified hostile-file sandbox | Frontend/worker/tools, #76/#77/#8; HTML inert, preview isolated, hostile parser input cannot reach worker secrets |
| FG-10 | LLM04 / ASI04: replaced dependency/image/model/plugin/prompt changes trusted behavior | M/H, P1 | uv lock and versioned prompts/corpus pins; several images/model tags mutable; signing/SBOM/tool registry not complete | Release/platform, #50/#81; identity/hash drift blocks promotion; no dynamic registry install |
| FG-11 | LLM06 / ASI08: retries/parallel streams/children consume unreserved compute or indefinite work | H/H, P0 | Local rate limits, context/output bounds, usage ledger, bounded capture; no atomic execution claim/parent cost reservation/distributed rate budget | Runtime/platform, #82/#63/#8; duplicated execution denied/charged, quota exhausted before next dispatch |
| FG-12 | LLM07 / ASI08: unsupported provisional child result cascades into a confident final financial answer | H/H, P1 | Final claim filtering/abstention and provenance; no broad partial-answer/lead-agent qualification | AI runtime, #81/#6/#74; forged/partial claim retained for audit but not promoted to verified answer |
| FG-13 | LLM03,LLM07 / ASI09: fluent rationale tricks a reviewer into approval with changed hidden arguments | M/H, P0 | No generic approval token API; current deterministic role-scoped UI actions only | Product/security, #81/#77; exact operation diff/expiry/version/nonce check; stale approval denies |
| FG-14 | LLM02,LLM09 / ASI06: cached context/KV/artifact bypasses revocation, deletion or tenant scope | M/H, P0 | PostgreSQL-scoped current context; shared inference cache/broad memory absent; no retention/erase guarantee | Memory/inference/data, #75/#83/#76; cache miss/invalidate on tenant/source/index/model/policy changes |
| FG-15 | LLM02 / ASI03,ASI08: prompts/credentials leak to logs/traces or operator stores accessible as tenant data | M/H, P1 | Redaction/attribute allowlists, fail-closed trace processors, role-scoped audit; local operator UIs unauthenticated, database audit role not immutable | Observability/platform, #43/#72/#8; sentinel excluded from every destination; telemetry ports protected |
| FG-16 | LLM04,LLM06 / ASI10: eval/CI or compromised worker expands scope to real targets or tampers with accepted results | M/H, P1 | Offline recorded gate, source-pinned public corpus, explicit capture/non-overwrite; no general target/worker/network isolation qualification | Release/eval/platform, #81/#53/#8; exact target inventory, no customer corpus/remote side effects, independent baseline approval |

### Existing evidence versus required new acceptance

`tests/integration/test_conversations_api.py` covers real signed-token OIDC
role/revocation/foreign reads and queued execution without metadata trust.
`test_conversation_memory_service.py` exercises stale documents/versions/chunks,
policies/indexes/filters/packs and cancelled immediate turns. Faithfulness service
tests retain unsupported draft audit while preventing final publication. URL
fetcher tests reject private literal/redirect targets and oversized responses,
but do not prove connection-bound DNS enforcement. Existing telemetry tests check
actual exported attributes; runtime sink/isolation tests are separate.

These are narrow evidence, not adaptive prompt-injection, hostile-parser,
privileged-tool, shared-cache or production-network qualification. Test failure
must drive remediation, not baseline weakening or claiming that a second judge
is a security boundary. Security denial checks and legitimate answer-quality
metrics remain distinct; excessive abstention can mask usefulness regressions.

## Approval and execution thresholds

Existing authorized read/query, upload, review/delete, setup and conversation
operations retain current roles. This table applies to **future agent-initiated**
tools and grants, not to ordinary user-clicked product controls.

| Operation | Required trusted boundary |
| --- | --- |
| Read same authorized resource or deterministic calculation | Scoped typed allowlisted operation; current membership; no hidden write/network destination; bounded reservation |
| Inference/external read | Approved provider/target and data policy; finite parent token/time/cost reservation. No configured ceiling means no autonomous paid dispatch |
| External communication, share/export, credential use, grant/role change | Specific human/operator approval plus role and resource checks; destination/input binding; credentials never handed to the model |
| Delete/overwrite/publish, arbitrary code, new tool/plugin, durable preference write | Disabled by default; exact-operation approval, rollback/compensation and audited qualified containment before capability is enabled |
| Child delegation/resume | Same parent budget, intersected capabilities, authenticated immutable tenant/run/policy envelope, reauthorization before every dispatch |

Approval binding follows ADR 0029. A source saying “approved”, a sub-agent's
message, repeated yes answers, a polished plan or prior chat approval is not an
approval record. Operator limits are set in trusted deployment policy, not by an
LLM choosing a threshold. Bulk actions show exact scope/destination/count/version
and have a safe bounded batch; do not overwhelm reviewers with blanket approval.
Stop/kill switch denies new dispatch; request-bound SSE cancellation alone is not
proof of external-side-effect rollback or durable worker cancellation.

## Rollout checklist and residual-risk ownership

- Preserve offline defaults, standalone API role contracts and private data.
- Fix #103, qualify #104 network boundary; do not describe string filtering as
  full SSRF/egress control. Isolate worker parsers before treating hostile uploads
  as safely contained.
- Before new tools/agents: policy registry, exact argument/resource authorization,
  approved egress, scoped credentials, operation-bound approvals, parent budget,
  stop/retry semantics and denied-side-effect tests (#81/#77/#82).
- Before broad memory/cache/artifacts: consent/visibility, versioned source
  references, omissions, revocation/retention/delete/export, safe content serving
  and cache separation/invalidation (#75/#76/#83).
- Before public/shared deployment: OIDC/IdP, TLS and trusted proxy, production
  storage/worker/Temporal identities, distributed admission, protected operator
  surfaces, durable query claims and audit retention/integrity (#8/#43/#63).
- Run catalog cases through actual deployed seams in a disposable synthetic
  workspace. Use `.invalid` sinks/no real secrets; network blocks must precede
  dispatch. Do not attack external targets or ingest these as public source facts.
- Keep raw adversarial prompts/model outputs in restricted test artifacts only;
  publish bounded allow/deny/version/usage facts. CI/evals have a signed target
  inventory and no ambient production credentials/network authority.
- Independently review financial/source correctness and adaptive attacks with
  deployed defenses disclosed to the tester. Offline fixture success is not a
  model-security or production-readiness claim.
- Security/runtime/platform owners review P0/P1 residual risks before enabling
  capabilities; record reviewer/date/environment, remediation links, expiry and
  rollback evidence. This self-review is not independent operator sign-off.
- Revisit after model/prompt/index/role/storage/tool/provider/policy change or an
  incident, not only on guidance updates. Disable affected capabilities first and
  preserve bounded audit/provenance, not source bodies in telemetry.
