# ADR 0076: Screenshots for the assistant

Status: accepted, 2026-11-07

## Context

Creators want to show the assistant what they see: "the character can't be seen at all", with a screenshot. The
assistant's model cannot see. Ollama lists it as `completion, tools, thinking`, and it refuses images with "does not
support multimodal requests". It was chosen for its writing, so replacing it for this would be the wrong trade.

## Decision

**A second small model looks, and tells the assistant in words.** `FLINT_GRAPH_NARRATIVE_ASSISTANT_VISION_MODEL` names
a vision model on the same Ollama, and is off by default. With it off, the Picture button does not appear and uploads
are refused. Before the writing model is called, the assistant worker reads each picture, asks the vision model what it
shows, and adds that under "attached" in the story context, quoted as data.

We use **`lfm3-vl:2b`**. On the owner's two real screenshots it said "No characters are visible" about the scene with
none, and on the other described the character, framing and background and read the name and dialogue. At about 1.5 GB
it fits beside the 7.6 GB writing model on a 12 GB GPU, so nothing swaps. It took 5 seconds once loaded. `keep_alive` is
0 so that memory goes straight back to the image and voice workers. Its LFM Open License v1.0 allows free commercial
use below $10M annual revenue; above that, Liquid AI requires a commercial licence. Check this before that point.

**Pictures are private and simple.**

- People can paste, drop or choose a picture. The browser redraws it as a PNG at most 1600 px on its longest side, which
  also drops its metadata. The server still normalizes and validates it as a PNG, up to 8 MB.
- A message takes up to 3, and a project up to 500. The same picture pasted again is the same row.
- They live under the project's own prefix and table, so Delete forever (ADR 0073) removes them with nothing added.
- They are never part of a story or a game, and the prompt tells the assistant they are not files it can use.
- The worker keeps the description, so a retried reply does not look again. Temporal history still carries only IDs.

**A picture that cannot be read never stops the reply.** The assistant is told it could not be read, and says so.

**Pictures cost no extra credits** beyond the reply itself. The vision step is a few seconds of GPU.

The prompt lock's CLI used to require a candidate to have exactly the same entries, which forbade adding a prompt. It now
refuses only a candidate that loses one; `validate_upgrade` already allowed additions.

## Consequences

- A description can be wrong, and the assistant only knows what it says. A small model reads text and framing better
  than it judges art, and it is not a substitute for the assistant seeing.
- Two real screenshots and one real chat are not a measurement of quality across many screens.
- A deployment needs the vision model pulled wherever Ollama runs, beside the writing model.
- A newly attached picture adds the time to load the vision model, about 2 seconds here, and more on a cold GPU. The
  first run on this machine took 52 seconds.
