"""Unavailable installations stay a recoverable manual-review path."""

import pytest

from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.narrative_look_tagger import LookTagger


async def test_invalid_interpreter_is_unavailable_without_exposing_its_path(tmp_path):
    broken = tmp_path / "broken-python"
    broken.write_text("not an executable")
    with pytest.raises(DomainError) as failure:
        await LookTagger(str(broken), str(tmp_path)).tag(b"image")
    assert failure.value.status_code == 503
    assert str(tmp_path) not in failure.value.detail
