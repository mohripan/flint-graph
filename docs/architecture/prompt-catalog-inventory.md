# Prompt inventory and Langfuse compatibility contract

Original contract baseline: `77cb2c8`, reviewed 2026-11-01 for #134. The migration
is now implemented: the table records the former builders and their variable
contracts. All fragments and provider wire-schema variants belong to the complete
bundle identity. See the implementation notes and report below.

## Exact migration inventory

| Catalog entry / type | Current source and identity | Declared variable inputs / configuration |
| --- | --- | --- |
| `grounded.answer.anthropic` / chat | `infrastructure/anthropic.py::_answer_system_prompt`, `_answer_user_prompt`; `grounded-answer-v3` | query string, formatted context-record string, optional verified-calculation lines; explicit claim response schema |
| `grounded.answer.ollama` / text | `infrastructure/ollama.py::_build_answer_generation_prompt`; `grounded-answer-v3` | same semantic inputs; preserve Ollama wording and format schema separately |
| `grounded.support.anthropic` / chat | `anthropic.py::_support_system_prompt`, `_support_user_prompt`; `grounded-support-v3` | query and preformatted indexed claims with their cited evidence; support response schema |
| `grounded.support.ollama` / text | `ollama.py::_build_support_check_prompt`; `grounded-support-v3` | same semantic inputs; preserve provider-specific wording/schema |
| Shared grounded rule fragments | `application/grounded_prompt_rules.py::ANSWER_RULES`, `SUPPORT_RULES`, `verified_calculation_lines` | trusted verified-calculation hint serialized locally, not remote tool execution; include all explanatory lines in containing answer template identity |
| `extraction.builtin.ollama` / text | `application/extraction.py::build_extraction_prompt`; `builtin-graph-v2` | ordered chunk IDs/text serialized locally, output-shape text/schema; preserve headings and separators |
| `extraction.proposals.ollama` / text | `ollama.py::_build_proposal_extraction_prompt`, `_proposal_extraction_schema`; `proposal-v1` in `worker/activities/ingestion.py` | formatted chunks and example-output instructions; hand-built provider response schema plus `ExtractionBatch` validation |
| `narrative.assistant.system` / chat system message | `narrative/assistant/prompts.py::SYSTEM_PROMPT`, `RESPONSE_SCHEMA`, `PROMPT_VERSION`, `prompt_sha256`, `PINNED_PROMPTS`; currently v3 | static system instructions and schema; keep old hashes meaningful for historical actions |
| `narrative.assistant.context` / text inserted as user message | `narrative/assistant/context.py::build_turn_messages`, `_render`, formatting helpers | bounded/escaped story outline, focus/neighbors, library IDs/metadata, saved appearance profiles, request and bounded history; formatting algorithms remain trusted code |
| `narrative.assistant.repair` / text appended as user message | `narrative/assistant/turn.py::_repair_request` | bounded diagnostics code/location list; include the complete corrective wording |
| `narrative.image.portrait` / text conditioning | `narrative/imagegen.py::portrait_request`, `_portrait_negative`, `QUALITY`, `QUALITY_NEGATIVE`, `TYPE_NEGATIVES` and transparency/type/framing fragments | normalized appearance and character type; generation/hires settings are typed config, resource ceilings remain code |
| `narrative.image.pose` / reference editing | `narrative/poses.py::pose_request`; FLUX.2 klein 4B, ADR 0048 | reviewed appearance and pose text; 4 steps, guidance 1, token ceiling 512. Distilled editing has no negative conditioning; typed input policy still applies. Reference verification, staging and resource limits remain code |
| `narrative.image.expression` / text conditioning | `imagegen.py::expression_request`, `EXPRESSION_QUALITY`, expression/negative fragments | approved-base description and expression tags; crop/reference/strength validation remains code |
| `narrative.image.background` / text conditioning | `imagegen.py::background_request`, `BACKGROUND_QUALITY`, people-exclusion and quality-negative fragments | place description; keep negative-prefix order and token limits |
| `narrative.image.scene_solo`, `narrative.image.scene_pair` / text; `narrative.image.scene_conditioning` / policy | `imagegen.py::scene_art_request`, `_solo_scene`, `_pair_negative`, `SCENE_QUALITY`, `SOLO_NEGATIVES` and the character-count tags | scene text and each referenced character's description (one or two); reference images, adapter scale and half masks remain code |
| `narrative.image.content_policy` / policy | `narrative/image_content_policy.toml`; `imagegen.py::ContentPolicy`, `content_policy`, `_negative` | typed version/negative/blocked config. A Langfuse text record can carry a fixed schema marker plus config; it is never itself sent as an LLM request |

Paths are under `src/flint_graph/` unless stated. The catalog renderer owns
instruction wording; provider adapters retain transport, retry and response parsing.
Question/evidence serialization is data transformation, not permission for templates
to execute expressions. Embedding input text, voiced dialogue and deterministic
test-provider output are data rather than additional instruction templates. New
CG/audio instructions must be inventoried by their owners when implemented.

