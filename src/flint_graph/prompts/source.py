"""Local approved bundles, immutable run scopes and validation of lock upgrades."""

import hashlib
import json
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Protocol

from flint_graph.prompts.catalog import PromptEntry, PromptError, canonical

MAX_LOCK_BYTES = 2 * 1024 * 1024
DEFAULT_LOCK = Path(__file__).with_name("prompts.lock")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PromptError("duplicate_lock_key")
        result[key] = value
    return result


def parse(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_LOCK_BYTES:
        raise PromptError("lock_too_large")
    try:
        value = json.loads(data, object_pairs_hook=_object)
        canonical(value)
    except (ValueError, UnicodeDecodeError, TypeError, RecursionError):
        raise PromptError("invalid_lock") from None
    if not isinstance(value, dict):
        raise PromptError("invalid_lock")
    return value


def entry_from_data(data: dict[str, Any]) -> PromptEntry:
    expected = {
        "name",
        "kind",
        "type",
        "catalog_version",
        "langfuse_version",
        "template",
        "variables_schema",
        "output_schema",
        "config",
        "legacy_version",
    }
    if set(data) != expected:
        raise PromptError("invalid_entry")
    values = {key: value for key, value in data.items() if key != "type"}
    try:
        entry = PromptEntry.create(**values)
    except (TypeError, ValueError, RecursionError):
        raise PromptError("invalid_entry") from None
    if data != entry.data:
        raise PromptError("invalid_entry")
    return entry


@dataclass(frozen=True)
class PromptBundle:
    _encoded: bytes
    _entries: tuple[PromptEntry, ...] = field(repr=False)

    @classmethod
    def create(
        cls, entries: Sequence[PromptEntry], *, source_revision: str, evaluation_record: str
    ) -> "PromptBundle":
        if (
            not isinstance(source_revision, str)
            or not 1 <= len(source_revision) <= 256
            or not isinstance(evaluation_record, str)
            or not 1 <= len(evaluation_record) <= 1024
        ):
            raise PromptError("invalid_bundle_provenance")
        names = [entry.name for entry in entries]
        if not names or len(names) > 128 or len(set(names)) != len(names):
            raise PromptError("invalid_bundle_entries")
        encoded = canonical(
            {
                "entries": [entry.data for entry in sorted(entries, key=lambda x: x.name)],
                "source_revision": source_revision,
                "evaluation_record": evaluation_record,
            }
        )
        if len(encoded) > MAX_LOCK_BYTES:
            raise PromptError("lock_too_large")
        return cls(encoded, tuple(sorted(entries, key=lambda x: x.name)))

    @classmethod
    def from_bytes(cls, raw: bytes) -> "PromptBundle":
        data = parse(raw)
        if set(data) != {"entries", "source_revision", "evaluation_record"}:
            raise PromptError("invalid_bundle")
        try:
            return cls.create(
                [entry_from_data(entry) for entry in data["entries"]],
                source_revision=data["source_revision"],
                evaluation_record=data["evaluation_record"],
            )
        except (TypeError, KeyError):
            raise PromptError("invalid_bundle") from None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self._encoded).hexdigest()

    @property
    def data(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self._encoded)
        return value

    @property
    def entries(self) -> tuple[PromptEntry, ...]:
        return self._entries

    def entry(self, name: str) -> PromptEntry:
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise PromptError("unknown_prompt")

    def identity(self, name: str, effective_config: dict[str, Any] | None = None) -> dict[str, Any]:
        return {**self.entry(name).identity(effective_config), "bundle_sha256": self.sha256}


class PromptSource(Protocol):
    def snapshot(self) -> PromptBundle: ...


