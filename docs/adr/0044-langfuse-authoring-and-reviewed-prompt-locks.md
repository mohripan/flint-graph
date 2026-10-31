# ADR 0044: Langfuse authoring and reviewed prompt locks

Date: 2026-11-01. Decision contract for #134 / M35; runtime integration is
**not delivered** by this ADR. Follow-on implementation is #135–#140.

## Context and alternatives

The creator selected Langfuse. Instructions currently live in Python builders;
image content settings live in `narrative/image_content_policy.toml`. The latter
contains negative conditioning tags and admission rules, not just prose. Current
prompt identity is inconsistent: the narrative assistant hashes its system/schema,
while answer/support/extraction paths mostly record hand-maintained versions.

| Option | Consequence | Decision |
| --- | --- | --- |
| Author in self-hosted Langfuse; export reviewed immutable bundles to the repository | Editable versions and labels, reproducible evaluation and offline operation; two explicit publication steps | Selected |
| Author in the repository and synchronize to Langfuse | Preserves Git-only editing but makes the selected authoring UI a mirror and creates ambiguous reverse edits | Rejected as the long-term workflow; existing files are initial import sources |
| Fetch the current Langfuse label on every call | Network dependency, unreviewed changes, mixed versions during jobs, unreliable offline replay | Rejected |

Langfuse is the authoring source of truth. A reviewed `prompts.lock` is the
deployment authority and contains the complete fallback templates/configuration,
not just their hashes. Local hard-coded/TOML copies cease being independently
editable authorities only when their specific migration lands. No current file
or setting is removed by this decision.

## Bundle and rendering contract

The version-1 JSON lock contains a default bundle digest, an allowlist of complete
approved bundles (including staged candidates), and entries with: logical name,
catalog version, kind (`prompt` or `policy`), text/chat type, Langfuse project/name,
numeric version, environment label, full template/messages, declared variable
JSON schema, approved model configuration, and SHA-256 identities for template,
variable/output schemas and configuration. It references the evaluation record
and reviewed source revision. It contains no credentials, tenant identifiers,
creator descriptions, evidence, conversations, compiled requests or model outputs.
JSON configuration is canonicalized with sorted keys and compact UTF-8 encoding;
array/message order is significant. Text hashes cover exact UTF-8 template bytes;
chat hashes cover canonical role/content arrays. Bundle identity covers all entry
identities and dependencies. No implicit Unicode/whitespace normalization.
Initial bounds: 256 KiB per template, 2 MiB per complete bundle and 1 MiB per
remote prompt response, enforced before SDK JSON decoding. Resolve only catalog
names from the validated lock. Schemas cannot fetch external references.

The typed renderer rejects missing, extra and wrong-type variables before model
dispatch. Values are substituted once locally; inserted template syntax is data.
Untrusted story/evidence/history stays in declared, delimited variables. Provider
differences, output schemas and shared rule fragments are explicit and versioned.
Initial bundles are flattened: unresolved prompt links, dynamic includes, arbitrary
message roles and unknown fields are rejected. A referenced rule cannot change
without changing the containing template identity.

The exact extraction inventory and current compatibility pins are in
[the migration contract](../architecture/prompt-catalog-inventory.md). #135 first
preserves model-visible bytes with golden fixtures. Existing builders without
strong delimiters must receive separately versioned/evaluated hardening; adding
delimiters cannot honestly be called byte-identical extraction. Current assistant
`prompt_sha256` retains its historical system/schema/version meaning; new template,
schema, config and bundle identities must not reinterpret or overwrite that field.

## Resolution, consistency and rollback

1. Startup validates and installs the packaged lock's default bundle into an immutable local map.
   A missing/corrupt packaged bundle fails readiness before admitting work. Tests
   and offline evaluation use only this map, with no Langfuse credential required.
2. Request/job admission snapshots the entire approved bundle plus effective
   allowlisted model configuration. Requests never call the remote SDK. Optional
   startup/background refresh uses a 60-second refresh TTL and one refresh per
   configured project; it never delays readiness or admission while a valid local
   bundle exists. Use the generated async prompt API with explicit request options
   (`max_retries: 0`, `timeout_in_seconds: 2`) inside a two-second total deadline.
   The high-level `get_prompt(max_retries=0)` still performs generated-client retries
   in SDK 4.15.0; do not mistake that argument for a total retry/deadline bound.
3. A remote result is eligible only if name, numeric version, type, schemas,
   template and authored config match a deployed approved-lock entry. Collect the
   environment-label results into a candidate map; activate it only when its entire
   identity matches one approved bundle, then swap atomically. A label move to a
   preapproved candidate can activate it without changing application code. Unknown
   versions, partial label changes and mismatches are quarantined; retain the
   current local approved map (initially the packaged default).
   TTL is a fetch interval, not permission to deploy arbitrary cached text. An outage
   may last indefinitely without changing the approved bundle. Do not use the SDK's
   bare string `fallback`: it discards config identity and still waits on a cold fetch.
