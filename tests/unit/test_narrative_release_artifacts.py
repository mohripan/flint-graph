"""The bounded child-byte transport is separate from engine execution."""

import io
import tarfile
import tracemalloc
import zipfile

import pytest

from flint_graph.narrative.release_artifacts import (
    ArtifactError,
    ArtifactLimits,
    read_child_files,
)


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as stream:
        root = tarfile.TarInfo("web")
        root.type = tarfile.DIRTYPE
        stream.addfile(root)
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            stream.addfile(info, io.BytesIO(data))
    return output.getvalue()


class ShortReader(io.BytesIO):
    def read(self, size=-1):
        assert 0 <= size <= 65536, "The consumer must never request unbounded input"
        return super().read(min(size, 17))


def test_fixed_child_files_are_decoded_from_short_reads_without_filesystem_extraction():
    source = ShortReader(
        archive(
            [
                ("web/index.html", b"<!doctype html><title>Original fixture</title>"),
                ("web/index.js", b"trusted fixture"),
            ]
        )
    )
    files = read_child_files(source, expected_names=frozenset({"index.html", "index.js"}))
    assert files == {
        "index.html": b"<!doctype html><title>Original fixture</title>",
        "index.js": b"trusted fixture",
    }
    assert source.tell() == len(source.getvalue())


def header(name="web/index.js", *, size=0, kind=tarfile.REGTYPE, link="", format=None):
    info = tarfile.TarInfo(name)
    info.size, info.type, info.linkname = size, kind, link
    return info.tobuf(format=tarfile.USTAR_FORMAT if format is None else format)


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.GNUTYPE_SPARSE,
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
    ],
)
def test_special_entries_are_rejected_before_their_declared_payload_is_read(kind):
    source = io.BytesIO(header(kind=kind, size=500000))
    with pytest.raises(ArtifactError, match=r"^invalid_entry$"):
        read_child_files(source, expected_names=frozenset({"index.js"}))
    assert source.tell() == 512


def test_gnu_headers_are_rejected_even_for_regular_files():
    source = io.BytesIO(header(format=tarfile.GNU_FORMAT))
    with pytest.raises(ArtifactError, match=r"^invalid_header$"):
        read_child_files(source, expected_names=frozenset({"index.js"}))
    assert source.tell() == 512


def test_overlarge_size_is_rejected_before_payload_allocation_or_read():
    # A valid large octal USTAR size, rather than an invalid checksum/header.
    source = io.BytesIO(header(size=2**32))
    with pytest.raises(ArtifactError, match=r"^file_size_limit$"):
        read_child_files(source, expected_names=frozenset({"index.js"}))
    assert source.tell() == 512


@pytest.mark.parametrize(
    "name",
    ["web/../index.js", "/web/index.js", "other/index.js", "web/index.js/child", "web/secret.txt"],
)
def test_unexpected_paths_are_rejected_without_echoing_them(name):
    with pytest.raises(ArtifactError) as caught:
        read_child_files(io.BytesIO(header(name)), expected_names=frozenset({"index.js"}))
    assert str(caught.value) == "unexpected_file"
    assert name not in str(caught.value)


def test_duplicate_files_and_directories_fail_closed():
    with pytest.raises(ArtifactError, match=r"^duplicate_file$"):
        read_child_files(
            io.BytesIO(archive([("web/index.js", b"a"), ("web/index.js", b"b")])),
            expected_names=frozenset({"index.js"}),
        )
    with pytest.raises(ArtifactError, match=r"^invalid_entry$"):
        read_child_files(
            io.BytesIO(header("web/extra", kind=tarfile.DIRTYPE)),
            expected_names=frozenset({"index.js"}),
        )


def test_aggregate_budget_is_checked_before_reading_the_next_file():
    source = io.BytesIO(archive([("web/index.js", b"abcd"), ("web/index.html", b"efgh")]))
    with pytest.raises(ArtifactError, match=r"^total_size_limit$"):
        read_child_files(
            source,
            expected_names=frozenset({"index.js", "index.html"}),
            limits=ArtifactLimits(total_bytes=7),
        )
    assert source.tell() == 2048


