# Milestone 15: useful answers and explainable failures

Status: in progress. Tracking: [issue #1](https://github.com/mohripan/flint-graph/issues/1).
See the [roadmap](../ROADMAP.md) for the complete acceptance criteria.

## Verified claim policy

[Issue #10](https://github.com/mohripan/flint-graph/issues/10) fixes publication of
partially supported draft statements. Final verified output retains only claims
with a `supported` decision; partially supported and unsupported decisions remain
inspectable in the faithfulness report and persisted claim records. Their
citations are omitted from final output when no retained claim uses them.

An answer with zero supported claims abstains even if the configured minimum
supported-claim ratio is zero. Mixed drafts may retain fully supported facts if
the existing ratio policy passes. This is claim filtering, not yet the planned
question-coverage model for partial answers in Milestone 20.

Regression tests cover a correct headquarters claim alongside an office claim
with an unevidenced date/profitability, and zero-threshold abstention. Provider
support decisions are still the verification boundary; a deterministic lexical
checker is an offline fixture, not proof of production semantic accuracy.

## Offline OIDC integration harness

[Issue #11](https://github.com/mohripan/flint-graph/issues/11) makes the shared
OIDC fixture explicitly select deterministic extraction, embeddings, answers,
and support checking. It retains local OIDC behavior without requiring hosted
credentials or a developer `.env`. Production provider defaults are unchanged.
The original complete suite had 17 credential-validation failures in this
fixture; explicitly selecting offline providers resolves those failures.

## Document-scoped queries

[Issue #12](https://github.com/mohripan/flint-graph/issues/12) implements query
filters for `document_id`, `document_version_id`, and `chunk_id`. Document/version
IDs must be UUID strings; chunk IDs must be nonempty strings of at most 100
characters. Unsupported query filters return 422. The primitive retrieval APIs
retain their separate existing filter contract.

Lexical/vector search receives the restrictions, and returned chunks are checked
again before candidate creation. Out-of-scope hits cannot reach an answer even
when a projection returns them. Graph relationship summaries may combine sources,
so filtered queries currently use only lexical/vector evidence; graph retrieval
returns no relationships until source-scoped relationship evidence is supported.
Unfiltered graph behavior is unchanged. A scoped query without evidence abstains.

## Parallel retrieval sessions

[Issue #13](https://github.com/mohripan/flint-graph/issues/13) gives each API
retrieval task its own read session. The execution session alone writes run state,
candidates, and events after gathering results. Independent network retrieval
remains concurrent, and one retriever ending its read transaction cannot roll
back another retriever or the query's event ledger.

The application graph accepts an optional `retrieval_session_factory`. Callers
using independent read sessions must commit source/setup records before running
retrieval. The graph commits pending run state and `retrieval.started` before
opening those read sessions. Existing transactional service tests may omit the factory to read their
uncommitted fixtures; production API execution always supplies it.

Query API regressions can additionally run against PostgreSQL by setting
`FLINT_GRAPH_PG_INTEGRATION=1`, with optional `FLINT_GRAPH_PG_TEST_URL`. Each
fixture owns a unique schema which it removes afterward, avoiding production
table mutation. Offline SQLite remains the default test backend.

## Effective model reporting

[Issue #14](https://github.com/mohripan/flint-graph/issues/14) shares model
selection between provider factories and system readiness. Anthropic reports
`anthropic_answer_model`/`anthropic_support_model`; Ollama reports the query model
settings; deterministic adapters report `deterministic`. Setup therefore shows
the selected model rather than an unrelated Ollama default. Credentials are
never included in this response.

The example local configuration and Compose select deterministic query providers
explicitly. That mode produces fixture answers and lexical support judgments.
To evaluate actual model quality, select Ollama with installed model names or a
hosted provider with valid credentials; inspect `/v1/system-readiness` for the
effective selection. A missing local model, an invalid hosted model name, and a
faithfulness abstention require different remedies.

## Provider failure diagnostics

[Issue #15](https://github.com/mohripan/flint-graph/issues/15) distinguishes
`answer_generation_failed` from `support_check_failed`. Context loading and
answer persistence also carry separate failure codes. Failed runs persist a
`query.failed` event, an actionable safe message, the stage, and an exception type.
Raw provider exception text is excluded from answer-stage events and inspection
details, since it may contain credentials or provider payloads.

These codes identify the failing operation, not the underlying network or model
diagnosis. Use the run's trace and effective provider settings for that diagnosis;
an outage must not be represented as a successful evidence abstention.

## Citation IDs from real models

[Issue #16](https://github.com/mohripan/flint-graph/issues/16) was reproduced
with a live installed Ollama model: a correct Berlin answer cited `ctx-0001`
instead of `c1`, so repair removed all evidence and the run abstained. Exact,
unambiguous context IDs from the current pack now normalize to canonical citation
IDs. Unknown or ambiguous aliases are rejected; repair never searches another
pack or invents source evidence. Support verification still runs afterward.

Ollama answer schemas enumerate actual pack citation IDs, and Ollama/Anthropic
prompts explicitly distinguish citation IDs from context IDs. Offline regressions
cover alias normalization and ambiguity. An opt-in live query API smoke uses real
Ollama answer/support calls with controlled retrieval fixtures:

```powershell
$env:FLINT_GRAPH_OLLAMA_INTEGRATION = '1'
$env:FLINT_GRAPH_OLLAMA_TEST_MODEL = '<installed model name>'
uv run pytest tests/integration/test_query_api.py -q -k live_ollama
```

The live smoke passed with the locally installed model after initially abstaining.
It validates real generation/support plus API/provenance, not full upload,
extraction, and projection operation; that end-to-end gate remains outstanding.

## Provider telemetry failure path

[Issue #17](https://github.com/mohripan/flint-graph/issues/17) removes the
unregistered model attribute from the provider-error counter. Failed calls now
preserve the original provider exception rather than replacing it with an
instrument-attribute validation error. Duration traces/metrics retain model
information according to their existing registry contracts.

## Ask outcome handling

[Issue #18](https://github.com/mohripan/flint-graph/issues/18) makes Ask inspect
persisted status/diagnostics after the stream closes. It shows the safe provider
failure message, distinguishes cancellation, and flags a stream ending while a
run is still queued/running. Only completed runs enter the normal final-answer
path. Structured provisional model JSON remains progress activity; it is not
displayed as verified answer prose.

Frontend outcome tests cover failure/cancellation/incomplete/completed states.
Browser QA with controlled network responses verifies the support-error message
and diagnostics, cancelled and unfinished outcomes, verified Berlin output, and
absence of raw draft JSON. `npm test`, `npm run typecheck`, and `npm run build`
passed. Real incremental verified sections remain Milestone 20 work.

## Responsive shell

[Issue #24](https://github.com/mohripan/flint-graph/issues/24) repairs a pre-existing
narrow-screen shell overflow. Header controls wrap, page navigation becomes a
horizontal row below the medium breakpoint, and Ask gets a full-width scrollable
panel. Desktop branding/layout remain in place. Workspace and page selectors
also have accessible names.

`npm run test:browser` runs an optional pinned agent-browser check against a local
Vite server, with mocked public API responses. It checks document overflow,
navigation clipping and Ask input width at 390px and 1280px. The check failed
against the old shell (100px input, clipped Switch workspace) and passes after
the repair. It does not test backend availability or answer quality. Start
`npm run dev` first; the check creates and closes its own browser session.

## Multiline plain-text ingestion

The first real Compose rehearsal found that ordinary multiline text ending in a
newline could produce no parser elements and fail ingestion before indexing.
[Issue #25](https://github.com/mohripan/flint-graph/issues/25) repairs paragraph
segmentation for LF/CRLF and trailing whitespace. Source offsets end at the exact
trimmed paragraph, preserving decoded-text evidence coordinates. Regressions cover
the pure parser and its real bounded subprocess. Historical failed attempts remain
inspectable; a retry must create a new immutable document version/ingestion attempt.
