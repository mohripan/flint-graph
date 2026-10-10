"""Bounded syntactic planning; never invent entities, dates or evidence."""

import re

_SUBJECT = r"[A-Z][A-Za-z0-9_-]*(?:\s+[A-Z][A-Za-z0-9_-]*){0,5}"
_BOUNDARY = re.compile(rf"\s+(?i:and|versus|vs\.?)\s+(?={_SUBJECT}['\u2019]s\b)")
_POSSESSIVE = re.compile(rf"(?P<subject>{_SUBJECT})['\u2019]s\b")
_LEAD = re.compile(r"^(?:Give|Compare|Tell|Describe|Show|What|Which)\s+")
_ASSOCIATION_SUFFIX = re.compile(
    r",\s*(?:identifying|indicating|showing|specifying)\s+which\s+"
    r"(?:figures?|values?|numbers?)\s+(?:belongs?|corresponds?)\s+to\s+which\s+"
    r"(?:compan(?:y|ies)|documents?|sources?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)


def coordinated_retrieval_queries(query: str) -> list[str]:
    clauses = _BOUNDARY.split(query)
    if not 2 <= len(clauses) <= 3:
        return [query]
    subjects = []
    for clause in clauses:
        match = _POSSESSIVE.search(clause)
        if match is None:
            return [query]
        subjects.append(_LEAD.sub("", match["subject"]).casefold())
    if len(set(subjects)) != len(subjects):
        return [query]
    # Omit only an explicit display/attribution instruction from retrieval.
    # The complete original question remains the generation/support input.
    return [_ASSOCIATION_SUFFIX.sub("", clause).strip() for clause in clauses]
