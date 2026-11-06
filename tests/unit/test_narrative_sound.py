"""Music, ambience and sound effects (ADR 0066): the format, saves and the library's checks."""

import copy
import hashlib
import json
import struct
from pathlib import Path

import pytest

from flint_graph.application.services.narrative_asset_library import inspect_upload
from flint_graph.domain.errors import DomainError
from flint_graph.narrative import Player, PlayerError
from flint_graph.narrative.ogg import MAX_SECONDS, ogg_info, validate_ogg
from flint_graph.narrative.package import load_text_package
from flint_graph.narrative.validation import validate_story
from flint_graph.narrative.values import PackageError
from flint_graph.narrative.wav import canonical_wav

AUDIO = Path(__file__).parents[1] / "fixtures/narrative/audio"
STEREO = (AUDIO / "tone_a.ogg").read_bytes()
MONO = (AUDIO / "tone_b.ogg").read_bytes()


def sound_story(**stage):
    return {
        "schema_version": "2",
        "id": "harbor",
        "title": "Harbor",
        "language": "en",
        "entry": "open",
        "characters": {},
        "variables": {},
        "assets": {
            "theme": {"kind": "music", "path": "assets/theme.ogg", "sha256": "a" * 64},
            "rain": {"kind": "music", "path": "assets/rain.ogg", "sha256": "b" * 64},
            "bell": {"kind": "audio", "path": "assets/bell.wav", "sha256": "c" * 64},
            "dusk": {"kind": "image", "path": "assets/dusk.png", "sha256": "d" * 64},
        },
        "nodes": {
            "open": {"type": "stage", "music": "theme", "next": "first", **stage},
            "first": {"type": "line", "text_id": "first", "text": "One.", "next": "change"},
            "change": {"type": "stage", "music": "rain", "ambience": "rain", "next": "second"},
            "second": {"type": "line", "text_id": "second", "text": "Two.", "next": "quiet"},
            "quiet": {"type": "stage", "music": None, "sound": "bell", "next": "third"},
            "third": {"type": "line", "text_id": "third", "text": "Three.", "next": "end"},
            "end": {"type": "end", "text_id": "end", "text": "Fin.", "ending": "done"},
        },
    }


def play(source):
    return Player(load_text_package(json.dumps(source).encode(), allow_asset_refs=True))


# ---- The Ogg Vorbis check ----------------------------------------------------------------


def test_real_vorbis_files_report_what_they_hold():
    stereo = ogg_info(STEREO)
    assert (stereo.channels, stereo.rate) == (2, 44100)
    assert stereo.duration_ms == 2000
    mono = ogg_info(MONO)
    assert (mono.channels, mono.rate) == (1, 22050)
    assert mono.duration_ms > 0


def pages(data):
    """(start, end) of each Ogg page."""
    found, at = [], 0
    while at < len(data):
        count = data[at + 26]
        size = 27 + count + sum(data[at + 27 : at + 27 + count])
        found.append((at, at + size))
        at += size
    return found


@pytest.mark.parametrize(
    "broken",
    [
        b"",
        b"not an ogg file at all",
        STEREO[:100],
        STEREO[:-1],
        STEREO + b"trailing",
        b"RIFF" + STEREO[4:],
    ],
    ids=["empty", "text", "cut-short", "last-byte-missing", "trailing-bytes", "wrong-magic"],
)
def test_anything_that_is_not_one_whole_vorbis_stream_is_refused(broken):
    with pytest.raises(PackageError) as raised:
        validate_ogg(broken, "assets.theme")
    assert (raised.value.code, raised.value.location) == ("invalid_music", "assets.theme")


def test_another_codec_in_an_ogg_file_is_refused():
    start = STEREO.index(b"\x01vorbis")
    opus = bytearray(STEREO)
    opus[start : start + 7] = b"OpusHea"
    with pytest.raises(PackageError, match="invalid_music"):
        validate_ogg(bytes(opus), "file")


def test_a_stream_that_never_ends_is_refused():
    start, _ = pages(STEREO)[-1]
    unfinished = bytearray(STEREO)
    unfinished[start + 5] &= ~0x04  # Clears the end-of-stream flag.
    with pytest.raises(PackageError, match="invalid_music"):
        validate_ogg(bytes(unfinished), "file")


def test_two_streams_in_one_file_are_refused():
    start, _ = pages(STEREO)[-1]
    mixed = bytearray(STEREO)
    mixed[start + 14] ^= 0xFF  # Another stream's serial number.
    with pytest.raises(PackageError, match="invalid_music"):
        validate_ogg(bytes(mixed), "file")


def test_a_track_longer_than_the_limit_is_refused():
    start, _ = pages(STEREO)[-1]
    long = bytearray(STEREO)
    struct.pack_into("<q", long, start + 6, (MAX_SECONDS + 1) * 44100)
    with pytest.raises(PackageError, match="invalid_music"):
        validate_ogg(bytes(long), "file")


