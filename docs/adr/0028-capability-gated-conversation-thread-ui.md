# ADR 0028: Capability-gated conversation thread Ask

Status: accepted design for the first #73 UI slice; full parent acceptance remains open.

## Decision and alternatives

Build on the authoritative conversation/turn/run APIs, not browser-side history
concatenation or synthetic grouping of old standalone runs. A single Ask
dispatcher reads backend capabilities; delivered ledger support enables a thread
screen, absent/unavailable support retains the independent-question screen. A
separate independent-question view keeps historical standalone results readable.
Do not infer broad memory from ledger availability: advertise only delivered
prior-year scope, with explicit limitations and original/resolved question labels.

Extending the single-run form alone would preserve old UX but cannot express
ordered multi-turn state. Browser-only chat state would be easy to sketch but
would lose authorization, restart identity and bounded reference interpretation.
The server-backed approach is chosen despite additional async/state management.

## Interaction and visual direction

Subject: document-grounded research conversations for workspace users. Single
job: ask and revisit source-backed questions without losing thread context.
Preserve FlintGraph's indigo/white/slate identity: focus #4f46e5, ink #0f172a,
wash #f8fafc, paper #ffffff, evidence #047857 and caution #b45309. Display titles
use the local Segoe UI Variable Display/Segoe UI stack; body retains the existing
Inter/system stack; citation/data labels use the existing monospace utility face.
No font download, image generation, decorative hero or unrelated navigation redesign.

Desktop: narrow conversation sidebar beside a restrained, readable transcript;
mobile: explicit history disclosure above the transcript. User messages use a
quiet indigo-tinted bubble; assistant messages are open document-like text rather
than a wall of nested cards. The signature is a per-answer evidence receipt:
source count, interpreted question when applicable, and scoped expandable sources
and diagnostics. It encodes actual provenance rather than ornamental decoration.

One primary transcript scroll area; individual answers and expanded sources do
not scroll internally. Composer stays outside it and visible at the bottom.
Follow new content only while the reader is near the bottom; otherwise show
Jump to latest. Loading older/page content and opening evidence must not yank
the reader. Label controls, keep visible keyboard focus, honor reduced motion.
Recheck screenshots at 390px and desktop, with long content and unbroken titles.

Keyboard qualification (#101) keeps the primary transcript a named, focusable
region rather than a generic labelled div or a live log. Explicit history
selection focuses the loaded heading, including after mobile history closes;
passive saved-thread restoration does not move focus. New chat focuses the
composer without creating server work. Rename Save/Cancel returns focus to
Rename. Citation activation focuses that turn's programmatically focusable
evidence item; Tab then reaches its full-excerpt disclosure. Focus moves avoid
implicit scroll jumps, and existing citation scrolling honors reduced motion.
Automated axe violations and incomplete results are recorded separately; clean
automation is not a claim of assistive-technology or full WCAG certification.

## State, authority and recovery

Separate the dispatcher, sidebar, transcript/message evidence and API wrappers.
Workspace/selection request epochs and AbortControllers invalidate late results.
Workspace switching or revoked access clears old messages and aborts active work;
no previous-workspace content can reappear. Persist selected conversation ID per
workspace only; conversations/messages/answers remain server-authoritative.

Reopen/list/refresh are GET-only and never start inference. Send explicitly
creates a server turn and consumes its existing SSE endpoint. Use a stable UUID
idempotency key for a retryable accepted/lost-response attempt; do not turn a
network retry into a fresh submission. POST conflicts retain the typed question
and explain the active-turn policy. Conversation creation itself currently has
no idempotency API; no exactly-once empty-conversation creation promise follows.

Queued turns may be explicitly resumed or cancelled by members; viewers read
only. Running streams are request-bound. Stop/disconnect is not proof of a
terminal backend state or durable continuation: refresh authoritative state.
Never replay a completed run by creating another query. Show clarification,
abstention, failed/cancelled/running/queued and partly-supported states distinctly.
Keep provisional output untrusted; progress is shown until verified final text.

Each turn loads its own authorized provenance on demand. Prefix DOM citation IDs
with run identity so c1 in one answer cannot jump to another answer's c1. Render
untrusted model text as React text plus bounded citation controls, never HTML;
rich Markdown and unsafe links are not introduced. Rename follows member roles;
archival/purge/turn deletion are not invented in the UI.

## Ordered implementation and verification

1. Public API-wrapper regression for conversation list/create/reopen/turn/rename/
   queued-cancel, headers, AbortSignal, paging and unchanged retry key.
2. Browser tracer regression proving the new transcript/composer is absent before
   UI changes. Deliver dispatcher and ordered read-only reopening first.
3. Add explicit send/retry and queued recovery, then sidebar discovery/rename,
   per-turn evidence and bottom-aware scrolling in tested vertical slices.
4. Exercise external HTTP fixtures, not React internals: desktop/mobile, long
   transcript, repeated citation labels, malicious-looking text, paging, failures,
   unknown response retry, viewer/revocation and stale workspace/chat requests.
5. Real configured backend/model smoke on existing public or clearly synthetic
   data; inspect screenshots and read-only replay/usage. Preserve private corpus.
6. Frontend unit/type/build/browser gates and relevant backend gates; publish
   precise evidence and CI status before closing the narrow issue.

Full #73/#62/#74/#75/#82 acceptance, general natural-language memory, durable
request execution, retention/deletion and production accessibility qualification
remain separate. This is an intentional first thread UI, not a Claude/GPT feature
parity claim.
