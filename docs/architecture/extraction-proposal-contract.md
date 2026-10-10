# Extraction Proposal Contract

## Purpose

FlintGraph extraction turns stored document chunks into staged, evidence-backed knowledge proposals. This contract defines the boundary between model output and canonical graph resolution.

The model proposes. FlintGraph verifies and persists. Canonical resolution decides.

## Inputs

Extraction consumes persisted `document_chunks` for one tenant and document version. Full chunk text stays in PostgreSQL and object storage. Temporal activity inputs and outputs should contain identifiers, counts, hashes, and artifact references rather than full source text.

Batch assembly is character-bounded. Each invocation receives a bounded list of chunks with stable chunk IDs and text.

## Provider Contract

The application depends on a provider-neutral asynchronous protocol. A provider returns structured extraction batches with:

- entities;
- relations;
- claims;
- evidence proposals;
- provider metadata when available.

Provider-specific message classes, response objects, token accounting structures, and SDK exceptions must not leak into domain models, persistence models, evaluation helpers, or Temporal workflow contracts.

## Batch Schema

An extraction batch uses batch-local IDs.

Entity proposal:

- local ID;
- surface name;
- entity type;
- aliases;
- confidence;
- attributes;
- evidence proposals.

Relation proposal:

- local ID;
- subject entity local ID;
- predicate;
- object entity local ID;
- confidence;
- evidence proposals.

Claim proposal:

- local ID;
- subject entity local ID, when available;
- predicate;
- object entity local ID or object string;
- confidence;
- evidence proposals.

Evidence proposal:

- chunk stable ID;
- exact quote;
- optional start hint.

## Validation

Schema validation rejects:

- duplicate local IDs;
- references to unknown local IDs;
- self-referential relations;
- empty or malformed predicates;
- invalid confidence values;
- collections over configured bounds;
- evidence references to chunks outside the invocation input.

Validation is provider-independent and deterministic.

## Evidence Resolution

Model-proposed offsets are never trusted. FlintGraph resolves evidence locally:

```text
chunk id + exact quote + optional start hint
    -> verify chunk belongs to invocation
    -> search stored chunk text
    -> reject absent quote
    -> accept unique occurrence
    -> accept repeated quote only with valid start hint
    -> calculate start/end offsets
    -> hash verified span
    -> derive stable evidence ID
```

Every accepted staged entity, relation, and claim must link to at least one verified evidence span.

## Stable IDs

Database UUIDs identify rows. Stable IDs identify extraction-contract records.

Stable IDs are derived from tenant/document-version context, normalized proposal content, and verified evidence IDs. Re-running the same extraction contract over the same accepted content should produce the same stable IDs.

New evidence IDs are `ev_v2_` plus SHA-256 over a canonical JSON array of immutable
document-version UUID, chunk ID, start/end offsets and quote hash. The pure resolver
requires that UUID; chunk/quote/offset tuples alone are not tenant-wide identities.
Existing `ev_` IDs, ready runs and their immutable manifests are not rewritten.
See [ADR 0017](../adr/0017-version-scoped-evidence-and-extraction-retries.md).

Proposal persistence uses a savepoint. Database failures roll back partial staged
rows before recording a failed invocation, preserving valid content artifacts.
Retries reuse failed contract-run rows and append invocation history; successful
retries become ready. Later failed provider retries do not downgrade ready evidence.

Document-local duplicate entities collapse by normalized name and entity type. Evidence links are unioned and confidence is retained conservatively.

## Persistence

PostgreSQL stores:

- `extraction_runs`: run-level status, schema/prompt/extractor/model versions, counts, quality metrics, warnings, errors, timestamps;
- `extraction_invocations`: per-provider-call request and response hashes, latency, character counts, token counts when available;
- `extraction_artifacts`: immutable manifest reference and hash;
- `evidence_spans`: verified chunk span offsets and hashes;
- `extracted_entities`, `extracted_relations`, `extracted_claims`: staged proposal records;
- evidence-link tables for staged records;
- `entity_resolution_candidates`: proposal match candidates and feature vectors.

Object storage stores a canonical content-addressed extraction manifest under a tenant and document-version scoped key.

Persistence is transactional. Partial provider output cannot leak into staged tables.

## Candidate Records

Candidate generation is non-destructive. It records possible matches between staged entities and canonical entities or other staged entities.

Candidate records include:

- source extracted entity;
- target candidate reference;
- feature vector;
- score;
- threshold outcome;
- reasons;
- status.

The current generator compares accepted staged entities from a ready extraction run
against active tenant canonical entities and one-way same-run staged entity pairs.
It stores only non-rejected candidates, leaves every row in `pending` status, and
rewrites pending rows for the run on retry. Reviewed rows are not mutated by
candidate regeneration.

Canonical graph mutation happens only in resolution services that consume candidates and record decisions.

## Staged Resolution

Each accepted extracted entity has independent resolution state:

- `resolution_status`;
- `resolved_canonical_entity_id`;
- `resolved_by_candidate_id`;
- `resolved_at`.

The staged resolver consumes ready extraction runs. Auto candidates may attach a
staged entity to an active canonical entity or group same-run staged duplicates.
Review candidates leave the staged entity unresolved for later review. Missing
usable candidates create a new canonical entity from the staged surface form.

Resolved staged relations and claims become canonical relationships only when
both endpoint extracted entities resolve to canonical entities. Relationship
support is rebuilt from staged provenance so retries are idempotent.

## Inspection

Milestone 05 persists the inspection data in PostgreSQL. Dedicated
tenant-scoped extraction inspection APIs are deferred to post-milestone API
hardening. Those APIs should allow local users and QA to:

- list extraction runs for a document version;
- inspect provider invocations and bounded errors;
- list staged entities, relations, claims, and their evidence;
- fetch verified evidence span context;
- list candidate records and score reasons.

Foreign tenant resources return 404.

## Quality Signals

Operational quality metrics may include:

- schema validity;
- evidence validity;
- reference integrity;
- accepted entity, relation, and claim counts;
- low-confidence rejection count;
- duplicate-collapse count;
- evidence coverage;
- extraction-density-derived score;
- bounded warnings.

These metrics are operational signals, not semantic-quality guarantees. Model selection requires labeled evaluation.
