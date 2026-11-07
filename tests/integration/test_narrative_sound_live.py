"""Opt-in real Godot qualification of music, ambience and effects (ADR 0066, runtime 0.10.0)."""

import hashlib
import io
import json
import os
import struct
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from test_narrative_godot_live import native_probe, native_ui_probe, stage_png

from flint_graph.infrastructure.narrative_builder import DockerNarrativeBuilder
from flint_graph.narrative import Player, load_package
from flint_graph.narrative.values import canonical_json
from flint_graph.narrative.wav import canonical_wav

engine = pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_GODOT_BIN"), reason="Explicit pinned Godot required"
)
AUDIO = Path(__file__).parents[1] / "fixtures/narrative/audio"


def line(key, text, target, **extra):
    return {"type": "line", "text_id": key, "text": text, "next": target, **extra}


def sound_package(tmp_path, theme=None):
    """A story that starts music, adds ambience, switches track, plays an effect and stops."""
    bell = canonical_wav(1, 24000, struct.pack("<h", 900) * 24000)
    files = {
        "theme": ((AUDIO / "tone_a.ogg").read_bytes(), "music", "ogg"),
        "rain": ((AUDIO / "tone_b.ogg").read_bytes(), "music", "ogg"),
        "bell": (bell, "audio", "wav"),
        "dusk": (stage_png(10), "image", "png"),
    }
    story = {
        "schema_version": "2",
        "id": "harbor_sound",
        "title": "Original sound fixture",
        "language": "en",
        "entry": "s0",
        "characters": {"mira": {"name": "Mira"}},
        "variables": {},
        "assets": {
            key: {
                "kind": kind,
                "path": f"assets/{key}.{extension}",
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for key, (data, kind, extension) in files.items()
        },
        "nodes": {
            "s0": {"type": "stage", "background": "dusk", "music": "theme", "next": "l0"},
            "l0": line("l0", "Music starts.", "s1"),
            "s1": {"type": "stage", "ambience": "rain", "next": "l1"},
            "l1": line("l1", "Rain joins it.", "s2"),
            "s2": {"type": "stage", "music": "rain", "sound": "bell", "next": "l2"},
            "l2": line("l2", "The track changes and a bell rings.", "s3"),
            "s3": {"type": "stage", "music": None, "ambience": None, "next": "l3"},
            "l3": line("l3", "Silence.", "e1"),
            "e1": {"type": "end", "text_id": "e1", "text": "Fin.", "ending": "done"},
        },
    }
    if theme is not None:
        story["theme"] = theme
    source = tmp_path / "source"
    (source / "assets").mkdir(parents=True)
    (source / "story.json").write_bytes(canonical_json(story))
    (source / "NOTICES.txt").write_bytes(b"Original sound fixture. CC0.\n")
    for key, (data, _, extension) in files.items():
        (source / "assets" / f"{key}.{extension}").write_bytes(data)
    return load_package(source)


@engine
def test_real_godot_tracks_what_is_playing_exactly_like_the_reference(tmp_path) -> None:
    package = sound_package(tmp_path)
    actions = ["advance", "advance", "advance"]
    actual = native_probe(package, tmp_path, {"actions": actions, "save_after": 1})
    reference = Player(package)
    frames = [reference.frame()]
    for action in actions:
        reference.act(action)
        frames.append(reference.frame(action))
    assert actual["frames"] == frames
    assert actual["state"] == reference.state
    assert actual["restore_error"] == ""
    # The native save loads in the reference player and means the same thing there.
    restored = Player(package)
    restored.load_save(actual["save"].encode())
    assert restored.state["stage"]["music"] == "theme"
    assert restored.state["stage"]["ambience"] == "rain"


@engine
def test_real_sound_plays_changes_and_comes_back_from_a_save(tmp_path) -> None:
    package = sound_package(tmp_path)
    result = native_ui_probe(tmp_path, "sound", package, frames=3000)

    # Real Vorbis bytes decode, and the first screen's track starts by itself.
    assert result["opening"] == {"music": "theme", "playing": True, "ambience": None}
    # Ambience joins without disturbing the music.
    assert result["ambience"] == {"music": "theme", "ambience": "rain", "fading": False}
    # A new track crossfades: both are audible, then only the new one.
    assert result["crossfade"]["music"] == "rain"
    assert result["crossfade"]["both_during"] == 2
    assert result["crossfade"]["one_after"] == 1
    # A sound effect plays once, on arrival.
    assert result["effect"] == {"played": True, "replayed_on_settle": False}
    # Null stops both.
    assert result["silence"] == {"music": None, "ambience": None, "playing": False}
    # A save restores what was playing, at once.
    assert result["load"] == {
        "music": "theme",
        "ambience": "rain",
        "fading": False,
        "playing": True,
    }
    # Restart begins again from the opening track.
    assert result["restart"] == {"music": "theme", "ambience": None}
    # Skipping switches instantly and stays out of the way of effects.
    assert result["skip"] == {"fading": False, "effect_played": False, "music": "theme"}
    # Volumes and mute apply and persist.
    assert result["volumes"]["quieter"] is True
    assert result["volumes"]["muted_is_silent"] is True
    assert result["volumes"]["voice_muted_too"] is True
    assert result["volumes"]["stored"]["music_volume"] == 30
    assert result["volumes"]["stored"]["muted"] is True
    assert result["volumes"]["m_key_toggles"] is False


@engine
def test_real_sound_waits_for_a_browser_that_may_not_start_it(tmp_path) -> None:
    package = sound_package(tmp_path)
    result = native_ui_probe(tmp_path, "sound_gate", package, frames=400)
    assert result["gate_shown"] is True
    assert result["label"].endswith("This story has sound.")
    assert result["before"] == {"music": None, "playing": False}
    assert result["after"] == {"music": "theme", "playing": True, "same_line": True}


@engine
def test_real_playtest_sound_settings_stay_in_memory(tmp_path) -> None:
    package = sound_package(tmp_path)
    result = native_ui_probe(tmp_path, "sound_preview", package, frames=400)
    assert result["music"] == "theme"
    assert result["files_written"] == []


@pytest.mark.anyio
async def test_actual_linux_release_build_carries_music(tmp_path) -> None:
    image, pin = (
        os.getenv("FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE"),
        os.getenv("FLINT_GRAPH_NARRATIVE_BUILDER_TOOLCHAIN"),
    )
    if not image or not pin:
        pytest.skip("Explicit owned builder required")
    package = sound_package(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    runner = DockerNarrativeBuilder(image=image, toolchain_sha256=pin, work_root=scratch)

    async def current():
        pass

    result = await runner.build(package, execution_id=uuid4(), check=current)
    theme = (AUDIO / "tone_a.ogg").read_bytes()
    with ZipFile(io.BytesIO(result.source_zip)) as source:
        assert json.loads(source.read("build-manifest.json"))["runtime_version"] == "0.12.0"
        assert source.read("content/assets/theme.ogg") == theme
        assert "runtime/sound_channel.gd" in source.namelist()
    with ZipFile(io.BytesIO(result.web_zip)) as web:
        pack = web.read("index.pck")
    # The file reached the exported game itself, not only the source download.
    assert theme[:64] in pack

