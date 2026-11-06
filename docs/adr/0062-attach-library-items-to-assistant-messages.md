# ADR 0062: Attaching library items to an assistant message

Status: accepted (2026-11-06)

## Context

A creator thinks in terms of what they already have: "put *her* in a scene at *this* street".
The model only saw a flat list of up to 120 approved file names, one line of looks per
character and no way to tell which of several similar files was meant. It had to guess or ask,
and in a large project the file might be past the list's limit altogether.

## Decision

1. **A Library in the composer.** It opens over the chat with Characters, Pictures and Voices
   tabs and a search box. Picking an item attaches it to the next message as a chip.
2. **Only characters of the saved story and approved files can be attached.** The server checks
   each one at admission against the base revision and this project, and refuses the message
   with a reason otherwise. A refused message writes and charges nothing.
3. **Attachments are frozen on the turn with their names**, so the chat shows what was attached
   even if a file is renamed later. They are part of the message's idempotency identity.
4. **The model is told exactly what was attached, under the IDs it must use**: a character with
   their expressions, looks and voice, and a file with its kind and owner. Files attached come
   first in the library list, so the 120-file limit can never drop them. Something removed or
   no longer approved since it was attached is left out.
5. **The conversation remembers.** `turn.requested` records the attached names, so later turns
   and the Activity log show them.
6. **Generated results can be attached directly** with **Attach to message**, once approved.

Attachments are references inside one project. They carry no bytes to the model, which reads
names and IDs only.

## Rejected

- **Giving the model a tool to search the library.** Each extra call costs seconds to minutes
  locally, and a person pointing at what they mean is more reliable than a model searching.
- **Letting candidates be attached.** A story can only bind approved files, so the model could
  not use one; approving is a click away in the same chat.
- **Parsing `@names` out of the message.** A picker cannot be mistyped, and it can show what a
  file looks like.

## Consequences

- Vague requests resolve: "she stands here" names one character and one background.
- A message can attach up to 12 items, bounded by the API.
- Fonts stay out of the picker. They are chosen in the Look tab.
- The picker lists up to 384 approved files per project, the shared approved list's limit. Search
  works within those.
