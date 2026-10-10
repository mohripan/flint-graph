# ADR 0025: Explicit Ollama query context capacity

Status: accepted. Tracking: #95; exact tokenizer admission and memory budgets
remain #75/#82.

## Evidence and alternatives

After a host service restart, the installed model loaded with a 4096-token
context. Earlier successful answers reported 5058/5265 input tokens. The adapter
omitted a context option. Invalid structured output was observed after restart;
the context mismatch alone does not prove its cause.

Relying on the host's `OLLAMA_CONTEXT_LENGTH` is simple but leaves application
behavior dependent on a separately launched service. Shrinking retrieval packing
would discard evidence and change the fixed workload. Instead, set a bounded
per-request context explicitly while preserving packing, prompts, output limits,
models and support/citation validation.

## Decision

`FLINT_GRAPH_QUERY_OLLAMA_CONTEXT_TOKENS` defaults to 8192, bounded to
2048..131072. Normal and streaming answer generation and nonempty support checks
send it as `options.num_ctx`. `num_predict` remains the configured output limit.
Extraction and embeddings are unchanged.

When either query provider is Ollama, reject settings whose context is less than
the packed-context estimate plus output limit plus a 2048-token prompt-overhead
reserve. This detects obvious configuration mismatches, not exact tokenizer
overflow: source estimates, query text, support claims and model templates can
vary. Do not claim a hard admission guarantee or silently relax output parsing.
Other providers retain their existing settings contract.

The operator must check the model's supported context and available memory.
Larger windows can increase memory use/offloading and latency. A configured
request is not proof that a server honored it: verify effective capacity using
`ollama ps` or `/api/ps` during live qualification. No hardware purchase, model
download or paid provider is needed for this slice.

Official API contract: [Ollama FAQ](https://docs.ollama.com/faq).
Memory/capacity guidance: [Ollama context length](https://docs.ollama.com/context-length).

## Verification boundary

Factory-to-HTTP regressions cover answer, stream and support requests. Settings
tests reject undersized/out-of-range windows without restricting deterministic
providers. Fresh public-corpus runs use the same model digest and unchanged
rubric/policy; reports disclose the new context configuration alongside model
fingerprints. The existing nightly model fingerprint attests role/model/digest,
not every generation parameter. Historic failed captures remain failed.
