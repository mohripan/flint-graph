"""The music child's protocol and the parent's distrust of it (ADR 0067). No GPU needed."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from flint_graph.infrastructure.narrative_imagegen import ModelIdentity
from flint_graph.infrastructure.narrative_musicgen import (
    LocalMusicGenerator,
    MusicGenerationError,
    MusicRequest,
    collect,
)

ROOT = Path(__file__).parents[2]
AUDIO = ROOT / "tests/fixtures/narrative/audio"
TONE = (AUDIO / "tone_a.ogg").read_bytes()  # Two seconds.
LOADED = {"runtime": {"torch": "2.11", "cuda": "12.8", "device": "GPU"}}


def child():
    script = ROOT / "runtimes/musicgen/generate.py"
    spec = importlib.util.spec_from_file_location("musicgen", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(seconds=15):
    return MusicRequest(description="calm piano", seconds=seconds, seed=7)


# ---- The join that lets a track loop -------------------------------------------------------


def test_the_end_of_a_track_leads_into_its_start():
    np = pytest.importorskip("numpy")
    rate = 1000
    module = child()
    data = np.ones((rate * 10, 2), dtype="float32")
    data[:, 0] = np.linspace(-1, 1, len(data))
    looped = module.seamless_loop(data, rate, seconds=2.0)
    # Shorter by the overlap, and the seam between last and first is where the old middle was.
    assert len(looped) == rate * 8
    assert looped[-1][0] == pytest.approx(data[-2001][0], abs=1e-3)
    # It starts from the old end, so looping continues what was playing.
    assert looped[0][0] == pytest.approx(data[-2000][0], abs=1e-3)
    assert looped[1999][0] == pytest.approx(data[1999][0], abs=1e-3)


def test_equal_power_keeps_the_level_through_the_join():
    np = pytest.importorskip("numpy")
    rate = 1000
    generator = np.random.default_rng(1)
    data = generator.normal(0, 0.2, (rate * 10, 2)).astype("float32")
    joined = child().seamless_loop(data, rate, seconds=2.0)[:2000]
    assert np.sqrt(np.mean(joined**2)) == pytest.approx(np.sqrt(np.mean(data**2)), rel=0.08)


def test_too_short_a_track_is_left_alone():
    np = pytest.importorskip("numpy")
    data = np.zeros((1000, 2), dtype="float32")
    assert child().seamless_loop(data, 1000, seconds=2.0) is data


# ---- What the parent accepts ------------------------------------------------------------


def output(tmp_path, files):
    folder = tmp_path / "out"
    folder.mkdir()
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


def test_a_real_vorbis_track_of_the_right_length_is_accepted(tmp_path):
    result = collect(output(tmp_path, {"0.ogg": TONE}), LOADED, MusicRequest("x", 4, 1))
    assert result.track.duration_ms == 2000
    assert (result.track.channels, result.track.rate) == (2, 44100)
    assert result.runtime["device"] == "GPU"


@pytest.mark.parametrize(
    ("files", "seconds"),
    [
        ({}, 4),
        ({"0.ogg": b"not audio"}, 4),
        ({"0.ogg": TONE[:500]}, 4),
        ({"0.ogg": TONE, "extra.wav": b"x"}, 4),
        ({"other.ogg": TONE}, 4),
        ({"0.ogg": TONE}, 60),
    ],
    ids=["nothing", "not-audio", "cut-short", "extra-file", "wrong-name", "wrong-length"],
)
def test_anything_else_the_child_leaves_is_refused(tmp_path, files, seconds):
    with pytest.raises(MusicGenerationError, match="invalid_output"):
        collect(output(tmp_path, files), LOADED, MusicRequest("x", seconds, 1))


@pytest.mark.parametrize(
    "runtime", [None, {}, {"torch": "1", "cuda": "1"}, {"torch": 1, "cuda": "1", "device": "x"}]
)
def test_a_malformed_runtime_report_is_refused(tmp_path, runtime):
    with pytest.raises(MusicGenerationError, match="invalid_output"):
        collect(output(tmp_path, {"0.ogg": TONE}), {"runtime": runtime}, MusicRequest("x", 4, 1))


# ---- The protocol, against a scripted child ------------------------------------------------

SCRIPT = """
import json, os, sys
request = json.load(sys.stdin)
def emit(**fields):
    print(json.dumps({"protocol": 1, **fields}), flush=True)
