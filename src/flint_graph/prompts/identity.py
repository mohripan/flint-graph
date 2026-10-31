"""Attach non-sensitive identity to the existing provider result/usage path."""

from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

from flint_graph.prompts.source import current_snapshot, use_snapshot

_identity: ContextVar[dict[str, Any] | None] = ContextVar("provider_prompt_identity", default=None)
_observer: ContextVar[Callable[[dict[str, Any]], Awaitable[None]] | None] = ContextVar(
    "prompt_identity_observer", default=None
)


@contextmanager
def observe_identity(observer: Callable[[dict[str, Any]], Awaitable[None]]) -> Iterator[None]:
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def provider_identity() -> dict[str, Any]:
    return dict(_identity.get() or {})


def identified[**P, T](
    name: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    def decorate(
        function: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            owner: Any = args[0]
            effective = {
                key.removeprefix("_"): getattr(owner, key)
                for key in ("_model", "_max_tokens", "_effort", "_temperature", "_context_tokens")
                if hasattr(owner, key)
            }
            with use_snapshot(current_snapshot()) as bundle:
                identity = bundle.identity(name, effective)
                identity["effective_config"] = effective
                observer = _observer.get()
                if observer is not None:
                    await observer(identity)
                token = _identity.set(identity)
                try:
                    result = await function(*args, **kwargs)
                finally:
                    _identity.reset(token)
                metadata = getattr(result, "metadata", None)
                if isinstance(metadata, dict):
                    metadata["prompt_identity"] = identity
                return result

        return wrapped

    return decorate