# ---- The story format ------------------------------------------------------------------


def test_music_ambience_and_sound_are_valid_stage_fields():
    validate_story(sound_story())


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("music", "nope", "unknown_reference"),
        ("music", "bell", "invalid_asset_kind"),
        ("music", "dusk", "invalid_asset_kind"),
        ("ambience", "bell", "invalid_asset_kind"),
        ("sound", "theme", "invalid_asset_kind"),
        ("sound", "nope", "unknown_reference"),
        ("sound", None, "invalid_id"),
        ("music", 3, "invalid_id"),
    ],
)
def test_sound_fields_name_the_right_kind_of_file(field, value, code):
    with pytest.raises(PackageError) as raised:
        validate_story(sound_story(**{field: value}))
    assert raised.value.code == code
    assert raised.value.location == f"nodes.open.{field}"


def test_music_files_keep_their_shape():
    source = sound_story()
    source["assets"]["theme"]["path"] = "assets/theme.wav"
    with pytest.raises(PackageError, match="unsafe_path"):
        validate_story(source)


def test_a_sound_field_is_a_real_stage_step_by_itself():
    source = sound_story()
    source["nodes"]["open"] = {"type": "stage", "sound": "bell", "next": "first"}
    validate_story(source)


def test_format_1_has_no_music():
    source = sound_story()
    source["schema_version"] = "1"
    with pytest.raises(PackageError):
        validate_story(source)


# ---- The reference player --------------------------------------------------------------


def test_music_and_ambience_carry_on_until_changed_and_null_stops_them():
    player = play(sound_story())
    assert player.view["stage"]["music"] == "theme"
    assert "ambience" not in player.view["stage"]
    player.act("advance")
    assert player.view["stage"]["music"] == "rain"
    assert player.view["stage"]["ambience"] == "rain"
    player.act("advance")
    assert "music" not in player.view["stage"]
    assert player.view["stage"]["ambience"] == "rain"


def test_a_sound_effect_plays_on_arrival_only():
    player = play(sound_story())
    assert player.view["sound"] is None
    player.act("advance")
    player.act("advance")
    assert player.view["sound"] == "bell"
    saved = player.save()
    player.load_save(saved)
    assert player.view["sound"] is None


def test_a_story_without_sound_saves_exactly_as_before():
    source = sound_story()
    source["nodes"]["open"] = {"type": "stage", "background": "dusk", "next": "first"}
    source["nodes"]["first"]["next"] = "end"
    saved = json.loads(play(source).save())
    assert set(saved["stage"]) == {"background", "cg", "characters"}


def test_what_is_playing_is_restored_from_a_save():
    player = play(sound_story())
    player.act("advance")
    saved = player.save()
    assert json.loads(saved)["stage"]["music"] == "rain"
    player.act("advance")
    player.load_save(saved)
    assert player.view["stage"]["music"] == "rain"
    assert player.view["stage"]["ambience"] == "rain"


def test_a_save_from_before_music_loads_with_silence():
    player = play(sound_story())
    saved = json.loads(player.save())
    del saved["stage"]["music"]
    player.load_save(json.dumps(saved, sort_keys=True, separators=(",", ":")).encode())
    assert "music" not in player.view["stage"]


@pytest.mark.parametrize("field", ["music", "ambience"])
@pytest.mark.parametrize("value", ["nope", "bell", "dusk", 3])
def test_a_save_naming_the_wrong_file_is_refused(field, value):
    player = play(sound_story())
    saved = json.loads(player.save())
    saved["stage"][field] = value
    before = copy.deepcopy(player.state)
    with pytest.raises(PlayerError):
        player.load_save(json.dumps(saved, sort_keys=True, separators=(",", ":")).encode())
    assert player.state == before


# ---- The library -----------------------------------------------------------------------


def test_the_library_keeps_vorbis_music_exactly_as_uploaded():
    upload = inspect_upload("music", STEREO)
    assert upload.media_type == "audio/ogg"
    assert upload.data == STEREO
    assert upload.sha256 == hashlib.sha256(STEREO).hexdigest()
    assert upload.duration_ms == 2000
    assert (upload.width, upload.height) == (None, None)


def test_the_library_says_what_to_upload_for_music():
    with pytest.raises(DomainError, match="Ogg Vorbis"):
        inspect_upload("music", b"ID3 this is an mp3")


def test_sound_effects_are_short_wav_clips():
    clip = canonical_wav(1, 24000, struct.pack("<h", 100) * 2400)
    upload = inspect_upload("sound", clip)
    assert upload.media_type == "audio/wav"
    assert upload.duration_ms == 100
    with pytest.raises(DomainError, match="WAV"):
        inspect_upload("sound", STEREO)
