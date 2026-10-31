"""Optional prompt-manager diagnostics without loading model or API credentials."""

import asyncio
import os
from pathlib import Path
from typing import Any

from flint_graph.prompts.catalog import PromptError
from flint_graph.prompts.langfuse import LangfusePromptSource, LangfuseReader
from flint_graph.prompts.source import DEFAULT_LOCK, LockedPromptSource


async def diagnose_prompts(*, offline: bool) -> dict[str, Any]:
    lock = LockedPromptSource.load(
        Path(os.environ["FLINT_GRAPH_PROMPT_LOCK_PATH"])
        if os.getenv("FLINT_GRAPH_PROMPT_LOCK_PATH")
        else DEFAULT_LOCK
    )
    report = {
        "optional": True,
        "bundle_sha256": lock.snapshot().sha256,
        "remote": "not_checked",
        "key": "not_checked",
        "drift": "not_checked",
    }
    if offline or os.getenv("FLINT_GRAPH_PROMPT_SOURCE", "locked") == "locked":
        return report
    public, secret = (
        os.getenv("FLINT_GRAPH_LANGFUSE_PUBLIC_KEY"),
        os.getenv("FLINT_GRAPH_LANGFUSE_SECRET_KEY"),
    )
    if not public or not secret:
        return {**report, "key": "missing"}
    try:
        reader = LangfuseReader(
            base_url=os.getenv("FLINT_GRAPH_LANGFUSE_BASE_URL", "http://127.0.0.1:6090"),
            public_key=public,
            secret_key=secret,
            names=[entry.name for entry in lock.snapshot().entries],
        )
        source = LangfusePromptSource(
            lock, reader, label=os.getenv("FLINT_GRAPH_LANGFUSE_PROMPT_LABEL", "production")
        )
        try:
            await source.refresh()
            status = source.status()["last_result"]
        finally:
            await source.aclose()
    except PromptError:
        return {**report, "remote": "configuration_unavailable"}
    return {
        **report,
        "remote": status,
        "key": "invalid"
        if status == "invalid_credentials"
        else "valid"
        if status in {"approved", "unreviewed", "invalid_response", "missing_label"}
        else "unknown",
        "drift": "none"
        if status == "approved"
        else "detected"
        if status in {"unreviewed", "invalid_response"}
        else "unknown",
    }


def prompt_report(*, offline: bool) -> dict[str, Any]:
    return asyncio.run(diagnose_prompts(offline=offline))
