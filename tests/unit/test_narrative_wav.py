"""Canonical 16-bit PCM WAV voice clips (ADR 0043)."""

import struct

import pytest

from flint_graph.narrative.values import PackageError
from flint_graph.narrative.wav import AUDIO_LIMIT, normalize_wav, validate_wav, wav_info


def chunk(kind: bytes, payload: bytes) -> bytes:
    return kind + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) % 2 else b"")


def fmt(channels=1, rate=24000, bits=16, tag=1, extra=b""):
    align = channels * bits // 8
    return struct.pack("<HHIIHH", tag, channels, rate, rate * align, align, bits) + extra


def wav(*chunks: bytes) -> bytes:
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def clip(frames=240, channels=1, rate=24000):
    return wav(chunk(b"fmt ", fmt(channels, rate)), chunk(b"data", b"\x01\x00" * frames * channels))


def test_canonical_clips_validate_and_report_their_shape():
    for channels, rate in ((1, 24000), (2, 48000), (1, 16000), (2, 44100), (1, 22050), (1, 32000)):
        data = clip(480, channels, rate)
        validate_wav(data, "assets.voice")
        info = wav_info(data)
        assert (info.channels, info.sample_rate, info.frames) == (channels, rate, 480)
        assert info.duration_ms == round(480 * 1000 / rate)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"RIFF" + struct.pack("<I", 4) + b"WAVE",
        clip()[:-1],  # Truncated data.
        clip() + b"\x00\x00",  # Trailing bytes after the data chunk.
        clip().replace(b"WAVE", b"AVI ", 1),
        clip().replace(b"RIFF", b"RIFX", 1),
        wav(chunk(b"fmt ", fmt(tag=3)), chunk(b"data", b"\x00" * 8)),  # Float samples.
        wav(chunk(b"fmt ", fmt(bits=8)), chunk(b"data", b"\x00" * 8)),
        wav(chunk(b"fmt ", fmt(channels=3)), chunk(b"data", b"\x00" * 12)),
        wav(chunk(b"fmt ", fmt(rate=11025)), chunk(b"data", b"\x00" * 8)),
        wav(chunk(b"fmt ", fmt()), chunk(b"data", b"")),  # No frames.
        wav(chunk(b"fmt ", fmt()), chunk(b"data", b"\x00\x00\x00")),  # Half a frame.
        wav(chunk(b"data", b"\x00" * 8), chunk(b"fmt ", fmt())),  # Data before format.
        wav(chunk(b"fmt ", fmt()), chunk(b"LIST", b"INFOxxxx"), chunk(b"data", b"\x00" * 8)),
        wav(chunk(b"fmt ", fmt(extra=b"\x00\x00")), chunk(b"data", b"\x00" * 8)),
        wav(chunk(b"fmt ", fmt()[:-2] + struct.pack("<H", 16)[:0]), chunk(b"data", b"\x00" * 8)),
    ],
)
def test_anything_but_the_canonical_form_is_refused(data):
    with pytest.raises(PackageError) as raised:
        validate_wav(data, "assets.voice")
    assert (raised.value.code, raised.value.location) == ("invalid_audio", "assets.voice")


def test_byte_rate_and_alignment_must_agree():
    broken = bytearray(clip())
    struct.pack_into("<I", broken, 28, 1)  # byte rate
    with pytest.raises(PackageError):
        validate_wav(bytes(broken), "x")
    broken = bytearray(clip())
    struct.pack_into("<H", broken, 32, 4)  # block align
    with pytest.raises(PackageError):
        validate_wav(bytes(broken), "x")


def test_clips_are_bounded_by_duration_and_size():
    validate_wav(clip(60 * 24000), "x")
    with pytest.raises(PackageError):
        validate_wav(clip(60 * 24000 + 1), "x")
    with pytest.raises(PackageError):
        validate_wav(clip(AUDIO_LIMIT // 2), "x")


def test_uploads_are_rewritten_losslessly_into_the_canonical_form():
    samples = struct.pack("<4h", 1, -2, 300, -400)
    canonical = wav(chunk(b"fmt ", fmt(2, 44100)), chunk(b"data", samples))
    noisy = wav(
        chunk(b"fmt ", fmt(2, 44100, extra=b"\x00\x00")),
        chunk(b"LIST", b"INFOISFT\x05\x00\x00\x00Lavf\x00"),
        chunk(b"fact", struct.pack("<I", 2)),
        chunk(b"data", samples),
        chunk(b"id3 ", b"tag"),
    )
    assert normalize_wav(noisy, "file") == canonical
    pcm_guid = bytes.fromhex("0100000000001000800000aa00389b71")
    extensible = wav(
        chunk(
            b"fmt ",
            fmt(2, 44100, tag=0xFFFE, extra=struct.pack("<HHI", 22, 16, 3) + pcm_guid),
        ),
        chunk(b"data", samples),
    )
    assert normalize_wav(extensible, "file") == canonical
    assert normalize_wav(canonical, "file") == canonical
    float_guid = bytes.fromhex("0300000000001000800000aa00389b71")
    with pytest.raises(PackageError):
        normalize_wav(
            wav(
                chunk(b"fmt ", fmt(tag=0xFFFE, extra=struct.pack("<HHI", 22, 16, 4) + float_guid)),
                chunk(b"data", samples),
            ),
            "file",
        )
    with pytest.raises(PackageError):
        normalize_wav(b"ID3\x04" + b"\x00" * 64, "file")  # An MP3 is not a WAV.