4. The run's immutable snapshot governs every child, retry and repair. Persist its
   bundle reference and identities before dispatch; keep historical approved bundle
   artifacts so a restarted job can reload its original version. A missing historical
   bundle stops that job rather than substituting today's lock. No label lookup in a
   Temporal workflow; activities load authorized durable references.
5. A label move during a run affects no existing snapshot. Switching an approved
   deployment bundle is atomic, never entry-by-entry. Replay and cache keys include
   bundle/config/schema identity along with existing tenant/project/revision and
   authorization versions. Conversation policy fingerprints include the bundle.

Bounded counters identify offline/remote/missing/hash/config/type/schema/transport
fallback reasons by catalog operation, with no raw text, bodies, credentials or
unbounded remote names in logs/labels. #135 adds nullable identity fields beside
existing extraction versions and query metadata; historical unknowns stay unknown.
#140 applies the same identity contract to durable proposal jobs.
Record both the authored config hash and the actual effective provider config hash
after allowed operator overrides/ceilings; the latter is part of the immutable run
snapshot and cache identity. Credentials are excluded from both configurations.

Rollback restores the previous complete lock and returns the environment labels
to its recorded numeric-version map. New admissions use that lock; existing runs retain
their snapshots. Disabling remote refresh is an immediate operator rollback to
the deployed lock, without changing prompts or erasing run history.

## Authority and promotion

Prompt editing is a code-equivalent change path. Authors create versions and
staging labels in Langfuse. Release automation exports the complete candidate,
validates schemas/identities, runs golden, quality and adversarial checks, and opens
a focused reviewed lock change with evaluation provenance. Production publication
requires a maintainer review distinct from authorship, deploys the approved bundle,
then moves the production labels to that exact bundle's versions. Moving labels
cannot authorize an unreviewed bundle; activation of a preapproved candidate is
an accountable deployment action. Emergency rollback records actor, previous/new bundle,
reason and evaluation/incident reference through the same release boundary.

Runtime credentials are read-only and project-scoped; authoring and promotion keys
never enter API/worker runtime configuration. In OSS deployments use organization
separation for environment/author access and restrict release credentials outside
the application. Do not assume finer project roles or immutable vendor audit logs
exist in OSS. Repository review/release records are required even with Enterprise.
An ordinary write-enabled project API key can bypass protected-label user-role
restrictions in the pinned server; a protected UI label is not sufficient isolation.

Runtime configuration accepts only declared model IDs and bounded generation
settings beneath application/operator ceilings. It cannot supply endpoints, keys,
code, plugins, tools, shell commands, SQL, capability grants or approval policy.
Server authorization, cancellation, budgets, schema validation and approval checks
remain authoritative regardless of what a prompt says.

## Image policy and the creator's R-18 configuration

Inventory `image_content_policy.toml` as a typed policy entry, with a future
Langfuse config record (`negative`, `blocked`, schema version), a reviewed policy
digest and the same lock/promotion rules. It is not an LLM instruction granting
permission. Application code still validates the policy and refuses matching
descriptions before generation; negative tags still lead the constructed prompt.
Image results are not certified by a keyword list or negative conditioning.

The existing TOML and `FLINT_GRAPH_NARRATIVE_IMAGE_CONTENT_POLICY` remain active
until that migration is implemented with the image owner. Initial import preserves
the current normalized lists, order, bounds and configurable empty-list semantics.
Import repository defaults; publishing a custom operator override requires an
explicit source selection and privacy review, never automatic file discovery.
Any changed policy, including a relaxation, gets an explicit config diff/review.
Future jobs snapshot policy/config identities and fully constructed conditioning;
retries keep them. Invalid/missing remote config falls back to the complete approved
policy, never to an empty/default-permissive policy. Do not silently combine a local
override and a catalog policy; production activation must select one reviewed source.
Image/CG/voice implementation and current model pipelines are outside #134.

## Privacy, observability and qualification boundary

Use self-hosted Langfuse for templates and generic approved configuration only.
Compile locally. No tenant question, evidence, story, image reference, appearance,
history, generated answer or private evaluation case is uploaded for prompt
management. Disable SDK tracing explicitly (`tracing_enabled=False`), use no SDK
observation decorators/integrations and deny ingestion/media/score writes with the
runtime key. Never disable FlintGraph's global OpenTelemetry provider to achieve
this. PostgreSQL remains the run/usage ledger and the current gateway owns spans.
The runtime HTTP transport also allows only prompt-read GETs to the configured
origin and rejects other methods/paths and cross-origin redirects before sending.
A server refusing a write after receiving its body is not a privacy boundary.
Langfuse receives no application LLM-provider credentials for this feature.
#79 separately decides trace/evaluation export; this ADR does not authorize it.

Server 4.72.0 and Python SDK 4.15.0 are the compatibility candidates qualified by
source review, exact dependency resolution and an isolated real-SDK transport probe.
No server is deployed or production prompt resolver implemented here. #136/#137
must qualify actual self-hosted reads, key restrictions, cold/outage behavior,
label movement, rollback and privacy before activation. See
[the report](../reports/2026-11-01-langfuse-prompt-contract.md) and
[ADR 0029 addendum](../architecture/prompt-management-threat-model.md).