@pytest.mark.parametrize(
    "data,code",
    [
        (b"x" * 511, "truncated_archive"),
        (header(size=1), "truncated_archive"),
        (header(size=1) + b"a" + b"x" + b"\0" * 510, "invalid_padding"),
        (b"\0" * 512, "truncated_archive"),
        (b"\0" * 512 + header(), "invalid_trailer"),
        (b"\0" * 1024 + b"x" * 512, "invalid_trailer"),
        (b"\0" * 1025, "invalid_trailer"),
        (b"\0" * 1024, "incomplete_inventory"),
    ],
)
def test_truncation_padding_and_trailers_are_checked(data, code):
    with pytest.raises(ArtifactError, match=f"^{code}$"):
        read_child_files(io.BytesIO(data), expected_names=frozenset({"index.js"}))


def test_trailing_zero_stream_cannot_exceed_wire_budget():
    source = io.BytesIO(archive([("web/index.js", b"ok")]))
    with pytest.raises(ArtifactError, match=r"^wire_size_limit$"):
        read_child_files(
            source, expected_names=frozenset({"index.js"}), limits=ArtifactLimits(wire_bytes=4096)
        )
    assert source.tell() == 4097


def test_archive_header_checksum_is_checked():
    data = bytearray(header())
    data[1] ^= 1
    with pytest.raises(ArtifactError, match=r"^invalid_header$"):
        read_child_files(io.BytesIO(data), expected_names=frozenset({"index.js"}))


def test_one_byte_payload_reads_do_not_amplify_retained_memory():
    class OneByteReader(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 1))

    payload = b"a" * (256 * 1024)
    source = OneByteReader(archive([("web/index.js", payload)]))
    tracemalloc.start()
    try:
        result = read_child_files(source, expected_names=frozenset({"index.js"}))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result["index.js"] == payload
    assert peak < 4 * 1024 * 1024


@pytest.mark.parametrize("names", [{"CON.txt"}, {"a", "A"}, {"../x"}, {"a."}, set()])
def test_trusted_inventory_must_also_be_portable_and_unambiguous(names):
    with pytest.raises(ValueError, match=r"^Invalid child artifact inventory$"):
        read_child_files(io.BytesIO(), expected_names=frozenset(names))


def test_source_zip_has_stable_bytes_and_portable_regular_file_metadata():
    from flint_graph.narrative.release_artifacts import make_artifact_zip

    files = {"runtime/player.gd": b"trusted script", "content/story.json": b"{}"}
    result = make_artifact_zip(files)
    assert make_artifact_zip(dict(reversed(list(files.items())))) == result
    with zipfile.ZipFile(io.BytesIO(result)) as stream:
        assert stream.namelist() == sorted(files)
        for entry in stream.infolist():
            assert entry.date_time == (1980, 1, 1, 0, 0, 0)
            assert entry.create_system == 3
            assert entry.external_attr >> 16 == 0o100644
            assert not entry.extra and not entry.comment
            assert stream.read(entry) == files[entry.filename]


@pytest.mark.parametrize(
    "name",
    [
        "../secret",
        "/root",
        "a\\b",
        "a//b",
        "a/./b",
        ".godot/cache",
        "a/.git/config",
        "CON.txt",
        "a/aux.log",
    ],
)
def test_zip_rejects_unsafe_and_nonportable_paths(name):
    from flint_graph.narrative.release_artifacts import make_artifact_zip

    with pytest.raises(ArtifactError, match=r"^invalid_zip_inventory$"):
        make_artifact_zip({name: b"not echoed"})


def test_zip_rejects_case_collisions_and_uncompressed_output_budgets():
    from flint_graph.narrative.release_artifacts import make_artifact_zip

    with pytest.raises(ArtifactError, match=r"^invalid_zip_inventory$"):
        make_artifact_zip({"A.txt": b"a", "a.txt": b"b"})
    with pytest.raises(ArtifactError, match=r"^file_size_limit$"):
        make_artifact_zip({"a": b"abc"}, limits=ArtifactLimits(file_bytes=2))
    with pytest.raises(ArtifactError, match=r"^total_size_limit$"):
        make_artifact_zip({"a": b"ab", "b": b"cd"}, limits=ArtifactLimits(total_bytes=3))
    with pytest.raises(ArtifactError, match=r"^zip_size_limit$"):
        make_artifact_zip({"a": b"a"}, zip_bytes=50)


@pytest.mark.parametrize("files", [{"a": b"x", "a/b": b"y"}, {"A": b"x", "a/b": b"y"}])
def test_zip_rejects_files_that_shadow_another_files_parent_directory(files):
    from flint_graph.narrative.release_artifacts import make_artifact_zip

    with pytest.raises(ArtifactError, match=r"^invalid_zip_inventory$"):
        make_artifact_zip(files)
