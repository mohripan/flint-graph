"""Catalog-backed assistant instructions; historical identities remain readable."""

import hashlib
from typing import Any

from flint_graph.narrative.values import canonical_json
from flint_graph.prompts.source import current_snapshot, render_chat


def system_prompt() -> str:
    return render_chat("narrative.assistant.system")[0]["content"]


# A grammar-constrained model must write fields in the schema's order, and the lock stores
# keys sorted. Left sorted, an operation has to start with whatever field sorts first, so a
# model that means to write {"op": "generate_backgrounds"} gets funnelled into the few
# operations that may start with "op", and writes set_title instead. These go first; the
# reply first of all, so the creator sees it streaming before the proposal.
_WRITTEN_FIRST = (
    "reply",
    "op",
    "type",
    "summary",
    "id",
    "character",
    "characters",
    "speaker",
    "text",
    "next",
    # A stage step: what is seen before what is heard. Sorted, "ambience" would come before
    # "background", and a model that had written the background could only reach "music".
    "background",
    "cg",
    "show",
    "hide",
    "music",
    "ambience",
    "sound",
    "transition",
    "effect",
)


def _written_order(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_written_order(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result = {key: _written_order(value) for key, value in schema.items()}
    properties = result.get("properties")
    if isinstance(properties, dict):
        rank = {name: position for position, name in enumerate(_WRITTEN_FIRST)}
        result["properties"] = {
            name: properties[name]
            for name in sorted(properties, key=lambda item: (rank.get(item, len(rank)), item))
        }
    return result


def response_schema(*, child_session: bool = False) -> dict[str, Any]:
    """What a model may write. Inside a child session it cannot start another: asked nicely,
    the live model tried anyway, and so did no work on its task."""
    schema: dict[str, Any] = _written_order(
        current_snapshot().entry("narrative.assistant.system").data["output_schema"]
    )
    if child_session:
        for branch in schema["properties"]["proposal"].get("anyOf", ()):
            items = (branch.get("properties") or {}).get("operations", {}).get("items", {})
            if "anyOf" in items:
                items["anyOf"] = [
                    shape
                    for shape in items["anyOf"]
                    if shape["properties"]["op"].get("const") != "start_child_session"
                ]
    return schema


def prompt_sha256() -> str:
    entry = current_snapshot().entry("narrative.assistant.system")
    identity = {
        "version": entry.data["legacy_version"],
        "system": system_prompt(),
        "schema": response_schema(),
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()


# Compatibility exports are the packaged default. Turn execution resolves through
# its immutable scope, not these import-time aliases.
PROMPT_VERSION = current_snapshot().entry("narrative.assistant.system").data["legacy_version"]
SYSTEM_PROMPT = system_prompt()
RESPONSE_SCHEMA = response_schema()

PINNED_PROMPTS = {
    "narrative-assistant/v1": "13bd64068832696009367f9fcb0fbefe66f0145299c15e315135e9eed10e6b8e",
    # Story format 2: stage, expressions, sprites, theme, library assets, image actions.
    "narrative-assistant/v2": "99d7090be56e40f350e2e681c7fb59c47a49ce956ef2bfcd29d6be82d814ee8f",
    # Clarify character intent and expose the transparent-sprite high-resolution default.
    "narrative-assistant/v3": "5caef1eeab73bcb1531fbbda1a267e52ef750d8cab9129d0db720da0636551b5",
    # Actions run for real: expressions, CGs and voices; stage CGs and line voices (ADR 0061).
    "narrative-assistant/v4": "eba010f6361e42dc3e107faa9236c74398cb4c4936246d4e52ca74e83b63de5f",
    # What the creator attached, and asset IDs versus expression names (ADR 0062).
    "narrative-assistant/v5": "36230c672aeb313f1910430e215a0cb1789fab30d3dca6fcd38f6a7f55424bb7",
    # Child sessions: the assistant can split large work up (ADR 0063).
    "narrative-assistant/v6": "d9888931438f5a6f57c738c7bc65d06864a0b59d3d7815caba466ed867493f24",
    # Stage transitions and effects, used sparingly (ADR 0065).
    "narrative-assistant/v7": "3be93c56725998b4a76097b56c8037e1552840df8815b27eadf6cadfa06df2cf",
    # Music, ambience and sound effects from the library (ADR 0066).
    "narrative-assistant/v8": "64b8ef67405cc57c8ef40754ed6c4bbd6c42ea707d1ad2295fae8c24c6eb27e8",
    # Generation cards: nothing runs until the creator presses Generate (ADR 0068).
    "narrative-assistant/v9": "f942d5b9b7e2bfedea8b0636d2553a6731ea58b7fcb686b0a01d284c6a6bfd45",
}
