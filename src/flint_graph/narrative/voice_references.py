"""Voice reference samples: the audio a cloned voice is made from (#175, ADR 0044).

A reference is private project data, never a story asset. It is stored in the same
canonical 16-bit PCM WAV form as voice clips (ADR 0043) so the hash names exactly the
samples a model heard, and it must be usable: 5 to 30 seconds long, not clipped and
not near silence. Who speaks in it and whether they agreed is declared by the
creator and recorded with it, not verified.
"""

import hashlib
import math
from array import array
from dataclasses import dataclass

from flint_graph.narrative.wav import normalize_wav, validate_wav

MIN_SECONDS = 5
MAX_SECONDS = 30
# A sample at full scale; more than 0.1 % of them means the input was clipped.
CLIPPED_SHARE = 0.001
# 50 ms windows louder than -40 dBFS count as heard; a reference needs 2 s of them.
WINDOW_SECONDS = 0.05
HEARD_RMS = 0.01
HEARD_SECONDS = 2.0
CONSENTS = ("self", "permission")


class ReferenceRefused(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True)
class ReferenceAudio:
    data: bytes
    sha256: str
    channels: int
    sample_rate: int
    frames: int

    @property
    def duration_ms(self) -> int:
        return round(self.frames * 1000 / self.sample_rate)


def inspect_reference(data: bytes) -> ReferenceAudio:
    """The canonical form of a usable reference, or ``ReferenceRefused`` saying why."""
    canonical = normalize_wav(data, "reference")
    info = validate_wav(canonical, "reference")
    seconds = info.frames / info.sample_rate
    if seconds < MIN_SECONDS:
        raise ReferenceRefused(
            "too_short", f"A reference needs at least {MIN_SECONDS} seconds of speech."
        )
    if seconds > MAX_SECONDS:
        raise ReferenceRefused(
            "too_long", f"Keep the reference to at most {MAX_SECONDS} seconds; trim it first."
        )
    samples = array("h")
    samples.frombytes(canonical[44:])
    clipped = sum(1 for value in samples if value >= 32767 or value <= -32768)
    if clipped > CLIPPED_SHARE * len(samples):
        raise ReferenceRefused(
            "clipped",
            "The recording is clipped (too loud). Record again a little further from the "
            "microphone or lower its input level.",
        )
    window = max(1, round(WINDOW_SECONDS * info.sample_rate)) * info.channels
    heard = 0
    for start in range(0, len(samples) - window + 1, window):
        energy = sum(value * value for value in samples[start : start + window])
        if math.sqrt(energy / window) / 32768 >= HEARD_RMS:
            heard += 1
    if heard * WINDOW_SECONDS < HEARD_SECONDS:
        raise ReferenceRefused(
            "silent",
            "We could barely hear anyone. Record closer to the microphone in a quiet room.",
        )
    return ReferenceAudio(
        data=canonical,
        sha256=hashlib.sha256(canonical).hexdigest(),
        channels=info.channels,
        sample_rate=info.sample_rate,
        frames=info.frames,
    )
