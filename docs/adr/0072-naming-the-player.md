# ADR 0072: Naming the player

- Status: accepted
- Date: 2026-11-07
- Issue: #165 (part)

## Context

Many visual novels let the player name the protagonist, and characters then call them by it. It needs text
input, which the story format never had, and it reaches state: the name has to last through saves and route
traces in all four implementations.

## Decision

**The format.** Format 2 gains an optional `player`, with a `default_name` and optionally the `character` who
takes the name, and a node `{"type": "name", "text_id", "text", "next"}` that asks. With a `player`, `{name}` in
any line, choice, option or ending text is the name. Without one, `{name}` is ordinary text, so no existing story
changes.

**A typed placeholder, not a template.** `{name}` is the only one. It is one plain string replacement, not
recursive, so a name of `{name}` shows as those six characters. Conditions cannot see it.

**Plain text on screen.** Story text never goes through markup, and the name is treated the same. `[b]Zoë[/b]`
shows the brackets. A test holds that, along with non-ASCII names and emoji.

**Cleaning, identical everywhere.** `clean_name` in Python and `player.gd` removes control, invisible, line-
breaking and text-reversing characters, trims spaces including the non-breaking and ideographic ones, and keeps
32 code points. The zero-width joiners stay, since some scripts and emoji need them. Nothing is normalised, because
two engines could disagree. An empty answer takes the default. A test feeds the same table to the real engine.

**State.** `player_name` is in the state, saves and route traces only when a `player` is declared, so other stories
save exactly as they always have. A saved name must already be clean or the save is refused.

**In the player.** The question shows in the text box with a field under it, focused and holding the current name.
Enter or a button answers. Auto and Skip stop there, as at a choice, and letters typed there are not shortcuts.

**A name the font cannot show.** A browser gives Godot no system fonts, so on the web a letter missing from the
game's font is an empty box, in every line that says the name. Real key events in a web build showed it with Japanese and
emoji. The field now says so and asks for other letters. On desktop the system fonts fill in. A creator wanting those
scripts uploads a font that has them, in Look.

**In the Studio.** "Ask the player's name" adds the node and a default `player`. Its form holds the question, the
default and who takes the name. The scene form hints at `{name}`.

**For the assistant.** Prompt v12 adds `set_player` and the `name` node, each with an exact shape. The real model
often wrote only part of it, so the code finishes the job: writing `{name}` or a `name` node brings a `player`, and a
new player with no question gets one before the story starts. These are the only reasons to use a player.

**Two smaller fixes the real model showed were needed.** A character with no pictures is left out of a stage step
rather than failing it, and whatever a proposal led into an emptied step now goes straight on to what followed.

**Voiced lines** are recorded once, so a clip says the default name. The text still shows the typed one.

Runtime 0.12.0. No migration, since all of this lives in the story.

## Alternatives

- **A name variable with templates in text.** Open-ended, and a template language in dialogue is what #165 rules out.
- **Free text in ordinary variables.** Conditions would then compare typed text, which #165 also rules out.

## Consequences

- #165's appearance choices (enums selecting outfit layers) remain open.
- A literal `{name}` cannot appear in a story with a player. Nobody has needed that yet.
- Web games using the built-in Lora accept only Latin-script names. Bundling a wider font would add many megabytes to every
  game, so that is left to the creator's choice of font.
- Read marks use the shown text, so a replay with a different name counts as unread for Skip.
