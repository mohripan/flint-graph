"""Narrow, zero-inference question interpretation; never factual answer memory."""

import re
from dataclasses import dataclass
from typing import Literal

MEMORY_POLICY_VERSION = "prior-year-scope-v1"
_PRIOR_YEAR = re.compile(
    r"^(?:and\s+)?(?:what|how)\s+about\s+(?:the\s+)?(?:prior|previous)\s+year\??$",
    re.IGNORECASE,
)
_FOLLOWUP = re.compile(
    r"^(?:what|how)\s+about\b|^(?:and|also)\b|\b(?:it|its|they|their|them|those|that)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)[0-9]{2}\b")


@dataclass(frozen=True, slots=True)
class FollowupInterpretation:
    mode: Literal["independent", "resolved", "clarification"]
    query: str
    reason: str


def interpret_followup(question: str, previous_question: str | None) -> FollowupInterpretation:
    normalized = " ".join(question.split())
    if not _PRIOR_YEAR.fullmatch(normalized):
        if _FOLLOWUP.search(normalized):
            return FollowupInterpretation("clarification", question, "unsupported_followup")
        return FollowupInterpretation("independent", question, "self_contained")
    if previous_question is None:
        return FollowupInterpretation("clarification", question, "no_trusted_previous_turn")
    if len(previous_question) > 1000:
        return FollowupInterpretation("clarification", question, "previous_question_too_large")
    years = list(_YEAR.finditer(previous_question))
    if len(years) != 1 or int(years[0].group()) <= 1900:
        return FollowupInterpretation("clarification", question, "ambiguous_previous_year")
    match = years[0]
    resolved = (
        previous_question[: match.start()]
        + str(int(match.group()) - 1)
        + previous_question[match.end() :]
    )
    return FollowupInterpretation("resolved", resolved, "explicit_prior_year")