class LockedPromptSource:
    def __init__(self, bundles: dict[str, PromptBundle], default_bundle: str):
        if default_bundle not in bundles:
            raise PromptError("missing_default_bundle")
        self._bundles = dict(bundles)
        self._default = default_bundle

    @classmethod
    def from_bytes(cls, raw: bytes) -> "LockedPromptSource":
        data = parse(raw)
        if (
            set(data) != {"schema_version", "default_bundle", "bundles", "versions"}
            or type(data["schema_version"]) is not int
            or data["schema_version"] != 1
        ):
            raise PromptError("invalid_lock")
        bundles = {}
        versions: dict[str, str] = {}
        try:
            for sha, value in data["bundles"].items():
                bundle = PromptBundle.from_bytes(canonical(value))
                if bundle.sha256 != sha:
                    raise PromptError("bundle_hash_mismatch")
                for entry in bundle.entries:
                    key = f"{entry.name}:{entry.data['catalog_version']}"
                    if key in versions and versions[key] != entry.sha256:
                        raise PromptError("version_not_bumped")
                    versions[key] = entry.sha256
                bundles[sha] = bundle
            if any(data["versions"].get(key) != sha for key, sha in versions.items()):
                raise PromptError("version_not_bumped")
            return cls(bundles, data["default_bundle"])
        except (TypeError, KeyError, AttributeError):
            raise PromptError("invalid_lock") from None

    @classmethod
    def load(cls, path: Path = DEFAULT_LOCK) -> "LockedPromptSource":
        try:
            with path.open("rb") as handle:
                return cls.from_bytes(handle.read(MAX_LOCK_BYTES + 1))
        except OSError:
            raise PromptError("lock_unavailable") from None

    @staticmethod
    def pack(
        bundles: Sequence[PromptBundle], default_bundle: str, versions: dict[str, str] | None = None
    ) -> bytes:
        history = dict(versions or {})
        for bundle in bundles:
            for entry in bundle.entries:
                key = f"{entry.name}:{entry.data['catalog_version']}"
                if key in history and history[key] != entry.sha256:
                    raise PromptError("version_not_bumped")
                history[key] = entry.sha256
        raw = canonical(
            {
                "schema_version": 1,
                "default_bundle": default_bundle,
                "bundles": {bundle.sha256: bundle.data for bundle in bundles},
                "versions": history,
            }
        )
        LockedPromptSource.from_bytes(raw)
        return raw

    @property
    def bundles(self) -> tuple[PromptBundle, ...]:
        return tuple(self._bundles.values())

    def snapshot(self) -> PromptBundle:
        return self._bundles[self._default]

    def get(self, sha: str) -> PromptBundle:
        if sha not in self._bundles:
            raise PromptError("historical_bundle_unavailable")
        return self._bundles[sha]


def validate_upgrade(previous: bytes, candidate: bytes) -> None:
    LockedPromptSource.from_bytes(previous)
    LockedPromptSource.from_bytes(candidate)
    old, new = parse(previous), parse(candidate)
    if any(new["versions"].get(key) != sha for key, sha in old["versions"].items()):
        raise PromptError("version_not_bumped")
    if not set(old["bundles"]).issubset(new["bundles"]):
        raise PromptError("historical_bundle_removed")


_scope: ContextVar[PromptBundle | None] = ContextVar("prompt_bundle", default=None)
_source: PromptSource | None = None


def configure_source(source: PromptSource | None) -> PromptSource | None:
    global _source
    previous, _source = _source, source
    return previous


def current_snapshot() -> PromptBundle:
    global _source
    scoped = _scope.get()
    if scoped is not None:
        return scoped
    if _source is None:
        _source = LockedPromptSource.load()
    return _source.snapshot()


@contextmanager
def use_snapshot(bundle: PromptBundle) -> Iterator[PromptBundle]:
    token = _scope.set(bundle)
    try:
        yield bundle
    finally:
        _scope.reset(token)


def render(name: str, **variables: Any) -> str:
    value = current_snapshot().entry(name).render(**variables)
    if not isinstance(value, str):
        raise PromptError("expected_text_prompt")
    return value


def render_chat(name: str, **variables: Any) -> list[dict[str, str]]:
    value = current_snapshot().entry(name).render(**variables)
    if not isinstance(value, list):
        raise PromptError("expected_chat_prompt")
    return value


def conditioning(key: str) -> Any:
    return current_snapshot().entry("narrative.image.conditioning").config[key]


def snapshot_async[**P, T](function: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        with use_snapshot(current_snapshot()):
            return await function(*args, **kwargs)

    return wrapped