The migration preserves the old wording, wire schemas and shipped image policy.
Image normalization, character counting, dimensions, adapter scale, masks and
resource ceilings remain trusted code. The current default has 22 entries; the
original 18-entry and subsequent 21-entry artifacts remain available for historical replay.

## Pinned compatibility candidates

| Component | Pin / observed baseline | Result |
| --- | --- | --- |
| Self-hosted server | `v4.72.0`, Git commit `7efeac5eebe215b461fa0bc37369dc7f80d7752f` | Source/documented prompt API compatibility; not a deployed service qualification |
| Python SDK | `langfuse==4.15.0`, Git commit `5fcae099163513af026ed71dadf5bd85e8177158` | Resolves with the entire unchanged root lock; four isolated SDK behavior probes pass |
| SDK wheel | SHA-256 `3612197b162838a90f3e6f9d994758d1388db2664c5a5d0a4411da5988f823eb` | Download hash verified against version-specific PyPI metadata |
| Application | Python 3.12.13; OTel API/SDK/proto 1.43.0, instrumentation 0.64b0; httpx 0.28.1, pydantic 2.13.4, packaging 26.2, wrapt 2.2.2 | Existing application environment remains unchanged; Python 3.13/3.14 not exercised by this probe |
| Added only to probe environment | SDK's HTTP OTLP exporter 1.43.0 and backoff | No root dependency/lock changes and no enabled exporter |
| Latest SDK / rejected with current lock | 5.1.0 (and 4.16–4.18 require OTel >=1.45) | Resolver rejects SDK 5.1 + locked OTel 1.43. The broad pyproject range alone would permit an upgrade; that is not qualification of the installed stack |

The [upstream compatibility matrix](https://langfuse.com/docs/compatibility)
supports Python SDK v4 with server v4. This contract uses prompt APIs only.
Re-check source, wheel hashes, dependency resolution and transport probes when
either pin changes; production deployment must also pin web/worker image digests
and qualify actual server auth/availability. Do not deploy moving `latest` tags.
[SDK 4.15 metadata](https://pypi.org/pypi/langfuse/4.15.0/json),
[SDK 5.1 metadata](https://pypi.org/pypi/langfuse/5.1.0/json),
[server release](https://github.com/langfuse/langfuse/releases/tag/v4.72.0).

## Edition and authority matrix

| Feature at reviewed server version | Self-hosted OSS / Enterprise distinction | Deployment consequence |
| --- | --- | --- |
| Templates, numbered versions, labels and prompt APIs | Core features in OSS | Use Langfuse for authoring; label changes still require our release review |
| Organization-level roles | Core roles; finer project role overrides are Enterprise | Use separate organizations to isolate environments/authors in OSS |
| Project API key permissions | Available self-hosted; restrict runtime to prompt reads | Qualify actual deny-on-write with a real server before rollout |
| Protected deployment labels | Enterprise, not OSS | Never rely on them as the only deploy gate; ordinary write-enabled API keys can still promote protected labels |
| Instance-configured OAuth/OIDC sign-in | Supported by self-hosted configuration | Distinguish this from organization-managed SSO/administration under Enterprise |
| Organization-specific SSO management | Enterprise source under `web/src/ee/features/multi-tenant-sso` | Do not promise per-organization SSO controls in OSS |
| Audit log persistence/viewer | Enterprise; tagged server disables OSS persistence | Keep reviewed Git/release records; do not assume an OSS vendor audit trail |

Sources: [RBAC](https://langfuse.com/docs/administration/rbac),
[protected labels](https://langfuse.com/docs/prompt-management/features/prompt-version-control),
[self-hosted authentication](https://langfuse.com/self-hosting/security/authentication-and-sso),
[audit docs](https://langfuse.com/docs/administration/audit-logs), and tagged code:
[API label mutation authorization](https://github.com/langfuse/langfuse/blob/v4.72.0/web/src/features/prompts/server/utils/authorizeProtectedLabelMutation.ts),
[audit persistence gate](https://github.com/langfuse/langfuse/blob/v4.72.0/web/src/features/audit-logs/isAuditLogEnabled.ts).
The source/edition review is not a claim that these permissions have been live-tested.


## Implemented catalog migration (2026-11-01)

The provider, extraction, assistant and image defaults now resolve from
`src/flint_graph/prompts/prompts.lock`; adapters own serialization and provider
protocols. `tests/fixtures/prompts/legacy_renderings.json` was captured from
`b4b6729` before builder changes. Schemas, exact template bytes and configuration
have distinct hashes; migrations preserve existing historical version fields.
Image admission uses the scoped policy rather than an import-time TOML default.
See the [migration report](../reports/2026-11-01-langfuse-prompt-migration.md) and
[operator runbook](../runbooks/prompt-management.md). The compatibility matrix above
records the original contract probe; the report adds actual deployed-service proof.


The rebase included the scene-art builder from `133a551`; its one/two-character
renderings were captured before migration in `tests/fixtures/prompts/legacy_scene_art.json`.
Both text templates and typed negative/quality configuration now use the scoped
catalog. The new catalog retains the old complete bundle. Explicit lock overrides
missing current required entries fail readiness; historical run manifests remain
loadable independently of the current default inventory.
