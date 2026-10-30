# ADR 0038: Conversational authoring through reviewed proposals

Date: 2026-10-30. Status: accepted by the user for implementation after #124
(tracking #168).
Supersedes only the "chat-first product" rejection in ADR 0035's consequences.
This ADR records intent, not delivered behavior.

## Context

ADR 0035 chose authored narrative games with portable Godot export and rejected a
chat-first product as the core workflow, on the grounds that it would not validate
the developer workflow or the promise of a usable export. M30/M31 have since
delivered that foundation: a validated story package, immutable revisions with
recoverable conflicts, a manual editor, isolated playtest and qualified releases.

On 2026-10-30 the user stated that creating a game by chatting with a model is the
point of the product: a creator should be able to describe what they want and have
the model create and connect scenes, while the editor remains available. The user
chose a switchable provider interface, defaulting to a local Ollama model so
development has no per-call cost.

## Decision

1. Conversation is the primary creator workflow. The Studio gains a project-scoped
   assistant whose turns may return a structured proposal of story edits.
2. ADR 0035/0036 invariants are unchanged. Proposals target an immutable base
   revision, are validated by the same rules as manual saves and become canon only
   through explicit creator acceptance, which creates a normal append-only
   revision (rebased when untouched, otherwise the existing conflict revision).
   Model output is data, not instructions. Manual authoring, playtest, releases and
   exported games work without any provider; exports contain no prompts or threads.
3. Proposals are bounded edit operations against the story, not regenerated whole
   stories, so large projects stay reviewable and unrelated text is untouched.
4. Model calls run as bounded Temporal jobs on a separate task queue, with
   ID-only payloads and the ADR 0037 ownership/recovery pattern. They never run
   inside an API request.
5. Providers sit behind one narrative-assistant port: Ollama (development default),
   Anthropic (explicit opt-in) and deterministic recordings (tests). No provider is
   selected implicitly outside `env=test`.

## Alternatives and consequences

Keeping chat as a later add-on would leave the product's main promise unvalidated.
Letting the model write whole stories or edit the draft directly would make review,
conflicts and large projects unmanageable and would blur canon with suggestions.
Request-bound streaming is simpler but loses turns on reload and contradicts the
durable-authoring rule in the product doc.

This re-sequences a usable subset of #150 and #126 ahead of the #134/#135 prompt
catalog. Prompt templates live in code with their SHA-256 recorded per proposal,
so the later catalog can adopt them without changing stored data. Small local
models produce weaker prose and more invalid proposals; strict validation, bounded
repair attempts and explicit review contain that risk rather than hiding it.

## References

- [Chat-to-game assistant design](../superpowers/specs/2026-10-30-chat-to-game-assistant-design.md).
- [ADR 0035](0035-authored-narrative-games-and-portable-godot-export.md),
  [ADR 0036](0036-immutable-authored-revisions-and-recoverable-conflicts.md),
  [ADR 0037](0037-temporal-owned-narrative-build-attempts.md).
- [Product direction](../product/narrative-game-studio.md).
