"""Explicit, bounded collection of public financial-report evidence. No inference or ingestion."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from flint_graph.evaluation.financial_corpus import (
    MAX_SOURCE_BYTES,
    CorpusError,
    collect_financial_corpus,
    export_financial_dataset,
    verify_financial_corpus,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser(
        "download", help="Download the pinned public FinQA dev/test release"
    )
    download.add_argument("--output", required=True, type=Path, help="New artifact directory")
    download.add_argument("--max-documents", type=int, default=2000)
    download.add_argument("--max-source-bytes", type=int, default=MAX_SOURCE_BYTES)
    download.add_argument("--timeout-seconds", type=float, default=180)
    download.add_argument("--json", action="store_true")
    verify = commands.add_parser(
        "verify", help="Verify every artifact checksum without network access"
    )
    verify.add_argument("--directory", required=True, type=Path)
    verify.add_argument("--json", action="store_true")
    dataset = commands.add_parser(
        "dataset", help="Export a bounded evidence-only ingestion dataset"
    )
    dataset.add_argument("--directory", required=True, type=Path)
    dataset.add_argument("--output", required=True, type=Path)
    dataset.add_argument("--max-documents", type=int, default=100)
    dataset.add_argument("--offset", type=int, default=0)
    dataset.add_argument("--json", action="store_true")
    return parser


async def _download(
    args: argparse.Namespace, transport: httpx.AsyncBaseTransport | None
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=transport,
        timeout=30,
        follow_redirects=False,
        trust_env=False,
        headers={"user-agent": "FlintGraph-public-corpus/1.0"},
    ) as client:
        return await collect_financial_corpus(
            client,
            args.output,
            max_bytes=args.max_source_bytes,
            max_documents=args.max_documents,
            timeout_seconds=args.timeout_seconds,
        )


def main(
    argv: Sequence[str] | None = None, *, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "dataset":
            batch = export_financial_dataset(
                args.directory, args.output, max_documents=args.max_documents, offset=args.offset
            )
            summary = {
                "status": "exported",
                "document_count": batch["document_count"],
                "offset": batch["offset"],
            }
            print(
                json.dumps(summary)
                if args.json
                else f"Exported {batch['document_count']} documents; no ingestion performed."
            )
            return 0
        manifest = (
            asyncio.run(_download(args, transport))
            if args.command == "download"
            else verify_financial_corpus(args.directory)
        )
        summary = {"status": "verified" if args.command == "verify" else "downloaded"}
        for key in (
            "revision",
            "source_bytes",
            "corpus_bytes",
            "example_count",
            "available_example_count",
            "document_count",
            "report_count",
            "truncated",
        ):
            summary[key] = manifest[key]
    except CorpusError as exc:
        summary = {"status": "failed", "error": str(exc)}
    except (OSError, ValueError, TypeError, KeyError):
        summary = {"status": "failed", "error": "Cannot read or create corpus artifacts."}
    print(
        json.dumps(summary, indent=2)
        if args.json
        else "\n".join(f"{key}: {value}" for key, value in summary.items())
    )
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
