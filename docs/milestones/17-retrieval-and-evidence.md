# Milestone 17: retrieval and authoritative evidence

Status: in progress. Native PostgreSQL vector search, cutover and benchmarks
are not delivered by this increment. Existing embeddings remain JSON in
PostgreSQL; Neo4j serves vector retrieval and OpenSearch lexical retrieval.

## Full chunk evidence

[Issue #32](https://github.com/mohripan/flint-graph/issues/32) replaces answering
from versioned search previews with full immutable PostgreSQL `DocumentChunk`
text. The packer batch-loads matching tenant/version/local chunk identities,
joins active non-deleted documents, verifies chunk hashes and rejects contradictory
document identities. Missing/stale versioned evidence never falls back to a preview.
Canonical page/heading/source-element/offset metadata travels with packed citations.

Candidate previews remain bounded at 2000 characters for ranking; vector records
currently preview 200 characters. The answer context is independently rehydrated,
so a late fact in a chunk can be present even when the search preview omits it.
Records over 4000 characters, over the configured budget/count, or unavailable
are skipped explicitly with persisted reason counts. There is no silent truncation
of an evidence record. Context token estimates still count whitespace words, not
actual model tokens; this is not complete context-window accounting.

Internal legacy unversioned candidates retain clearly labeled preview behavior;
public chunk retrievers always supply immutable identities. Graph records still
use the existing preview/triple path and need original evidence-span improvements.
This is not whole-corpus CAG, adjacent-section reads, or an agent harness.

Regression evidence includes facts beyond character 200, missing/stale hashes,
foreign/deleted documents, source-ID-only references, oversized chunks and budgets.
API fixtures now seed canonical chunks as the real ingestion pipeline does, rather
than assuming an external search response alone is evidence.

Real Compose rehearsal at `fe8423b` uploaded a 633-character memo through the
public intake API, waited for ingestion/indexing, and asked its codename using a
document-scoped query. The full PostgreSQL context contained the late `Quartz`
fact beyond character 200; the local Ollama answer cited it successfully.
The original global index remained active alongside the separate evaluation
workspace's tenant index. This is a focused smoke, not a native-vector benchmark.
