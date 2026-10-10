"""Opt-in CLI; publish redacted summaries, never raw black-box recordings."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from flint_graph.evaluation.capture import CaptureManifest
from flint_graph.evaluation.datasets import load_dataset
from flint_graph.evaluation.financial_corpus import verify_financial_corpus
from flint_graph.evaluation.nightly import (
    AnswerRubric,
    NightlyError,
    NightlyPolicy,
    inspect_nightly_target,
    run_nightly,
)


def nightly_command(args: argparse.Namespace) -> int:
    # Reuse connection validation without embedding credentials in reports.
    from flint_graph.cli.eval import _api_connection_options

    output = Path(args.output)
    try:
        if output.exists() or output.is_symlink():
            raise NightlyError("Report output already exists; choose a new path.")
        if not args.inspect and not args.model_fingerprint:
            raise NightlyError("Require an explicitly reviewed model fingerprint.")
        base_url, headers = _api_connection_options(args)
        corpus = verify_financial_corpus(Path(args.corpus))
        approved = {"finqa-" + row["sha256"] for row in corpus["documents"]}
        dataset_path = Path(args.dataset)
        dataset = load_dataset(dataset_path)
        manifest = CaptureManifest.model_validate_json(
            Path(args.manifest).read_text(encoding="utf-8")
        )
        policy = NightlyPolicy.model_validate_json(
            (dataset_path / "policy.json").read_text(encoding="utf-8")
        )
        rubrics = {
            key: AnswerRubric.model_validate(value)
            for key, value in json.loads(
                (dataset_path / "rubrics.json").read_text(encoding="utf-8")
            ).items()
        }

        async def execute() -> dict[str, Any]:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=30,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                if args.inspect:
                    async with asyncio.timeout(60):
                        result = await inspect_nightly_target(
                            client,
                            manifest,
                            approved_labels=approved,
                            isolation_workspace_id=str(args.isolation_workspace_id),
                        )
                    return {"status": "inspected_not_evaluated", **result}
                return await run_nightly(
                    client,
                    dataset,
                    manifest,
                    rubrics,
                    approved_labels=approved,
                    isolation_workspace_id=str(args.isolation_workspace_id),
                    expected_model_fingerprint=args.model_fingerprint,
                    policy=policy,
                )

        result = asyncio.run(execute())
        result["client_git_sha"] = args.git_sha
        result["deployed_git_sha"] = None  # API does not attest a build revision yet.
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as report:
            json.dump(result, report, indent=2)
            report.write("\n")
        print(f"Nightly status: {result['status']}; redacted report written.")
        return 0 if result["status"] in {"passed", "inspected_not_evaluated"} else 1
    except NightlyError as exc:
        print(f"Nightly failed: {exc}")
    except (ValueError, OSError, httpx.HTTPError, TimeoutError, KeyError, TypeError):
        print("Nightly failed: invalid configuration, source verification or API response.")
    return 1


def register_nightly(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("nightly", help="fresh bounded public financial black-box gate")
    for name in ("dataset", "manifest", "corpus", "base-url", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--isolation-workspace-id", type=UUID, required=True)
    parser.add_argument("--model-fingerprint")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--token-env", default="FLINT_GRAPH_EVAL_TOKEN")
    parser.add_argument("--git-sha")
    parser.set_defaults(func=nightly_command)
