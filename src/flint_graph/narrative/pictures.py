"""Someone can only be in a scene once they have a picture to show (ADR 0079).

Without one the game plays their words over an empty stage. Only what a change adds counts: stories
saved before this rule stay editable, and rewording a line says nothing about who speaks it.
"""

from typing import Any

from flint_graph.narrative.values import Diagnostic

CODE = "needs_approved_picture"
# A story's narrator is a voice. There is nobody to draw, so nobody to wait for.
_NO_BODY = {"narrator", "narration"}


def _shown(node: dict[str, Any]) -> set[str]:
    return {
        entry["character"]
        for entry in node.get("show") or []
        if isinstance(entry, dict) and isinstance(entry.get("character"), str)
    }


def without_pictures(base: dict[str, Any], story: dict[str, Any]) -> list[tuple[str, str]]:
    """Each (scene, character) that ``story`` adds to ``base``, for someone with no sprite."""
    if story.get("schema_version") != "2":
        return []
    characters = story.get("characters") or {}
    saved = base.get("nodes") or {}
    found: list[tuple[str, str]] = []
    for key, node in (story.get("nodes") or {}).items():
        if not isinstance(node, dict):
            continue
        before = saved.get(key)
        before = before if isinstance(before, dict) else {}
        if node.get("type") == "line":
            speaker = node.get("speaker")
            names = (
                {speaker}
                if isinstance(speaker, str) and speaker != before.get("speaker")
                else set()
            )
        elif node.get("type") == "stage":
            names = _shown(node) - _shown(before)
        else:
            continue
        for name in sorted(names):
            character = characters.get(name)
            if name.lower() in _NO_BODY:
                continue
            if isinstance(character, dict) and not character.get("sprites"):
                found.append((key, name))
    return found


def picture_diagnostics(base: dict[str, Any], story: dict[str, Any]) -> tuple[Diagnostic, ...]:
    return tuple(Diagnostic(CODE, f"nodes.{key}") for key, _ in without_pictures(base, story))
