import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from flint_graph.application.services.narrative_package_v2 import (
    NOTICE_MARKER,
    Bound,
    compose_notices,
)
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.player_terms import TERMS_BEGIN, TERMS_END, player_terms
from flint_graph.narrative.values import PackageError
from flint_graph.narrative.voice_models import LICENSES

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/narrative/player_terms.json").read_text("utf-8")
)
CASES = FIXTURE["cases"]
STORY = json.dumps(
    json.loads(
        (Path(__file__).parents[1] / "fixtures/narrative/line_voices.json").read_text("utf-8")
    )["story"]
).encode()
BILIBILI, MIT = LICENSES["bilibili-model-use"], LICENSES["chatterbox-mit"]


def expand(text: str) -> str:
    markers = FIXTURE["markers"]
    return (
        text.replace("{notices}", markers["notices"])
        .replace("{begin}", markers["begin"])
        .replace("{end}", markers["end"])
    )


def test_the_fixture_markers_are_the_runtime_markers() -> None:
    assert FIXTURE["markers"] == {
        "notices": NOTICE_MARKER,
        "begin": TERMS_BEGIN,
        "end": TERMS_END,
    }


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_reference_finds_player_terms_like_every_runtime(case) -> None:
    notices = expand(case["notices"])
    if "error" in case:
        with pytest.raises(PackageError) as refused:
            player_terms(notices)
        assert refused.value.code == case["error"]
        with pytest.raises(PackageError):
            load_text_package(STORY, notices.encode(), allow_asset_refs=True)
    else:
        assert player_terms(notices) == case["terms"]


def clip(key: str, license_id: str | None, sha: str, *, source="generated", notice=None):
    item = LICENSES[license_id] if license_id else None
    provenance = (
        {
            "model_repo": "repo/model",
            "model_revision": "r" * 40,
            "license": {
                "id": item.id,
                "name": item.name,
                "sha256": item.sha256,
                "obligations": item.obligations,
            },
        }
        if item
        else {"source": "upload"}
    )
    asset = SimpleNamespace(
        license=item.name if item else "Own work",
        source=source,
        notice=notice if notice is not None else (item.notice if item else None),
        provenance=provenance,
    )
    return Bound(key, "audio", sha, asset)


def test_notices_carry_license_text_and_player_terms_only_when_a_clip_requires_them() -> None:
    plain = compose_notices("Written by me.", [clip("hi", "chatterbox-mit", "a" * 64)])
    assert player_terms(plain) is None
    assert BILIBILI.text not in plain and TERMS_BEGIN not in plain
    uploaded = compose_notices("", [clip("own", None, "b" * 64, source="uploaded")])
    assert player_terms(uploaded) is None

    mixed = compose_notices(
        "Written by me.",
        [
            clip("hi", "chatterbox-mit", "a" * 64),
            clip("cry", "bilibili-model-use", "c" * 64),
            clip("run", "bilibili-model-use", "d" * 64),
        ],
    )
    terms = player_terms(mixed)
    assert terms is not None and terms.startswith(BILIBILI.player_terms)
    assert BILIBILI.text in terms  # The agreement itself, readable in the game.
    assert mixed.count(BILIBILI.text) == 1
    assert "  " + BILIBILI.notice in mixed  # The per-clip attribution and disclaimer.
    assert mixed.startswith("Written by me.\n\n" + NOTICE_MARKER)
    assert mixed.endswith(TERMS_END + "\n")
    # Saving again recomposes the generated part instead of stacking it.
    assert compose_notices(mixed, [clip("hi", "chatterbox-mit", "a" * 64)]) == plain
    package = load_text_package(STORY, mixed.encode(), allow_asset_refs=True)
    assert player_terms(package.notices.decode()) == terms


def test_an_unknown_license_hash_on_a_clip_refuses_to_compose() -> None:
    forged = clip("x", "bilibili-model-use", "e" * 64)
    forged.asset.provenance["license"]["sha256"] = "0" * 64
    with pytest.raises(PackageError, match="NOTICES") as refused:
        compose_notices("", [forged])
    assert refused.value.code == "unknown_license"