behaviour = request["description"]
if behaviour == "fails":
    emit(event="error", code="gpu_busy")
    sys.exit(1)
if behaviour == "unknown":
    emit(event="error", code="something_else")
    sys.exit(1)
if behaviour == "noise":
    print("not json", flush=True)
    sys.exit(0)
if behaviour == "crashes":
    sys.exit(3)
if behaviour == "hangs":
    import time
    time.sleep(60)
if behaviour == "secret":
    assert "SECRET_SETTING" not in os.environ
emit(event="loaded", runtime={"torch": "2", "cuda": "12", "device": "GPU"})
source = os.environ["TEMP"] + "/../"
import shutil
shutil.copyfile(sys.argv[1] if len(sys.argv) > 1 else "TONE", request["output_dir"] + "/0.ogg")
emit(event="track", file="0.ogg", frames=1, rate=44100, device="gpu")
emit(event="done")
"""


def generator(tmp_path, deadline=30):
    script = tmp_path / "generate.py"
    script.write_text(SCRIPT.replace('"TONE"', repr(str(AUDIO / "tone_a.ogg"))), encoding="utf-8")
    return LocalMusicGenerator(
        python=Path(sys.executable),
        script=script,
        model_dir=tmp_path,
        model=ModelIdentity("ACE-Step/ACE-Step-v1-3.5B", "abc", "apache-2.0"),
        deadline_seconds=deadline,
    )


def run(tmp_path, description, seconds=15, deadline=30):
    progress: list[int] = []

    async def note(done: int) -> None:
        progress.append(done)

    return (
        asyncio.run(
            generator(tmp_path, deadline).generate(
                MusicRequest(description, seconds, 1), on_progress=note
            )
        ),
        progress,
    )


def test_a_clean_run_reports_progress_and_the_track(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "flint_graph.infrastructure.narrative_musicgen._LENGTH_SLACK_MS", 20000, raising=True
    )
    result, progress = run(tmp_path, "calm")
    assert progress == [1]
    assert result.track.data == TONE


@pytest.mark.parametrize(
    ("description", "code"),
    [
        ("fails", "gpu_busy"),
        ("unknown", "generation_failed"),
        ("noise", "invalid_output"),
        ("crashes", "generation_failed"),
    ],
)
def test_child_failures_become_safe_codes(tmp_path, description, code):
    with pytest.raises(MusicGenerationError) as raised:
        run(tmp_path, description)
    assert raised.value.code == code


def test_a_child_past_its_deadline_is_stopped(tmp_path):
    with pytest.raises(MusicGenerationError) as raised:
        run(tmp_path, "hangs", deadline=1)
    assert raised.value.code == "generation_timeout"


def test_settings_never_reach_the_child(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_SETTING", "postgres://user:password@host/db")
    monkeypatch.setattr(
        "flint_graph.infrastructure.narrative_musicgen._LENGTH_SLACK_MS", 20000, raising=True
    )
    result, _ = run(tmp_path, "secret")
    assert result.track.data == TONE


@pytest.mark.parametrize(
    ("description", "seconds"),
    [("", 30), ("   ", 30), ("x" * 501, 30), ("calm", 14), ("calm", 181)],
)
def test_bad_requests_never_start_a_child(tmp_path, description, seconds):
    with pytest.raises(MusicGenerationError) as raised:
        run(tmp_path, description, seconds=seconds)
    assert raised.value.code == "bad_request"


def test_the_child_rejects_requests_the_parent_would_never_send(tmp_path, capsys, monkeypatch):
    module = child()
    module._output = sys.stdout
    bad = {
        "protocol": 1,
        "model_dir": "x",
        "output_dir": "y",
        "description": "calm",
        "seconds": 5,
        "seed": 1,
        "steps": 60,
    }

    class Stdin:
        def __init__(self, data):
            import io

            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(sys, "stdin", Stdin(json.dumps(bad).encode()))
    with pytest.raises(module.ChildError, match=""):
        module.read_request()


def test_the_child_gets_a_username_of_its_own_and_not_the_real_one(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "the-real-person")
    generator = LocalMusicGenerator(
        python=tmp_path / "python",
        script=tmp_path / "generate.py",
        model_dir=tmp_path,
        model=None,
        deadline_seconds=60,
    )
    assert generator._environment(tmp_path)["USERNAME"] == "musicgen"

