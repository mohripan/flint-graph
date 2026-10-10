# ADR 0027: Bounded prior-year conversation interpretation

Status: accepted for #97; parent #62 remains incomplete.

## Decision

Use a deterministic interpretation policy, not free-form model rewriting or
concatenated chat history. This first memory slice recognizes a narrow English
prior/previous-year follow-up. It can replace exactly one explicit 1901..2099
year in the immediately previous resolved question. Preserve the original turn's
question and persist an inspectable resolved query. A self-contained new topic
remains independent. Unsupported elliptical/pronominal follow-ups clarify.

Only the immediately previous turn is considered: no searching backward across
failed or unrelated turns. Its run must be finalized, non-abstained, contain only
supported persisted claims with citations, and use the same active index and
server-owned execution-policy fingerprint. Revalidate exact tenant document /
active version / chunk hash and completed current-index coverage, with at most
eight distinct citations. A missing, replaced or deleted source invalidates the
interpretation context. Previous answer text never enters a prompt or evidence
pack; only the bounded question supplies reference scope.

The fingerprint includes configured provider/model identity, prompt-policy
versions, context/output limits, temperature and faithfulness thresholds. Missing
legacy attestation or changed settings fail closed. A later source change must
not silently resurrect old memory; recheck the referenced context before answer
generation. Fresh retrieval and per-turn citation, arithmetic and support checks
remain mandatory. This is not a hard guarantee about concurrent deletion after
the final authorization check; the existing source lifecycle boundary still applies.

Bound interpretation to one question of at most 1000 characters, one explicit
year and eight citations. Persist considered/omitted counts, prior turn/run IDs,
reason, policy and fingerprint, not an answer transcript or new source copy.
Interpretation makes zero additional model calls. Existing retrieval packing,
output limits and invocation accounting apply to the resolved query; parent-wide
reservations remain #82. No summary/cache or broad pronoun-memory claim follows.

Ambiguous/untrusted follow-ups finalize as an inspectable clarification with no
retrieval/model calls. Explicit zero expected calls may attest complete accounting;
unknown attempted usage must still remain incomplete. Other standalone behavior
and historical recordings are unchanged.

## Interfaces and verification plan

Policy seam: pure follow-up classification/rewrite and boundary cases. Service
seam: authorized turn/run/source revalidation and fingerprints. API seam:
original/resolved query visibility, fresh retrieval/generation/support query,
new-chat isolation, unknown/stale contexts, zero-dispatch clarification and replay.
Use distinct PostgreSQL fixtures and external provider fakes, not internal
orchestration mocks. Run fresh public-corpus prior-year turns with existing local
models, check exact cited answers and measure per-turn latency/usage.

Advertise bounded prior-year follow-ups separately from broad
`chained_conversations`, which stays false for this slice. UI #73, realistic
multi-turn suites #74, broader memory/retention #75 and atomic budgets #82 remain
open. Do not close #62 or claim durable request execution from this change.
