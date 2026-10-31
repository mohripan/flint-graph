"""Catalog-backed assistant instructions; historical identities remain readable."""

import hashlib
from typing import Any

from flint_graph.narrative.values import canonical_json
from flint_graph.prompts.source import current_snapshot, render_chat


def system_prompt() -> str:
    return render_chat("narrative.assistant.system")[0]["content"]


def response_schema() -> dict[str, Any]:
    schema: dict[str, Any] = (
        current_snapshot().entry("narrative.assistant.system").data["output_schema"]
    )
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
}
