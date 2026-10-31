"""Generic prompt publication tooling; runtime credentials never gain write access."""

import argparse
import asyncio
import json
import os
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from flint_graph.prompts.catalog import PromptError, canonical
from flint_graph.prompts.release import promote, pull, seed
from flint_graph.prompts.source import (
    DEFAULT_LOCK,
    LockedPromptSource,
    PromptBundle,
    validate_upgrade,
)


def read(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise PromptError("lock_too_large")
    return raw


def write(path: Path, raw: bytes) -> None:
    path.write_text(
        json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


async def remote(args: argparse.Namespace, lock: LockedPromptSource) -> None:
    public = os.getenv("FLINT_GRAPH_PROMPT_AUTHOR_PUBLIC_KEY")
    secret = os.getenv("FLINT_GRAPH_PROMPT_AUTHOR_SECRET_KEY")
    if not public or not secret:
        raise PromptError("author_credentials_required")
    url = httpx.URL(args.url)
    if (
        url.username
        or url.password
        or url.query
        or url.fragment
        or url.scheme not in {"http", "https"}
    ):
        raise PromptError("invalid_langfuse_origin")
    async with httpx.AsyncClient(
        base_url=str(url), auth=(public, secret), timeout=10, follow_redirects=False
    ) as client:
        if args.command == "seed":
            await seed(client, lock.snapshot(), args.label)
        elif args.command == "pull":
            bundle = await pull(
                client,
                lock,
                args.label,
                source_revision=args.source_revision,
                evaluation_record=args.evaluation_record,
            )
            write(args.output, canonical(bundle.data))
        elif args.command == "promote":
            # Durable intent exists even if the service fails halfway through label changes.
            receipt = {
                "actor": args.actor,
                "reason": args.reason,
                "bundle_sha256": args.bundle,
                "label": args.label,
                "at": datetime.now(UTC).isoformat(),
                "status": "started",
            }
            with args.receipt.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(receipt) + "\n")
            result = await promote(client, lock, args.bundle, args.label)
            with args.receipt.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({**receipt, **result, "status": "completed"}) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--base-ref")
    check.add_argument("--previous", type=Path)
    commands.add_parser("status")
    diff = commands.add_parser("diff")
    diff.add_argument("candidate", type=Path)
    approve = commands.add_parser("lock")
    approve.add_argument("candidate", type=Path)
    approve.add_argument("--output", type=Path, required=True)
    approve.add_argument("--activate", action="store_true")
    for command in ("seed", "pull", "promote"):
        sub = commands.add_parser(command)
        sub.add_argument(
            "--url", default=os.getenv("FLINT_GRAPH_LANGFUSE_BASE_URL", "http://127.0.0.1:6090")
        )
        sub.add_argument("--label", default="staging")
        if command == "pull":
            sub.add_argument("--source-revision", required=True)
            sub.add_argument("--evaluation-record", required=True)
            sub.add_argument("--output", type=Path, required=True)
        if command == "promote":
            sub.add_argument("--bundle", required=True)
            sub.add_argument("--actor", required=True)
            sub.add_argument("--reason", required=True)
            sub.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = read(args.lock)
        lock = LockedPromptSource.from_bytes(raw)
        if args.command == "check":
            if args.previous:
                validate_upgrade(read(args.previous), raw)
            if args.base_ref:
                if args.base_ref.startswith("-"):
                    raise PromptError("invalid_base_ref")
                previous = subprocess.run(
                    ["git", "show", args.base_ref + ":src/flint_graph/prompts/prompts.lock"],
                    capture_output=True,
                    check=True,
                ).stdout
                validate_upgrade(previous, raw)
        elif args.command in {"lock", "diff"}:
            candidate = PromptBundle.from_bytes(read(args.candidate))
            if {e.name for e in candidate.entries} != {e.name for e in lock.snapshot().entries}:
                raise PromptError("incomplete_candidate_bundle")
            if args.command == "diff":
                print(
                    json.dumps(
                        {
                            e.name: [
                                key
                                for key, value in e.data.items()
                                if lock.snapshot().entry(e.name).data[key] != value
                            ]
                            for e in candidate.entries
                            if e.sha256 != lock.snapshot().entry(e.name).sha256
                        },
                        sort_keys=True,
                    )
                )
            else:
                bundles = {b.sha256: b for b in lock.bundles}
                bundles[candidate.sha256] = candidate
                packed = LockedPromptSource.pack(
                    list(bundles.values()),
                    candidate.sha256 if args.activate else lock.snapshot().sha256,
                )
                validate_upgrade(raw, packed)
                write(args.output, packed)
        elif args.command in {"seed", "pull", "promote"}:
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", args.label):
                raise PromptError("invalid_label")
            asyncio.run(remote(args, lock))
        print(json.dumps({"status": "ok", "bundle_sha256": lock.snapshot().sha256}))
        return 0
    except (
        PromptError,
        OSError,
        httpx.HTTPError,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        # Never print URLs, response bodies, credentials, files or arbitrary authored text.
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": str(error)
                    if isinstance(error, PromptError)
                    else "prompt_command_failed",
                }
            )
        )
        return 1
