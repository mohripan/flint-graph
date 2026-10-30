"""Bounded trusted-child transport. No archive metadata is extracted to host paths.

The runner owns stream deadlines and process cleanup. Only an explicit uncompressed
USTAR inventory is accepted; automatic extended/sparse/longname parsing is absent.
"""

import io
import re
import struct
import tarfile
import zipfile
from collections.abc import Buffer, Mapping
from dataclasses import dataclass
from typing import Protocol

_CHUNK = 65536
_MIB = 1024 * 1024
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class ArtifactError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ArtifactLimits:
    wire_bytes: int = 72 * _MIB
    file_bytes: int = 50 * _MIB
    total_bytes: int = 64 * _MIB
    max_files: int = 32

    def __post_init__(self) -> None:
        for value, ceiling in [
            (self.wire_bytes, 72 * _MIB),
            (self.file_bytes, 50 * _MIB),
            (self.total_bytes, 64 * _MIB),
            (self.max_files, 32),
        ]:
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("Invalid artifact limits")


_DEFAULT_LIMITS = ArtifactLimits()


class BinaryReader(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


class _Reader:
    def __init__(self, stream: BinaryReader, cap: int) -> None:
        self.stream, self.cap, self.used = stream, cap, 0

    def chunk(self, size: int = _CHUNK) -> bytes:
        requested = min(size, _CHUNK, self.cap - self.used + 1)
        data = self.stream.read(requested)
        if not isinstance(data, bytes) or len(data) > requested:
            raise ArtifactError("invalid_stream")
        self.used += len(data)
        if self.used > self.cap:
            raise ArtifactError("wire_size_limit")
        return data

    def exact(self, size: int) -> bytes:
        if size > self.cap - self.used:
            raise ArtifactError("wire_size_limit")
        result = bytearray()
        remaining = size
        while remaining:
            value = self.chunk(remaining)
            if not value:
                raise ArtifactError("truncated_archive")
            result.extend(value)
            remaining -= len(value)
        return bytes(result)


def _flat_name(name: str) -> bool:
    return (
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", name))
        and not name.endswith(".")
        and name.split(".")[0].lower() not in _RESERVED
    )


def read_child_files(
    stream: BinaryReader,
    *,
    expected_names: frozenset[str],
    root: str = "web",
    limits: ArtifactLimits = _DEFAULT_LIMITS,
) -> dict[str, bytes]:
    if (
        not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", root)
        or not 1 <= len(expected_names) <= limits.max_files
    ):
        raise ValueError("Invalid child artifact inventory")
    if any(not _flat_name(name) for name in expected_names) or len(
        {name.lower() for name in expected_names}
    ) != len(expected_names):
        raise ValueError("Invalid child artifact inventory")
    reader = _Reader(stream, limits.wire_bytes)
    files: dict[str, bytes] = {}
    root_seen, total = False, 0
    while True:
        header = reader.exact(512)
        if not any(header):
            if any(reader.exact(512)):
                raise ArtifactError("invalid_trailer")
            while trailing := reader.chunk():
                if any(trailing):
                    raise ArtifactError("invalid_trailer")
            if reader.used % 512:
                raise ArtifactError("invalid_trailer")
            if set(files) != expected_names:
                raise ArtifactError("incomplete_inventory")
            return files
        if header[257:265] != b"ustar\x0000":
            raise ArtifactError("invalid_header")
        try:
            member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        except (tarfile.HeaderError, UnicodeError, ValueError):
            raise ArtifactError("invalid_header") from None
        if member.type == tarfile.DIRTYPE:
            if member.name != root or root_seen or member.size or member.linkname:
                raise ArtifactError("invalid_entry")
            root_seen = True
            continue
        # Reject PAX, GNU sparse/longname, symlinks, hardlinks and devices BEFORE
        # reading their declared payload or invoking any extended-header parser.
        if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.linkname:
            raise ArtifactError("invalid_entry")
        name = member.name.removeprefix(root + "/")
        if member.name != root + "/" + name or name not in expected_names:
            raise ArtifactError("unexpected_file")
        if name in files:
            raise ArtifactError("duplicate_file")
        if not 0 <= member.size <= limits.file_bytes:
            raise ArtifactError("file_size_limit")
        total += member.size
        if total > limits.total_bytes:
            raise ArtifactError("total_size_limit")
        files[name] = reader.exact(member.size)
        padding = (-member.size) % 512
        if any(reader.exact(padding)):
            raise ArtifactError("invalid_padding")


def web_pack_has_project_settings(pck: bytes) -> bool:
    """Whether a pinned Godot 4.7 Web pack carries readable engine project settings.

    Godot exits successfully even when it cannot stage ``project.binary``, which
    leaves an empty entry that browsers refuse to boot. Only the unencrypted pack
    format of the pinned engine (version 4) is accepted; anything else fails closed.
    """
    try:
        magic, version, *_, flags, base, directory = struct.unpack_from("<4s5I2Q", pck, 0)
        if magic != b"GDPC" or version != 4 or flags & 1:
            return False
        (count,) = struct.unpack_from("<I", pck, directory)
        if count > 4096:
            return False
        offset = directory + 4
        for _ in range(count):
            (length,) = struct.unpack_from("<I", pck, offset)
            if length > 4096:
                return False
            name = pck[offset + 4 : offset + 4 + length].rstrip(b"\0")
            offset += 4 + length
            start, size = struct.unpack_from("<QQ", pck, offset)
            (entry_flags,) = struct.unpack_from("<I", pck, offset + 32)
            offset += 36
            if name == b"project.binary":
                begin = base + start
                return (
                    not entry_flags & 1
                    and 4 <= size
                    and begin + size <= len(pck)
                    and pck[begin : begin + 4] == b"ECFG"
                )
        return False
    except struct.error:
        return False


class _ZipBuffer(io.BytesIO):
    def __init__(self, cap: int) -> None:
        super().__init__()
        self.cap = cap

    def write(self, data: Buffer, /) -> int:
        if self.tell() + memoryview(data).nbytes > self.cap:
            raise ArtifactError("zip_size_limit")
        return super().write(data)


def make_artifact_zip(
    files: Mapping[str, bytes],
    *,
    limits: ArtifactLimits = _DEFAULT_LIMITS,
    zip_bytes: int = 64 * _MIB,
) -> bytes:
    """Encode an already bounded inventory; never discover files from a host tree.

    Stable for given bytes and compressor version. Engine output reproducibility
    across hosts is separate; releases record actual artifact hashes.
    """
    if type(zip_bytes) is not int or not 1 <= zip_bytes <= 64 * _MIB:
        raise ValueError("Invalid ZIP limit")
    names = list(files)
    if not 1 <= len(names) <= limits.max_files or len({n.lower() for n in names}) != len(names):
        raise ArtifactError("invalid_zip_inventory")
    total = 0
    folded_names = {name.lower() for name in names}
    for name, data in files.items():
        if len(name) > 240 or not all(_flat_name(part) for part in name.split("/")):
            raise ArtifactError("invalid_zip_inventory")
        parts = name.lower().split("/")
        if any("/".join(parts[:i]) in folded_names for i in range(1, len(parts))):
            raise ArtifactError("invalid_zip_inventory")
        if not isinstance(data, bytes):
            raise ArtifactError("invalid_zip_inventory")
        if len(data) > limits.file_bytes:
            raise ArtifactError("file_size_limit")
        total += len(data)
        if total > limits.total_bytes:
            raise ArtifactError("total_size_limit")
    output = _ZipBuffer(zip_bytes)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as z:
        for name in sorted(names):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            with z.open(info, "w") as entry:
                data = files[name]
                for start in range(0, len(data), _CHUNK):
                    entry.write(data[start : start + _CHUNK])
    return output.getvalue()
