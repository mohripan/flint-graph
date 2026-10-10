"""Conservative English financial-value scope rule, not a semantic classifier."""

import re

_BARE_VALUE_RE = re.compile(
    r"(?:what\s+(?:was|were)|how\s+much\s+(?:was|were))\s+(?:the\s+)?"
    r"(?:(?:total|net|gross|annual|quarterly|operating)\s+)*"
    r"(?:revenue|sales|profit|income|earnings|cash\s+flow|assets|liabilities)"
    r"(?:\s+(?:in|for|during)\s+(?P<period>(?:fy\s*|fiscal\s+year\s+)?(?:19|20)\d{2}))?"
    r"\s*[?.]?\s*",
    re.IGNORECASE,
)


def missing_financial_scope(query: str) -> list[str]:
    match = _BARE_VALUE_RE.fullmatch(query.strip())
    if match is None:
        return []
    return ["company_or_document"] + ([] if match.group("period") else ["reporting_period"])
