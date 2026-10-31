# Assistant tools for story format 2: delivery and qualification

Scope: the story assistant ([ADR 0038](../adr/0038-conversational-authoring-through-reviewed-proposals.md))
on story format 2 ([ADR 0040](../adr/0040-visual-novel-stage-theme-and-asset-library.md)).
The user asked it to "generate a character … transparent … two expressions" and it
could not: it only knew format 1 scenes, characters and variables. Only the local
Ollama model was called; no paid provider was used.

## Delivered

- **Prompt `narrative-assistant/v2`** (pinned; v1 stays pinned). On format 2 the
  context shows the format, each character's expressions, colour, framing and saved
  appearance, the story's assets, up to 120 approved library files by key, and the
  theme. Format 1 stories are told they have no stage and are pointed to "Use stage
  & theme".
- **New edits.** `upsert_character` takes an optional `color`, `sprites` and
  `stage` framing, and keeps fields it does not set. `set_theme` sets or clears the
  theme. Line `expression` and stage nodes are in the response schema.
- **Library files by ID.** The model uses a library key as an asset ID. After
  parsing, the server adds an explicit `add_asset` for each key the proposal
  references, with the approved file's path and SHA-256. Unknown IDs still fail
  validation, as before.
- **Image actions.** `generate_character_images` (appearance tags, character type,
  portrait or full-body, transparent) and `generate_backgrounds` are proposal
  actions: applying a proposal skips them, and each one targets its own
  `actions.…` record. A transparent request is always full-body. Several actions
  may target one character, one per expression.
- **Studio.** A proposal lists "Suggested pictures" under its changes. Each has a
  Generate button that saves the character's appearance (as the character sheet
  does) and starts a portrait, sprite or background job with the creator's access,
  using a stable idempotency key per suggestion. A suggestion for a character the
  proposal adds is disabled until the proposal is accepted. Rejected proposals hide
  their suggestions.
- **Repairs.** A repaired answer is written as the creator's first answer, with no
  apology or mention of the diagnostics.

## Qualification

- **Unit and frontend tests.** `test_narrative_assistant_tools.py` covers library
  keys, merged character edits, theme set and clear, actions leaving the story
  unchanged, transparent sprites forced to full-body, validation errors, library
  resolution, context content and a scripted turn. The frontend model test covers
  the new change descriptions, `proposalActions` readiness and `isAction`.
- **Live, owned stack** (local Ollama, gemma-4-12B): the user's exact prompt on the
  format 2 "Upgrade QA (format 1)" project.
  1. The first run lost the transparency: the prompt called transparency
     "full_body only", so the repair dropped it. It also claimed the images were on
     their way.
  2. With the clearer wording, the model put both expressions into one action, which
     hit the one-action-per-character rule. The repaired reply talked about the
     error.
  3. Thread `40162f75-b5e7-4da3-abe3-edeaa75a174b` passed on the first attempt. It
     added Kael with two transparent full-body sprite actions (natural and happy) and
     a reply that says to click Generate after accepting.
- **Studio, headless Edge.** Before acceptance both Generate buttons were disabled
  with "Accept the proposal first". Accept saved revision 4 and enabled them. Both
  clicks reported "Started", and the API listed two transparent full-body jobs for
  `kael`; the owned image worker ran the first.

## Open

- Expression edits of an approved base sprite (ADR 0041, another branch) will
  replace one-job-per-expression with an expression action once merged.
- Event CGs (#161) are not yet in the format, so the assistant cannot place them.
