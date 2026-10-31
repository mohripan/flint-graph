"""Canonical 16-bit PCM WAV for voice clips (ADR 0043).

A story ships audio only in one exact form: ``RIFF``/``WAVE`` with a 16-byte
``fmt `` chunk (PCM, one or two channels, a common sample rate, 16 bits) followed by
one ``data`` chunk that ends the file. The Godot runtime parses the same form, so a
file either plays identically everywhere or is refused. Uploads may carry metadata
chunks, an 18-byte format or ``WAVE_FORMAT_EXTENSIBLE`` with the PCM subformat;
``normalize_wav`` rewrites those losslessly before anything is hashed.
"""

import struct
from dataclasses import dataclass

from flint_graph.narrative.values import PackageError

AUDIO_LIMIT = 10 * 1024 * 1024
MAX_SECONDS = 60
SAMPLE_RATES = (16000, 22050, 24000, 32000, 44100, 48000)
_PCM_GUID = bytes.fromhex("0100000000001000800000aa00389b71")
_CANONICAL_HEADER = 44


@dataclass(frozen=True)
class WavInfo:
    channels: int
    sample_rate: int
    frames: int

    @property
    def duration_ms(self) -> int:
        return round(self.frames * 1000 / self.sample_rate)


def _refuse(location: str) -> PackageError:
    return PackageError("invalid_audio", location)


def _format(payload: bytes, location: str, *, lenient: bool) -> tuple[int, int]:
    if len(payload) < 16:
        raise _refuse(location)
    tag, channels, rate, byte_rate, align, bits = struct.unpack("<HHIIHH", payload[:16])
    if lenient and tag == 0xFFFE and len(payload) == 40:
        size, valid_bits, _mask = struct.unpack("<HHI", payload[16:24])
        if size != 22 or valid_bits != 16 or payload[24:40] != _PCM_GUID:
            raise _refuse(location)
        tag = 1
    elif lenient and len(payload) == 18 and payload[16:18] == b"\x00\x00":
        pass
    elif len(payload) != 16:
        raise _refuse(location)
    if (
        tag != 1
        or channels not in (1, 2)
        or rate not in SAMPLE_RATES
        or bits != 16
        or align != channels * 2
        or byte_rate != rate * align
    ):
        raise _refuse(location)
    return channels, rate


def _chunks(data: bytes, location: str) -> list[tuple[bytes, bytes]]:
    if (
        len(data) < 12
        or data[:4] != b"RIFF"
        or data[8:12] != b"WAVE"
        or struct.unpack("<I", data[4:8])[0] != len(data) - 8
    ):
        raise _refuse(location)
    chunks, offset = [], 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise _refuse(location)
        kind = data[offset : offset + 4]
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        end = offset + 8 + size
        if end > len(data):
            raise _refuse(location)
        chunks.append((kind, data[offset + 8 : end]))
        offset = end + (size % 2)
    if offset != len(data):
        raise _refuse(location)
    return chunks


def _bounded(channels: int, rate: int, samples: bytes, location: str) -> WavInfo:
    frames, partial = divmod(len(samples), channels * 2)
    if not samples or partial or frames > rate * MAX_SECONDS:
        raise _refuse(location)
    return WavInfo(channels, rate, frames)


def validate_wav(data: bytes, location: str) -> WavInfo:
    """Accept exactly the canonical form, within the size and duration caps."""
    if type(data) is not bytes or len(data) > AUDIO_LIMIT or len(data) < _CANONICAL_HEADER + 2:
        raise _refuse(location)
    chunks = _chunks(data, location)
    if len(chunks) != 2 or chunks[0][0] != b"fmt " or chunks[1][0] != b"data":
        raise _refuse(location)
    channels, rate = _format(chunks[0][1], location, lenient=False)
    if len(chunks[1][1]) % 2:
        raise _refuse(location)  # A pad byte would follow; 16-bit frames never need one.
    return _bounded(channels, rate, chunks[1][1], location)


def wav_info(data: bytes) -> WavInfo:
    return validate_wav(data, "audio")


def canonical_wav(channels: int, rate: int, samples: bytes) -> bytes:
    align = channels * 2
    header = struct.pack("<HHIIHH", 1, channels, rate, rate * align, align, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + header
    body += b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(body)) + body


def normalize_wav(data: bytes, location: str) -> bytes:
    """Keep the format and samples, drop every other chunk; validate the result."""
    if type(data) is not bytes or len(data) > AUDIO_LIMIT:
        raise _refuse(location)
    chunks = _chunks(data, location)
    formats = [payload for kind, payload in chunks if kind == b"fmt "]
    datas = [index for index, (kind, _) in enumerate(chunks) if kind == b"data"]
    if len(formats) != 1 or len(datas) != 1:
        raise _refuse(location)
    if next(index for index, (kind, _) in enumerate(chunks) if kind == b"fmt ") > datas[0]:
        raise _refuse(location)
    channels, rate = _format(formats[0], location, lenient=True)
    samples = chunks[datas[0]][1]
    _bounded(channels, rate, samples, location)
    result = canonical_wav(channels, rate, samples)
    validate_wav(result, location)
    return result
