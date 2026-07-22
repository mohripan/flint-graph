# Milestone 05 Provenance-Rich Extraction Design

## Summary

Milestone 05 replaces the current extraction-to-resolution bridge with staged, evidence-backed extraction proposals. The model produces provider-neutral structured output, FlintGraph validates and verifies it against stored chunks, and deterministic resolution decides what reaches the canonical graph.

This is Approach 2 from planning: staged extraction records become the direct input to canonical resolution. The current `entity_mentions` / `claims` bridge is superseded as the primary resolution path.

## Design Decisions

- Keep ingestion intake, parsing, chunking, job lifecycle, Temporal dispatch, PostgreSQL authority, and Neo4j projection.
- Allow breaking Milestone 04 extraction/graph API shapes where the cleaner design requires it.
- Add extraction runs, invocations, content-addressed manifests, evidence spans, staged entities, staged relations, staged claims, evidence links, and proposal candidate records.
- Require every accepted staged record to have at least one verified evidence span.
- Never trust model-proposed offsets or durable identifiers.
- Make candidate generation explainable and non-destructive.
- Make canonical resolution consume staged proposals directly.

## Documentation Outputs

Team-facing:

- `docs/milestones/05-provenance-rich-extraction.md`
- `docs/adr/0005-staged-extraction-proposals-before-canonical-resolution.md`
- `docs/architecture/extraction-proposal-contract.md`
- `docs/runbooks/provenance-extraction-developer.md`
- `docs/runbooks/provenance-extraction-qa-guide.md`

Private handoff:

- `notes/milestone-05/01-provenance-rich-extraction-plan.md`
- `notes/milestone-05/02-manual-testing-provenance-extraction.md`
- `notes/milestone-05/03-code-flow-provenance-extraction.md`

## Approval

Approved by the project owner in conversation on 2026-07-13.
