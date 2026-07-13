from __future__ import annotations

import re
import unicodedata

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_name(text: str) -> str:
    """Normalize an entity surface form for matching.

    The transform is Unicode NFKC, casefold, punctuation stripped to spaces, and
    whitespace collapsed. It is deterministic and shared by mention persistence,
    alias registration, and candidate generation so the same surface always
    produces the same key.
    """

    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.casefold()
    normalized = _PUNCTUATION.sub(" ", normalized)
    normalized = _WHITESPACE.sub(" ", normalized)
    return normalized.strip()
