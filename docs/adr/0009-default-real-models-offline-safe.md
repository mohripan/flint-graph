# ADR 0009: Real models by default, offline-safe via env-aware provider defaults

## Status

Accepted. Implemented in Milestone 09.

## Context

Through Milestone 08 every model-backed step defaults to a deterministic provider:
`embedding_provider="deterministic"`, `query_answer_provider="deterministic"`,
`query_support_provider="deterministic"`, and deterministic classifier/reranker. These are
smoke-test stubs — the deterministic answer generator returns the first sentence of the top
context record and cites every record. The orchestration, faithfulness, and provenance layers
are real; the models are not. Out of the box a user receives a non-answer.

To be usable, the default runtime must produce a genuine grounded answer. But the codebase has
a load-bearing invariant established across Milestones 05–08: the deterministic providers exist
so the entire test suite (and the deterministic eval fixtures) run without any live model
service. Flipping the global default to a real model would break offline, hermetic testing and
force every contributor to hold API credentials.

Two further facts shape the decision:

- **Anthropic exposes no embeddings API.** Real answer generation (and the LLM support judge)
  can be Claude; real embeddings cannot. Embeddings must come from an OpenAI-compatible
  endpoint or a local model. The two concerns are independent.
- **Changing the embedding model is not free.** Chunk embeddings are keyed to
  `(chunk_hash, retrieval_index_version)`. A real embedding model changes dimensions and
  vectors, which requires a new retrieval index version and a backfill (Milestone 06).

## Decision

Make real models the default for real environments while keeping the test environment
deterministic, via **environment-aware provider defaults**.

1. **Env-aware default resolution.** When provider settings are left unset, resolve them by
   `env`: `test` → deterministic across the board; `local` / `staging` / `production` → real
   providers (answer and support → Anthropic/Claude; embeddings → the configured real model).
   Any explicit setting always wins over the resolver.

2. **Anthropic behind existing protocols.** Add an `AnthropicAnswerGenerator`
   (implementing `AnswerGenerator` and the streaming variant) and an `AnthropicSupportChecker`
   (implementing `SupportChecker`) at the infrastructure edge (`infrastructure/anthropic.py`),
   selected through the existing `create_answer_generator` / `create_support_checker`
   factories. The adapters use structured output to emit the same citation-only draft shape
   the Ollama adapter targets, stream via `messages.stream(...)`, and return only
   provider-neutral contracts. Generation and verification stay separated — the answer model
   never certifies its own grounding.

3. **Real embeddings via the existing adapters.** Default the non-test `embedding_provider` to
   a real model (OpenAI-compatible or local Ollama), reusing the existing embedding adapters.
   Switching embedding models is performed through the retrieval index-version + backfill path,
   never in place.

4. **Fail fast on missing credentials.** Selecting a real provider without its key raises at
   startup with a clear message (mirroring the existing `openai_compatible` validation).

## Consequences

- The default local/staging/production runtime produces genuine, faithfulness-checked,
  citation-bearing answers.
- The test suite and the offline CI eval gate remain network-free and hermetic — the
  deterministic invariant is preserved, not weakened.
- Answer generation and support checking can each be pointed at deterministic, Ollama, or
  Anthropic providers independently, so cost/quality can be tuned per stage.
- Real answer quality now depends on external services and credentials; this raises the
  importance of the evaluation platform (ADR 0010) to detect regressions.
- The LLM support judge roughly doubles model calls per query; it is independently
  configurable so cost-sensitive deployments can fall back to the deterministic checker.
- Adopting a real embedding model incurs a one-time index-version bump and backfill.

## Alternatives considered

### A single hard default of real models

Simplest to state, but it breaks offline/hermetic testing and forces every contributor to hold
credentials — regressing a load-bearing invariant. Rejected in favor of env-aware defaults.

### Keep deterministic as the default and document how to opt into real models

Zero risk to tests, but it leaves the shipped product as a non-answering demo — the exact gap
this milestone exists to close. Rejected.

### Route embeddings through Anthropic too

Not possible — Anthropic has no embeddings API. Embeddings must use an OpenAI-compatible or
local model regardless.

### Let the answer model self-report support

Rejected already in ADR 0008 and unchanged here: a model grading its own faithfulness is
unreliable and unauditable. Support checking stays a separate provider.
