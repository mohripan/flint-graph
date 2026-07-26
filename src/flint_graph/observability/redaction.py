"""Log redaction.

Logs are shipped off-box, so they must never carry prompts, answers, document
text, or credentials. Redaction is a structlog processor rather than a review
convention: a new log call site cannot leak a payload by forgetting the rule.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

REDACTED = "[redacted]"

# Keys whose values are model or document payloads. Bounded metadata about them
# (counts, hashes, identifiers) is fine; the text itself is not.
_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "answer",
        "answer_text",
        "chunk",
        "chunk_text",
        "claim",
        "claim_text",
        "content",
        "context",
        "context_pack",
        "delta",
        "document_text",
        "normalized_text",
        "prompt",
        "query",
        "query_text",
        "raw_text",
        "system_prompt",
        "text",
        "text_preview",
        "user_prompt",
    }
)

# Keys whose values are credentials. Always redacted, in every environment.
_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "access_key",
        "access_key_id",
        "api_key",
        "authorization",
        "aws_secret_access_key",
        "bearer",
        "client_secret",
        "credentials",
        "id_token",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "secret_access_key",
        "secret_key",
        "session_token",
        "token",
    }
)

_SECRET_KEY_FRAGMENTS: tuple[str, ...] = ("password", "secret", "api_key", "token")

_MAX_DEPTH = 6


def is_secret_key(key: str) -> bool:
    lowered = key.casefold()
    if lowered in _SECRET_KEYS:
        return True
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def is_payload_key(key: str) -> bool:
    return key.casefold() in _PAYLOAD_KEYS


class RedactionProcessor:
    """structlog processor that strips secrets and, optionally, payload text.

    ``allow_payloads`` exists only so a local developer can debug prompt shaping.
    Staging and production reject it at config validation time.
    """

    def __init__(self, *, allow_payloads: bool = False) -> None:
        self._allow_payloads = allow_payloads

    def __call__(
        self,
        _logger: Any,
        _method_name: str,
        event_dict: MutableMapping[str, Any],
    ) -> Mapping[str, Any]:
        for key in list(event_dict):
            event_dict[key] = self._redact(key, event_dict[key], depth=0)
        return event_dict

    def _redact(self, key: str, value: Any, *, depth: int) -> Any:
        if is_secret_key(key):
            return REDACTED
        if not self._allow_payloads and is_payload_key(key):
            return _summarize(value)
        if depth >= _MAX_DEPTH:
            return value
        if isinstance(value, dict):
            return {
                nested_key: self._redact(str(nested_key), nested_value, depth=depth + 1)
                for nested_key, nested_value in value.items()
            }
        if isinstance(value, list | tuple):
            items = [self._redact(key, item, depth=depth + 1) for item in value]
            return type(value)(items) if isinstance(value, tuple) else items
        return value


def _summarize(value: Any) -> Any:
    """Replace payload text with a bounded description of it."""
    if value is None:
        return None
    if isinstance(value, str):
        return f"{REDACTED} ({len(value)} chars)"
    if isinstance(value, dict | list | tuple):
        return f"{REDACTED} ({len(value)} items)"
    return REDACTED
