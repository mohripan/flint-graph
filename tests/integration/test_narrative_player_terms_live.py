"""Opt-in real Godot qualification of the player license screen (ADR 0044, runtime 0.7.0)."""

import base64
import json
import os
from pathlib import Path

import pytest
from test_narrative_godot_live import native_ui_probe
from test_narrative_line_voices_live import voice_package
from test_narrative_preview_live import probe

from flint_graph.narrative import load_package
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.player_terms import NOTICE_MARKER, TERMS_BEGIN, TERMS_END, player_terms
from flint_graph.narrative.values import PackageError

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures/narrative/player_terms.json").read_text("utf-8")
)
engine = pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_GODOT_BIN"), reason="Explicit pinned Godot required"
)
TERMS = "Players agree to these terms.\n\nThe agreement follows."
NOTICES = (
    "Original voice fixture. CC0.\n\n"
    f"{NOTICE_MARKER}\nhello (audio, sha256 cccc)\nlicense: bilibili Model Use License Agreement\n"
    f"source: generated with IndexTeam/IndexTTS-2.5@c39c\n\n{TERMS_BEGIN}\n{TERMS}\n{TERMS_END}\n"
)


def expand(text: str) -> str:
    markers = FIXTURE["markers"]
    return (
        text.replace("{notices}", markers["notices"])
        .replace("{begin}", markers["begin"])
        .replace("{end}", markers["end"])
    )


def terms_package(tmp_path: Path):
    _, files = voice_package(tmp_path)
    source = tmp_path / "source"
    (source / "NOTICES.txt").write_text(NOTICES, encoding="utf-8", newline="\n")
    return load_package(source), files


@engine
def test_actual_runtime_parses_the_shared_player_terms_cases(tmp_path):
    package, _ = voice_package(tmp_path)
    notices = [expand(case["notices"]) for case in FIXTURE["cases"]]
    actual = native_ui_probe(tmp_path, "terms_parse", package, {"notices": notices})
    for case, result in zip(FIXTURE["cases"], actual, strict=True):
        if "error" in case:
            assert result == {"ok": False, "terms": None}, case["name"]
        else:
            assert result == {"ok": True, "terms": case["terms"]}, case["name"]


@engine
def test_actual_preview_refuses_malformed_terms_and_accepts_good_ones(tmp_path):
    package, files = terms_package(tmp_path)
    cases = []
    for notices, valid in [
        (NOTICES, True),
        (NOTICES.replace(TERMS_END + "\n", ""), False),
        (NOTICES + "Trailing words.\n", False),
    ]:
        raw = package.canonical_story
        if valid:
            identity = load_text_package(raw, notices.encode(), allow_asset_refs=True).content_hash
        else:
            with pytest.raises(PackageError):
                load_text_package(raw, notices.encode(), allow_asset_refs=True)
            identity = package.content_hash
        cases.append(
            {
                "source": base64.b64encode(raw).decode(),
                "notices": base64.b64encode(notices.encode()).decode(),
                "hash": identity,
                "assets": {key: base64.b64encode(data).decode() for key, data in files.items()},
                "valid": valid,
            }
        )
    assert probe(tmp_path, cases) == [True, False, False]


@engine
@pytest.mark.parametrize("preview", [False, True], ids=["release_persistent", "preview_memory"])
def test_actual_license_screen_holds_the_story_until_accepted(tmp_path, preview):
    package, _ = terms_package(tmp_path)
    assert player_terms(NOTICES) == TERMS
    changed = NOTICES.replace("these terms", "new terms")
    launches = native_ui_probe(
        tmp_path,
        "terms_preview" if preview else "terms",
        package,
        {"changed_notices": changed},
        frames=120,
    )
    first = launches[0]
    assert first["open"] and first["required"] and first["license_button"]
    assert first["playing"] is False  # The first line's voice waits for the agreement.
    assert first["still_open"] and first["same_line"]  # Clicks, Enter and Escape do not pass.
    assert first["text"] == TERMS and first["button"] == "I agree"
    assert first["accepted"] == {"open": False, "clip": "hello", "playing": True}
    for launch in launches:
        assert launch["reread"] == {"open": True, "required": False, "button": "Close license"}
        assert launch["escape_closes_reread"]
    # Exports keep the acceptance per story and terms text; playtests always ask again.
    assert launches[1]["open"] is (True if preview else False)
    assert launches[2]["open"] is True  # Changed terms ask again.
    assert first["stored"] is not preview and launches[2]["stored"] is not preview
