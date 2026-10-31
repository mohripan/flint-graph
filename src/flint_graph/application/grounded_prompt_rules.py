"""Shared, versioned grounding instructions; verification remains a separate step."""

import json
from typing import Any

from flint_graph.application.financial_arithmetic import VerifiedCalculationHint
from flint_graph.prompts.source import current_snapshot, render

ANSWER_PROMPT_VERSION = "grounded-answer-v3"
SUPPORT_PROMPT_VERSION = "grounded-support-v3"


def verified_calculation_lines(policy: dict[str, Any]) -> list[str]:
    raw = policy.get("verified_calculation")
    if raw is None:
        return []
    try:
        hint = VerifiedCalculationHint.model_validate(raw)
    except ValueError:
        return []
    return [
        render("grounded.verified_calculation"),
        json.dumps(hint.model_dump(mode="json"), sort_keys=True),
    ]


ANSWER_RULES = tuple(current_snapshot().entry("grounded.rules").config["answer"])

SUPPORT_RULES = tuple(current_snapshot().entry("grounded.rules").config["support"])
