# Milestone 05: Provenance-rich extraction proposals

## Status

In progress. The provider-neutral proposal contract, evidence resolver,
provenance persistence schema, transactional staged-record persistence,
non-destructive staged candidate generation, and staged canonical resolver are
implemented. Extraction workflow wiring and inspection APIs are still pending.

## Goal

Transform immutable document chunks into versioned, inspectable, evidence-backed knowledge proposals before anything is allowed to affect the canonical graph.

Target flow:

```text
stored chunks
    -> character-bounded extraction batches
    -> provider-neutral structured extraction
    -> schema and local-reference validation
    -> verbatim evidence resolution
    -> confidence filtering and duplicate collapse
    -> content-addressed extraction manifest
    -> transactional staged-record persistence
    -> proposal candidate generation
    -> deterministic canonical resolution
    -> PostgreSQL graph state
    -> Neo4j projection
```

The model proposes structured records. AtlasRAG validates, verifies evidence, assigns stable IDs, persists staged records, and only then runs deterministic candidate generation and resolution. A model never writes canonical entities, canonical relationships, merge decisions, or Neo4j records directly.

## Scope

Milestone 05 may break the current Milestone 04 extraction and graph API shape where needed. The project is still early, so the priority is the cleaner long-term boundary rather than preserving a transitional `entity_mentions` / `claims` bridge.

Preserved:

- tenant intake, document versions, ingestion jobs, outbox, and Temporal dispatch;
- immutable raw objects, normalized artifacts, chunk manifests, and queryable chunks;
- PostgreSQL as the system of record;
- Neo4j as an idempotent, rebuildable projection;
- canonical entities, aliases, reviewable decisions, soft merges, and unmerge where still valid.

Superseded:

- the simple extraction schema that only emits entity names and claim triples;
- `entity_mentions` and `claims` as the primary resolution input;
- single-row extraction artifact provenance as the only inspection surface;
- candidate generation that starts from pending mentions instead of staged extraction proposals.

## Provider Boundary

Introduce a narrow asynchronous extraction protocol that returns provider-neutral structured batches. The application, domain, persistence, evaluation, and Temporal contracts must not import provider-specific request or response classes.

Required implementations:

- a deterministic extraction model for offline contract, persistence, and workflow tests;
- a production adapter at the infrastructure edge.

The deterministic backend is intentionally weak semantically. It proves workflow behavior, validation, provenance, retries, and inspection without external API calls.

## Proposal Schema

One extraction batch contains:

- entities with batch-local IDs, type, aliases, confidence, attributes, and evidence proposals;
- directed relations with subject and object entity references;
- atomic claims with optional entity subject/object references and optional object string;
- evidence proposals containing a chunk stable ID, exact quote, and optional start hint.

Pydantic validation rejects:

- duplicate local IDs;
- unknown local references;
- self-referential relations;
- malformed predicates;
- invalid confidence values;
- unbounded output collections;
- evidence proposals that do not reference chunks in the current invocation input.

Batch-local references are deliberate. A provider only reasons over the chunks supplied in that invocation. Cross-batch and cross-document identity belongs to deterministic candidate generation and canonical resolution.

## Evidence Trust Boundary

The model cannot author trusted offsets. For every evidence proposal, AtlasRAG:

1. verifies that the referenced chunk belongs to the current extraction input;
2. searches the stored chunk text for the exact quote;
3. rejects absent quotes;
4. accepts a unique occurrence directly;
5. accepts a repeated quote only when `start_hint` identifies a real occurrence;
6. calculates start/end offsets locally;
7. hashes the verified span locally;
8. derives a stable evidence ID from chunk identity and verified location.

Every accepted staged entity, relation, and claim must retain at least one verified evidence span. This creates a deterministic chain from knowledge proposal to evidence span, chunk, document version, and immutable source artifact.

## Persistence Model

Add a new PostgreSQL migration, expected as `0006_provenance_extraction`, with:

