"""Logs are shipped off-box, so payloads and secrets must not reach them."""

from __future__ import annotations

import pytest

from flint_graph.config import Settings
from flint_graph.logging import bind_log_context, clear_log_context
from flint_graph.observability.redaction import REDACTED, RedactionProcessor


def _redact(event: dict[str, object], *, allow_payloads: bool = False) -> dict[str, object]:
    processor = RedactionProcessor(allow_payloads=allow_payloads)
    return dict(processor(None, "info", event))


def test_prompt_and_answer_text_are_summarized_not_logged() -> None:
    redacted = _redact(
        {
            "event": "answer.finalized",
            "prompt": "Where is Acme headquartered?",
            "answer_text": "Berlin [c1]",
            "answer_citation_count": 1,
        }
    )

    assert redacted["prompt"] == f"{REDACTED} (28 chars)"
    assert redacted["answer_text"] == f"{REDACTED} (11 chars)"
    # Bounded metadata about a payload is exactly what stays useful in logs.
    assert redacted["answer_citation_count"] == 1


def test_secrets_are_redacted_even_when_payloads_are_allowed() -> None:
    redacted = _redact(
        {
            "authorization": "Bearer abc",
            "anthropic_api_key": "sk-ant-123",
            "object_store_secret_access_key": "shhh",
            "prompt": "debugging locally",
        },
        allow_payloads=True,
    )

    assert redacted["authorization"] == REDACTED
    assert redacted["anthropic_api_key"] == REDACTED
    assert redacted["object_store_secret_access_key"] == REDACTED
    assert redacted["prompt"] == "debugging locally"


def test_redaction_reaches_into_nested_structures() -> None:
    redacted = _redact(
        {
            "event": "provider.call",
            "details": {
                "model": "claude-opus-4-8",
                "api_key": "sk-ant-123",
                "records": [{"text": "chunk body", "chunk_id": "c1"}],
            },
        }
    )

    details = redacted["details"]
    assert isinstance(details, dict)
    assert details["model"] == "claude-opus-4-8"
    assert details["api_key"] == REDACTED
    assert details["records"][0]["text"] == f"{REDACTED} (10 chars)"
    assert details["records"][0]["chunk_id"] == "c1"


def test_production_rejects_payload_logging() -> None:
    with pytest.raises(ValueError, match="log_payloads is not allowed"):
        Settings(
            env="production",
            log_payloads=True,
            public_base_url="https://api.example",
            allowed_origins=["https://app.example"],
            trusted_hosts=["api.example"],
            require_tls=True,
            allow_private_url_intake=False,
            rate_limit_enabled=True,
            allow_in_memory_rate_limit=True,
            auth_mode="oidc",
            oidc_issuer="https://issuer.example/realms/flintgraph",
            oidc_audience="flintgraph-api",
            object_store_access_key_id="real-key",
            object_store_secret_access_key="real-secret",
            embedding_provider="deterministic",
            query_answer_provider="deterministic",
            query_support_provider="deterministic",
        )


def test_bind_log_context_drops_none_and_stringifies_uuids() -> None:
    from uuid import UUID

    import structlog

    clear_log_context()
    bind_log_context(
        tenant_id=UUID("11111111-1111-1111-1111-111111111111"),
        request_id="req-1",
        missing=None,
    )
    bound = structlog.contextvars.get_contextvars()
    clear_log_context()

    assert bound == {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "request_id": "req-1",
    }
