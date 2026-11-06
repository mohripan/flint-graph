# ADR 0061: The assistant runs generation

Status: accepted (2026-11-06)

Amends [ADR 0038](0038-conversational-authoring-through-reviewed-proposals.md), which kept
image generation a suggestion the creator started by hand.

## Context

The Assistant is the primary workflow, but the Studio had outgrown it. It could suggest
portraits, sprites and backgrounds, and nothing else. It had no way to ask for expressions,
CGs or voices, and its output schema could not even express a stage `cg` or a line `voice`.
Generating a picture took Accept, then Generate, then a trip to another tab to approve it.

Qualifying the existing flow live showed something worse. Asked for a character with a
sprite, the local model took three attempts and about 100 seconds, and the sprite was then
silently dropped. Six of the 14 real turns on the main Studio had needed repairs.

The cause was the output schema. It had two defects, and each hid the other:

1. **One flat operation shape.** Every field of every operation was optional on one object,
   so the grammar let the model write `{"op": "generate_character_images", "voice": "girl"}`.
2. **Alphabetical field order.** The prompt lock stores keys sorted, and a grammar-constrained
   model must write fields in schema order. So with exact per-operation shapes,
   `generate_backgrounds` would have to begin `{"description"`. The model wants to begin
   `{"op"`, and only `set_title` and `set_theme` allowed that. Its thinking said
   `generate_backgrounds`, and its output said `set_title`.

## Decision

1. **Actions run for real.** `generate_expressions`, `generate_cg` and `generate_voice` join
   `generate_character_images` and `generate_backgrounds`.
2. **Generation may start before acceptance**, unless it depends on something the proposal
   itself adds or rewrites (`action_needs_accept`). Results are only candidates, so this
   cannot change canon. Story edits still need Accept, and files still need approval.
3. **Automatic generation is on by default, and can be switched off** in the composer. The
   choice is stored per turn. The creator asked for a picture, so it should get one; each
   start spends credits, so the switch is one click away and its label says so.
4. **Actions are durable.** `narrative_assistant_actions` holds their state and bindings to
   jobs. `dispatch_actions` and `reconcile_actions` run in the assistant worker's loop:
   - automatic actions need no open page, and survive a crash or restart;
   - a full queue leaves an action `pending`, so five requested jobs do not fail because the
     workspace allows two at a time;
   - anything else blocks it with a reason for the creator, and a click retries it.
5. **Starting an action only admits a normal job**, with the same content policy, credits,
   audit and outbox. One action is one job, through a key derived from the proposal and the
   operation's position, however it was started.
6. **The server resolves what the model cannot know.** The approved picture of a character,
   a face box from the sprite's alpha (mirroring the browser's guess), and a voice for a
   character with none. A voice the creator chose is never replaced, and a voice the model
   invented is ignored.
7. **Job endings reach the conversation by reconciliation**, not hooks in the image and voice
   workers, which keep knowing nothing of conversations. `action.started`, `action.blocked`,
   `job.finished` and `asset.approved` join the thread log
   ([ADR 0060](0060-assistant-thread-event-log.md)), so the next turn knows what was made
   and chosen. A pause of up to one poll is harmless.
8. **Results are in the chat.** Thumbnails and clips come with **Approve** and, where the
   meaning is clear, **Use**: a sprite on stage, an expression under its name, a clip on its
   line. **Use** saves a normal revision with the editor's own functions.
9. **The output schema is exact and ordered.** Prompt v4 has one closed shape per operation
   with its real required fields. `response_schema()` writes `reply`, then `op` and `type`,
   before the other fields. Writing order is not part of the prompt's identity, so
   historical hashes stay valid. Older bundles get the same ordering when replayed.
10. **Slips with one obvious meaning are corrected without a model call**, because each round
    trip costs about a minute: `speaker: narrator` with no such character, a voice on a line
    with no speaker, and `text` on a full voice. Repairs now say what exists rather than only
    where the problem is.

## Rejected

- **A multi-step tool loop for the model.** Each call costs 10 to 60 seconds locally. The
  proposal is already one structured tool call with validation and repair.
- **Having the browser start automatic actions.** No worker changes, but a closed tab stops
  generation, and a teammate opening the page would spend their credits on someone else's turn.
- **Starting jobs inside `complete_turn`.** It holds the turn row, and admission takes the
  tenant and project locks: the opposite order from the API, so it could deadlock.
- **Hooks in every job's terminal path.** There are many (complete, fail, abandon, cancel, in
  two services), and missing one would silently lose an event.
- **Keeping the flat schema and relying on better repair messages.** The live model repeated
  the same mistake through both repairs.

## Consequences

- The same character request went from three attempts, about 100 seconds and no sprite to one
  attempt and about 13 seconds of model time, with the sprite. Reply text now streams first.
- The assistant worker needs the API's image, voice and object-store settings.
- A model that invents a request could spend credits on it, up to the job's price. Per-kind
  caps and the balance still apply, the worker stops when they run out, and the switch turns
  this off.
- A generated picture can start for a proposal that is later rejected. That job finishes;
  its result stays a candidate.
- Grammar enforcement applies to Ollama. Other providers still rely on validation and repair.
- Poses are not available to the assistant: the pose model is an optional service, not
  installed on the machine this was qualified on.