- `extraction_runs`;
- `extraction_invocations`;
- `extraction_artifacts`;
- `evidence_spans`;
- `extracted_entities`;
- `extracted_relations`;
- `extracted_claims`;
- evidence-link tables for entities, relations, and claims;
- `entity_resolution_candidates`.

An extraction run records schema, prompt, extractor, and model versions; input and output counts; quality metrics; bounded warnings and errors; and timestamps. Each invocation records request/response hashes, latency, character counts, and token counts when the provider exposes them.

The canonical extraction manifest is content-addressed and stored in object storage. The exact key format is defined in the extraction proposal contract, but it must include tenant and document-version identity and the manifest hash.

The run, invocations, evidence spans, staged records, evidence links, and manifest artifact row persist transactionally. Retries reuse a ready run and immutable artifact rather than producing duplicate active staged records.

## Candidate Generation And Resolution

Candidate generation operates on staged extracted entities, not raw model output and not the old mention bridge.

Candidates include:

- source extracted entity;
- candidate target canonical entity or extracted entity;
- normalized name and alias equality features;
- character-sequence similarity;
- token Jaccard overlap;
- acronym agreement;
- entity-type compatibility;
- score, threshold outcome, reasons, and status.

Candidate generation creates reviewable proposal records. It does not merge by itself.

The implemented Phase 5 generator is deliberately bounded and deterministic for
early corpora. For a ready extraction run it loads accepted staged entities,
compares them with active tenant canonical entities and one-way same-run staged
entity pairs, persists non-rejected candidates with feature vectors and reasons,
and rewrites pending rows during retries. It does not apply auto decisions or
change canonical graph state.

Canonical resolution consumes ready staged records and candidates. Auto decisions are deterministic and recorded. Ambiguous candidates remain pending for review. Rejected extraction proposals do not leak into canonical graph state.

The implemented Phase 6 resolver records resolution state directly on
`extracted_entities`. Auto canonical candidates attach staged entities to active
canonical entities. Auto same-run extracted-entity candidates collapse staged
duplicates into one canonical entity. Staged entities with only review candidates
remain unresolved in `review` state. Entities with no usable candidate create new
canonical entities. The Temporal resolution activity drains both the legacy
mention path and the staged path during the transition.

Resolved staged relations and entity-object claims are folded into
`entity_relationships` by recomputing staged provenance for the tenant, rather
than incrementing counters on every retry. This prevents staged relationship
support inflation.

## Failure And Retry Behavior

- Provider timeout or validation failure records a bounded run error and fails the extraction activity.
- Evidence verification failure rejects only the affected proposal when other valid proposals remain.
- A run with no accepted staged records can still be inspectable and failed or ready depending on configuration.
- A cancelled ingestion job marks unfinished extraction runs failed with an explicit `cancelled` error code.
- A ready run and artifact satisfy repeated extraction activity execution.
- Partial provider output cannot leak into staged tables because persistence is transactional.
- The document version is not activated until required processing and extraction gates succeed.

## Exit Criteria

- Provider-neutral extraction contracts are versioned.
- Provider adapters are isolated at the infrastructure edge.
- Every accepted staged entity, relation, and claim has verified evidence.
- Model-proposed offsets and identifiers are never trusted as durable identifiers.
- Extraction runs, invocations, staged records, evidence spans, and candidates are queryable.
- Staged records persist transactionally and retry idempotently.
- Candidate generation is explainable and non-destructive.
- Canonical resolution consumes staged proposals directly.
- Tenant-scoped inspection APIs return 404 for foreign resources.
- Existing ingestion, chunking, job lifecycle, canonical graph, and Neo4j projection invariants still hold after the refactor.
- Migration rendering, linting, strict typing, tests, package build, and Docker Compose validation pass.

## Known Risks

- This milestone intentionally changes a working but premature design, so graph API and test churn is expected.
- Migration strategy must decide whether to preserve old local development data or treat Milestone 04 graph data as disposable.
- Strict evidence requirements can reduce recall when a provider paraphrases instead of quoting exactly.
- Relationship support recomputation should be addressed while claims/relations are refactored, otherwise Milestone 04's support-count inflation risk may survive.
