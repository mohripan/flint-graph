import pytest

from flint_graph.domain.enums import ProviderUsageOperation
from flint_graph.infrastructure.provider_telemetry import provider_call


@pytest.mark.anyio
async def test_error_telemetry_preserves_the_original_provider_failure() -> None:
    failure = ConnectionError("provider unavailable")
    with pytest.raises(ConnectionError) as raised:
        async with provider_call(
            provider="ollama", model="test-model", operation=ProviderUsageOperation.ANSWER
        ):
            raise failure
    assert raised.value is failure
