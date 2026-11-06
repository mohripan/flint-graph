"""Ogg Vorbis music (ADR 0066): one whole, bounded Vorbis stream.

This checks the container and the identification header without decoding. A SHA-256 already
guards the bytes in a package, so page checksums are left to the decoder, which every player has.
"""

import struct
from dataclasses import dataclass

from flint_graph.narrative.values import PackageError

MUSIC_LIMIT = 10 * 1024 * 1024
MAX_SECONDS = 600
RATES = frozenset({22050, 32000, 44100, 48000})
_HEADER = struct.Struct("<4sBBqIIIB")
_BEGIN, _END = 0x02, 0x04


@dataclass(frozen=True)
class OggInfo:
    channels: int
    rate: int
    duration_ms: int


def validate_ogg(data: bytes, location: str) -> OggInfo:
    """What the file holds, or ``invalid_music`` if it is not one whole Vorbis stream."""

    def invalid() -> PackageError:
        return PackageError("invalid_music", location)

    if type(data) is not bytes or not 0 < len(data) <= MUSIC_LIMIT:
        raise invalid()
    at, number = 0, 0
    serial: int | None = None
    channels = rate = granule = 0
    ended = False
    while at < len(data):
        if ended or at + _HEADER.size > len(data):
            raise invalid()
        magic, version, flags, position, stream, sequence, _, segments = _HEADER.unpack_from(
            data, at
        )
        if magic != b"OggS" or version != 0 or flags & ~0x07:
            raise invalid()
        body = at + _HEADER.size + segments
        if body > len(data):
            raise invalid()
        size = sum(data[at + _HEADER.size : body])
        if body + size > len(data):
            raise invalid()
        if number == 0:
            # The identification packet: alone on the first page, with these exact fields.
            if not flags & _BEGIN or size != 30 or data[body : body + 7] != b"\x01vorbis":
                raise invalid()
            codec, channels, rate = struct.unpack_from("<IBI", data, body + 7)
            if codec != 0 or channels not in (1, 2) or rate not in RATES:
                raise invalid()
            serial = stream
        elif flags & _BEGIN or stream != serial:
            raise invalid()  # A second stream in the same file.
        if sequence != number:
            raise invalid()
        if position != -1:
            if position < granule:
                raise invalid()
            granule = position
        ended = bool(flags & _END)
        at, number = body + size, number + 1
    if not ended or number < 2 or granule <= 0 or granule > MAX_SECONDS * rate:
        raise invalid()
    return OggInfo(channels, rate, round(granule * 1000 / rate))


def ogg_info(data: bytes) -> OggInfo:
    return validate_ogg(data, "music")
