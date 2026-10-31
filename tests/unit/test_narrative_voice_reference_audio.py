import math
import struct

import pytest

from flint_graph.narrative.values import PackageError
from flint_graph.narrative.voice_references import ReferenceRefused, inspect_reference
from flint_graph.narrative.wav import canonical_wav


def speech(
    seconds: float, *, rate: int = 24000, amplitude: float = 0.3, channels: int = 1
) -> bytes:
    """A voice-like signal: a 180 Hz tone whose loudness rises and falls like syllables."""
    frames = round(seconds * rate)
    samples = []
    for index in range(frames):
        envelope = 0.5 + 0.5 * math.sin(2 * math.pi * 3 * index / rate)
        value = round(amplitude * envelope * math.sin(2 * math.pi * 180 * index / rate) * 32767)
        samples.extend([max(-32768, min(32767, value))] * channels)
    return canonical_wav(channels, rate, struct.pack(f"<{len(samples)}h", *samples))


def test_a_clear_reference_between_5_and_30_seconds_is_accepted_as_canonical_wav() -> None:
    reference = inspect_reference(speech(8))
    assert (reference.channels, reference.sample_rate) == (1, 24000)
    assert reference.duration_ms == 8000
    assert reference.data.startswith(b"RIFF") and len(reference.sha256) == 64
    stereo = inspect_reference(speech(6, rate=48000, channels=2))
    assert stereo.channels == 2 and stereo.duration_ms == 6000


def test_metadata_chunks_are_dropped_before_hashing() -> None:
    plain = speech(5.5)
    body = plain[12:]
    with_list = b"LIST" + struct.pack("<I", 4) + b"INFO"
    noisy = b"RIFF" + struct.pack("<I", 4 + len(with_list) + len(body)) + b"WAVE" + with_list + body
    assert inspect_reference(noisy).sha256 == inspect_reference(plain).sha256


@pytest.mark.parametrize(
    ("seconds", "amplitude", "code", "words"),
    [
        (3, 0.3, "too_short", "at least 5 seconds"),
        (31, 0.3, "too_long", "at most 30 seconds"),
        (8, 1.4, "clipped", "too loud"),
        (8, 0.002, "silent", "barely hear"),
    ],
    ids=["short", "long", "clipped", "silent"],
)
def test_unusable_references_are_refused_with_a_clear_reason(
    seconds, amplitude, code, words
) -> None:
    with pytest.raises(ReferenceRefused) as refused:
        inspect_reference(speech(seconds, amplitude=amplitude))
    assert refused.value.code == code
    assert words in str(refused.value)


def test_a_reference_that_is_mostly_silence_with_a_cough_is_refused() -> None:
    quiet = speech(10, amplitude=0.001)
    loud = speech(1.0, amplitude=0.5)
    header, cough = quiet[:44], loud[44:]
    samples = quiet[44 : 44 + len(quiet) - 44 - len(cough)] + cough
    data = canonical_wav(1, 24000, samples)
    assert header[:4] == b"RIFF"
    with pytest.raises(ReferenceRefused, match="barely hear"):
        inspect_reference(data)


def test_non_pcm_input_is_not_a_reference() -> None:
    with pytest.raises(PackageError):
        inspect_reference(b"OggS" + bytes(100))
