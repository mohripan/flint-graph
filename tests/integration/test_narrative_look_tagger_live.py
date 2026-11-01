"""Opt-in real CPU qualification with the WD-only model directory, no CCIP files."""

import asyncio
import os
from pathlib import Path

import pytest

from flint_graph.domain.errors import DomainError
from flint_graph.infrastructure.narrative_look_tagger import WD_MANIFEST, LookTagger

MODEL = os.environ.get("FLINT_GRAPH_LOOK_TAGGER_MODEL")
PYTHON = os.environ.get("FLINT_GRAPH_LOOK_TAGGER_PYTHON")
pytestmark = pytest.mark.skipif(
    not MODEL or not PYTHON, reason="Set explicit WD tagger model and Python"
)


async def test_actual_wd_child_tags_approved_fixture_without_ccip_or_gpu(tmp_path):
    data = (
        Path(__file__).parents[2] / "evals/character-preservation/pilot-v1/references/aster.png"
    ).read_bytes()
    result = await LookTagger(PYTHON, MODEL).tag(data)
    assert result["model_manifest_sha256"] == WD_MANIFEST
    assert result["general_tags"]["white_hair"] > 0.5
    assert len(result["tagger_sha256"]) == 64
    # A tampered manifest is refused before opening any checkpoint.
    (tmp_path / "flintgraph-download.json").write_text("{}")
    with pytest.raises(DomainError) as refused:
        await LookTagger(PYTHON, str(tmp_path)).tag(data)
    assert refused.value.status_code == 503
    assert str(tmp_path) not in refused.value.detail
    # A second tab gets a recoverable busy response instead of an unbounded wait.
    shared = LookTagger(PYTHON, MODEL)
    replies = await asyncio.gather(shared.tag(data), shared.tag(data), return_exceptions=True)
    assert sum(isinstance(reply, dict) for reply in replies) == 1
    assert (
        sum(isinstance(reply, DomainError) and reply.status_code == 429 for reply in replies) == 1
    )
