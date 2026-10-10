# ADR 0018: fresh public financial black-box checks

Status: accepted for implementation; deployment activation remains operator-owned.

Extend the existing public-API capture seam instead of scoring yesterday's
recording or calling model providers directly. Every night/manual run creates
new queries, consumes SSE, inspects persisted retrieval/provenance and probes
foreign-workspace run/events/provenance access. Approved evidence comes only from
independently verified pinned FinQA excerpts; annotation/model-answer files are
never ingested. A dedicated workspace must exactly match the prepared manifest.

Only installed, digest-identifiable Ollama answer/support models are eligible.
Deterministic embeddings are permitted but explicitly do not qualify real
embedding quality. Hosted answer/support/embedding providers are refused. Local
compute is unpriced, not free or zero-cost. Reviewed model fingerprints are
explicit inputs, never silently updated. Corpus/version/index/model fingerprints
are rechecked before each query and at completion. API source bytes and deployed
Git revision are not independently attested; the manifest is a preparation trust
boundary, and client revision is not deployed revision.

Run at most 32 sequential queries, 180 seconds per query and 1,800 seconds total.
The default suite uses 12 questions, 90 seconds/query, 1,200 seconds overall and
a 100,000 observed-provider-token stop. The token stop is checked after a
completed query and can overshoot by one query; it is not a spend reservation.
Cancelled/incomplete provider calls may lack usage rollups. Reports distinguish
planned, attempted and captured counts and incomplete usage. Durable budget
reservations remain Milestone 18 work.

Literal concept/value/unit rubrics are source-checked independently of model
outputs; they are smoke assertions, not financial-reasoning judges. External
human review and accepted performance baselines remain pending. Do not bless a
failing capture or weaken the suite to make it pass. Rendered answers must have
supported claims and valid citations even when a usefulness threshold permits
some incorrect answers. Ambiguous/unanswerable cases must abstain.

Publish only redacted counts, fingerprints, metrics, case IDs and run UUIDs.
Never publish questions, answers, source quotations, provider payloads, URLs or
credentials. Retain GitHub artifacts for seven days. Raw source downloads and
local captures remain gitignored. The scheduled workflow is serialized, read-only
in GitHub permissions and opt-in; missing deployment configuration means skipped,
not demonstrated quality. Do not expose localhost or enable billable providers
to satisfy a missing deployment prerequisite.
