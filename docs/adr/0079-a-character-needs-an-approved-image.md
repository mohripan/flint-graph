# ADR 0079: A character needs an approved image

- Status: accepted, 2026-11-07. Prompt v15.
- Date: 2026-11-07
- Changes: the "write everything now, offer pictures after" rule of prompt v13.

## Context

A creator approved four sprites of a character, then asked the assistant for a scene. The game showed nobody.
Approving an image only kept it in the library, so the character had no expressions. The assistant's stage
step lost her, as someone with no pictures, and her lines played over an empty stage. The Look page did show her,
because its preview borrows a picture, which made it harder to see what was wrong.

## Decision

The owner set two rules.

**The first image approved for a character becomes their `default` expression.** It applies wherever it is
approved: the chat, Characters or Assets. It counts a transparent sprite or a portrait, and only the first. The
creator can change it afterwards. `firstExpression` in `StudioPage.tsx` saves a revision straight away, or if
there are unsaved edits, adds it to them so nothing is lost. Older stories that say `neutral` keep working: code that
needs the usual face takes `default`, then `neutral`, then whatever there is.

**A new scene cannot use a character with no image.** Narration needs none, and neither does a story's narrator.

- The assistant's proposal is refused with `needs_approved_picture` (`narrative/pictures.py`), and the repair tells the
  model what to do instead: add the character and offer an image card. A model that will not change gets a
  proposal that cannot be accepted. Asked for a story with nobody drawn yet, it now offers cards first, and writes
  their scenes once images are approved.
- The editor's speaker menus disable anyone without one, and say why.
- Only what a change adds counts, so stories saved before this rule stay editable. Rewording a line
  changes nothing about who speaks it.

Whoever speaks a new line is also put on stage, by adding them to the step before it or adding a step, unless a
step hides them or the request asks for them to be absent. A prompt rule alone has not been enough for a local
model before now, so this is done in code as well.

## Why not in the save path

`create_revision` could refuse too, which would be stricter. But a character may fairly have a voice or a place in
the cast with no picture, many tests rely on that, and the rule is about making scenes, which happens in the two
places above. So hand-editing JSON in the **Source** panel can still get past it, which is left as the expert's way
out, and the editor's notice "speaks here but isn't on stage" still says what happened.

## Consequences

- A creator must approve an image before any character's scene, so a first story takes one more step and spends
  credits earlier. Cards still wait for Generate, as in ADR 0068.
- The assistant may now choose someone's look itself, and say so, because asking instead of writing was the failure
  that prompt v13 removed. The card can be adjusted before Generate.
- Only the first approved image is attached. The rest stay in the library until the creator uses them.
