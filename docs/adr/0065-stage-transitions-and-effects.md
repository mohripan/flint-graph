# ADR 0065: Stage transitions and effects

Status: accepted (2026-11-07)

## Context

Stage changes in a game were instant, so a new background or a character walking on simply popped
into place. #162 asks for a small, declarative set of effects that cannot grow into scripting, that
never changes story state, and that players can turn off.

## Decision

1. **Two optional fields on a format 2 stage step, with closed values.** `transition` is `cut`,
   `fade`, `dissolve` or `slide`. `effect` is `shake` or `flash`. Both have fixed durations. There are
   no custom durations, shaders or scripts.
2. **They change how a step looks, never what it does.** They are not in saves or route traces.
   The players' `view` reports what to play on arriving at a screen, and only for that arrival.
   Loading a save plays nothing, and neither does a new start.
3. **The settled screen is the same either way.** The view keeps the old screen above the new one
   until it has gone, so the stage underneath is always the settled one. A test walks a story with
   motion on and off and compares every screen.
4. **A change with no `transition` gets a quick dissolve of 0.2 seconds.** Existing stories therefore
   stop popping without any edit. `cut` asks for the old instant change. Validation needs a real
   change for a transition, so a step cannot hold only one. An `effect` alone is a real step, because
   a shake needs no new background.
5. **A press finishes first.** One press ends a transition, the next finishes the text, and the
   next moves on. Auto waits for a transition, and Skip shows none.
6. **Fade and slide hide the text box until they finish.** A dissolve keeps it visible.
7. **Flash is one fade-out in 0.35 seconds, never a repeated flicker,** for photosensitive players.
8. **Players can turn it all off** with Reduce motion in the menu. The setting is stored on the
   device. Without a stored setting, a browser's `prefers-reduced-motion` decides.
9. **The Studio's stage panel has a Transition and an Effect control.** The Transition control is
   off until the step changes something, and a step that stops changing anything loses its transition.
10. **The assistant can use both** (prompt v7). It is told to leave `transition` out for an ordinary
    change, because the game already blends it, and to use these only when asked or when the moment
    clearly calls for it.

## Consequences

Runtime 0.9.0. Saves and earlier exports are unaffected, and format 1 stories have no stage to apply
these to. Settings files from runtime 0.8.0 still read correctly.

The panel edits the stage step that opens a scene, so a mid-scene step shows its transition in the
script view but changes it through the assistant or Source. Character enter and exit have no motion
of their own; they take part in the screen's transition. Parity is checked by the view's reported
values and settled figure positions, not by comparing rendered pixels.
