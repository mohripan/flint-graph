from flint_graph.application.services.conversation_memory import conversation_policy_fingerprint
from flint_graph.config import Settings


def test_policy_fingerprint_changes_with_context_and_provider_policy_but_not_secrets():
    baseline = conversation_policy_fingerprint(Settings(env="test"))
    assert len(baseline) == 64
    assert conversation_policy_fingerprint(Settings(env="test")) == baseline
    assert (
        conversation_policy_fingerprint(Settings(env="test", query_ollama_context_tokens=16384))
        != baseline
    )
    assert (
        conversation_policy_fingerprint(Settings(env="test", query_min_supported_claim_ratio=0.9))
        != baseline
    )
    assert (
        conversation_policy_fingerprint(
            Settings(env="test", anthropic_api_key="different-test-secret")
        )
        == baseline
    )
