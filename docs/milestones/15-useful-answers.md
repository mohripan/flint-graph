# Milestone 15: useful answers and explainable failures

## Financial scope clarification

[Issue #60](https://github.com/mohripan/flint-graph/issues/60) returns an inspectable
clarification for bare financial-value questions spanning multiple searchable
documents. Answer/support calls are skipped; the run completes abstained without
claims/citations and the frontend asks the user to narrow the question. Named,
scoped and other-language semantic ambiguity are not fully solved. Rejected drafts
remain in audit and evaluation metrics, and nightly thresholds are unchanged.
See [ADR 0021](../adr/0021-clarifying-bare-financial-values.md) and the
[verification report](../reports/2026-10-10-financial-scope-clarification.md).

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

## Streaming setup transaction

[Issue #26](https://github.com/mohripan/flint-graph/issues/26) releases the request
authentication/setup transaction before returning the SSE body. Previously its
`last_login_at` update held the user's row lock during model generation, causing
other requests by that principal to wait. Run/index/filter snapshots and tenant
authorization are completed first; execution uses its existing owned sessions.
A real PostgreSQL test pauses answer generation and requires simultaneous status
inspection to succeed while the provider remains paused. This does not make
query execution durable; disconnect/replay behavior is unchanged.

## Document-version-scoped chunk identity

[Issue #28](https://github.com/mohripan/flint-graph/issues/28) fixes candidate
collisions and cross-document fusion when different documents both contain
`chunk-000001`. New candidate IDs include the document version; source/citation
references include document, immutable version and local chunk name. The public
API regression retrieves same-named chunks from two active documents, requires
successful execution and verifies distinct persisted identities. Existing stored
query/citation records retain their original identities and remain readable.

## Versioned grounded answer instructions

[Issue #29](https://github.com/mohripan/flint-graph/issues/29) shares explicit,
versioned answer/support rules between Ollama and Anthropic. Focused answers
must address the requested attribute, cite every supporting premise for
multi-record claims, and signal insufficient context rather than cite absence
commentary as an answer. Context remains untrusted evidence, not instructions.
Adapter metadata identifies `grounded-answer-v2` and `grounded-support-v2`.
Support thresholds and offline providers are unchanged. Prompt rules guide models;
they do not mechanically prove completeness or replace the M20 coverage contract.

[Issue #30](https://github.com/mohripan/flint-graph/issues/30) further separates
per-claim entailment from whole-question completeness (`grounded-support-v3`).
Ollama's request-specific schema constrains the number of judgements and allowed
claim indices. Both adapters fail closed on missing/duplicate judgements.
A narrow English policy rejects context-insufficiency commentary even if the
model approves it; explicit negative source facts remain eligible. This guard is
not a multilingual semantic coverage checker. Rejected claims remain inspectable.

The configured hosted default `claude-opus-4-8` is listed as available in
[Anthropic's model documentation](https://platform.claude.com/docs/en/models/opus-4-8/overview)
(checked 2026-10-10); this is not a live credential/account/request validation.
No hosted calls or automatic model migration were performed. The real end-to-end
answer rehearsals used the installed local Ollama model.

## Canonical inline and legacy citation rendering

[Issue #33](https://github.com/mohripan/flint-graph/issues/33) repairs reserved
inline citation/context markers before support checking and renders both legacy
and structured drafts from supported repaired claims. Unknown inline `c999`
references are dropped and recorded; known inline references do not duplicate
rendered markers. Ordinary factual parentheses remain intact. Legacy drafts with
inline citations use those references rather than unused citation-array entries;
drafts without inline markers can still use the declared citation array.
The original unverified legacy text is never the final rendering source.

## Complete search-readiness accounting

[#66](https://github.com/mohripan/flint-graph/issues/66) separates authoritative
workspace/active-index coverage totals from the bounded recent-document preview.
Older active searchable content is not hidden by newer pending/failed attempts.
Completed coverage requires an active source version, matching retrieval filters;
deleted/superseded sources, other indexes and foreign tenants do not contribute.
The preview selects the latest visible version per document before limiting rows.
The live 100-document financial workspace now shows 100 searchable versions with
25 preview rows; see [the readiness report](../reports/2026-10-10-complete-search-readiness.md).

## Bounded explicit multi-source retrieval

[#59](https://github.com/mohripan/flint-graph/issues/59) adds inspectable syntactic
retrieval clauses for two/three explicit named sources without increasing the
parent candidate allowance. The strict public Devon/Philip Morris cross-report
case now returns both supported figures and exact required sources. A first live
failure exposed source-attribution display words dominating lexical ranking;
only that narrow suffix is omitted from derived retrieval queries. Original
answer intent, scope and evidence/support gates remain unchanged. See
[ADR 0022](../adr/0022-bounded-coordinated-source-retrieval.md) and
[the delivery report](../reports/2026-10-10-coordinated-source-retrieval.md).
The final nightly gate meets its unchanged 0.8 useful-answer threshold, but two
individual cases still fail (#70/#71); this is not full release qualification.
