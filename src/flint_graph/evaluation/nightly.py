"""Fresh, bounded black-box checks for an explicitly approved public evaluation workspace."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from flint_graph.evaluation.capture import CaptureManifest, capture_dataset
from flint_graph.evaluation.datasets import GoldenDataset
from flint_graph.evaluation.metrics import aggregate_metrics

RubricTerm = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
RubricGroup = Annotated[list[RubricTerm], Field(min_length=1, max_length=8)]


class NightlyError(ValueError):
    """Safe messages only: do not include source text, model output, URLs or credentials."""


class AnswerRubric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    groups: list[RubricGroup] = Field(min_length=1, max_length=16)


class NightlyPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_queries: int = Field(default=16, ge=1, le=32)
    query_timeout_seconds: float = Field(default=90, gt=0, le=180)
    total_timeout_seconds: float = Field(default=1200, gt=0, le=1800)
    max_provider_tokens: int = Field(default=100000, ge=1, le=2000000)
    min_useful_answer_rate: float = Field(default=0.8, ge=0, le=1)
    min_abstention_accuracy: float = Field(default=1, ge=0, le=1)
    max_latency_ms_p95: float = Field(default=90000, gt=0, le=180000)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def inspect_nightly_target(
    client: httpx.AsyncClient,
    manifest: CaptureManifest,
    *,
    approved_labels: set[str],
    isolation_workspace_id: str,
) -> dict[str, Any]:
    """Read-only inspection. Caller must independently verify approved public source hashes."""
    tenant = str(manifest.tenant_id)
    isolation = str(UUID(isolation_workspace_id))
    labels = set(manifest.document_labels.values())
    if (
        isolation == tenant
        or not 1 <= len(manifest.document_labels) <= 100
        or not labels <= approved_labels
    ):
        raise NightlyError("Require separate isolation workspace and approved public documents.")
    headers = {"X-Tenant-ID": tenant}

    async def read(path: str, **kwargs: Any) -> Any:
        response = await client.get(path, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    workspaces = await read("/v1/workspaces")
    if not {tenant, isolation} <= {row["id"] for row in workspaces}:
        raise NightlyError("Both evaluation workspaces require authenticated membership.")
    readiness = await read("/v1/system-readiness")
    if (
        not readiness.get("setup_capabilities", {}).get("query_usage_rollups")
        or not readiness.get("setup_capabilities", {}).get("query_usage_invocations")
        or not readiness["search_readiness"]["ready"]
    ):
        raise NightlyError("Require searchable corpus and complete query invocation accounting.")
    models = await read("/v1/model-readiness")
    roles = {row["role"]: row for row in models}
    if len(models) != 3 or set(roles) != {"answer", "support", "embedding"}:
        raise NightlyError("Require all three model roles.")
    for role, row in roles.items():
        if role != "embedding" or row["provider"] != "deterministic":
            if (
                row["provider"] != "ollama"
                or row["status"] != "available"
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", row.get("digest") or "")
            ):
                raise NightlyError(
                    "Nightly requires installed digest-pinned Ollama answer/support models."
                )
    documents = await read("/v1/documents", params={"limit": 500})
    versions = manifest.preparation.get("document_versions", {})
    if len(documents) != len(manifest.document_labels) or len(versions) != len(documents):
        raise NightlyError(
            "Require an exact dedicated public corpus with verified document versions."
        )
    for row in documents:
        if (
            row["id"] not in manifest.document_labels
            or row["title"] != manifest.document_labels[row["id"]]
            or row["latest_version_status"] != "active"
            or versions.get(row["latest_version_id"]) != row["id"]
        ):
            raise NightlyError("Prepared corpus changed or includes unapproved content.")
    selected = [
        {key: row.get(key) for key in ("role", "provider", "model", "digest")}
        for row in sorted(models, key=lambda row: row["role"])
    ]
    index_id = readiness["search_readiness"]["active_index_version"]["id"]
    return {
        "model_fingerprint": _fingerprint(selected),
        "corpus_fingerprint": _fingerprint(
            {"labels": manifest.document_labels, "versions": versions}
        ),
        "deployment_fingerprint": _fingerprint({"index": index_id, "models": selected}),
        "retrieval_index_version_id": index_id,
    }


async def run_nightly(
    client: httpx.AsyncClient,
    dataset: GoldenDataset,
    manifest: CaptureManifest,
    rubrics: dict[str, AnswerRubric],
    *,
    approved_labels: set[str],
    isolation_workspace_id: str,
    expected_model_fingerprint: str,
    policy: NightlyPolicy,
) -> dict[str, Any]:
    """Fresh serialized requests; token stop is post-query, not a hard spending reservation."""
    report: dict[str, Any] = {
        "format_version": 3,
        "usage_scope": "query-invocations-v1",
        "dataset_name": dataset.metadata.name,
        "dataset_version": dataset.metadata.version,
        "rubric_fingerprint": _fingerprint(
            {key: rubric.model_dump(mode="json") for key, rubric in rubrics.items()}
        ),
        "policy_fingerprint": _fingerprint(policy.model_dump(mode="json")),
        "status": "failed",
        "query_count": 0,
        "attempted_query_count": 0,
        "planned_query_count": len(dataset.queries),
        "usage_complete": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "tenant_isolation_passed": False,
        "estimated_cost_usd": None,
        "cost_status": "unpriced_local_compute",
        "aggregate": {},
        "queries": [],
        "failure": None,
    }
    pairs = []
    useful = []
    all_answers_grounded = True
    try:
        async with asyncio.timeout(policy.total_timeout_seconds):
            if not 1 <= len(dataset.queries) <= policy.max_queries:
                raise NightlyError("Query count exceeds policy or dataset is empty.")
            answerable = {q.id for q in dataset.queries if not q.expect_abstain}
            if set(rubrics) != answerable or any(
                not set(q.relevant_chunk_ids + q.must_cite_sources)
                <= set(manifest.document_labels.values())
                or (not q.expect_abstain and not q.must_cite_sources)
                for q in dataset.queries
            ):
                raise NightlyError("Require independent rubrics and approved citation targets.")
            snapshot = await inspect_nightly_target(
                client,
                manifest,
                approved_labels=approved_labels,
                isolation_workspace_id=isolation_workspace_id,
            )
            report.update(snapshot)
            if snapshot["model_fingerprint"] != expected_model_fingerprint:
                raise NightlyError("Reviewed model fingerprint changed.")
            for query in dataset.queries:
                current = await inspect_nightly_target(
                    client,
                    manifest,
                    approved_labels=approved_labels,
                    isolation_workspace_id=isolation_workspace_id,
                )
                if current != snapshot:
                    raise NightlyError("Deployment, model or corpus changed during evaluation.")
                report["attempted_query_count"] += 1
                record = (
                    await capture_dataset(
                        client,
                        dataset.model_copy(update={"queries": [query]}),
                        manifest,
                        query_timeout_seconds=policy.query_timeout_seconds,
                    )
                )[0]
                evaluation = record.evaluation
                report["query_count"] += 1
                if (
                    record.capture.get("provider_usage_complete") is not True
                    or evaluation.input_tokens is None
                    or evaluation.output_tokens is None
                    or min(evaluation.input_tokens, evaluation.output_tokens) < 0
                ):
                    raise NightlyError("Actual provider usage is missing or invalid.")
                report["input_tokens"] += evaluation.input_tokens
                report["output_tokens"] += evaluation.output_tokens
                if (
                    record.capture["retrieval_index_version_id"]
                    != snapshot["retrieval_index_version_id"]
                ):
                    raise NightlyError("Query used a different retrieval index.")
                for suffix in ("", "/events", "/provenance"):
                    foreign = await client.get(
                        f"/v1/query-runs/{record.capture['query_run_id']}{suffix}",
                        headers={"X-Tenant-ID": str(UUID(isolation_workspace_id))},
                    )
                    if foreign.status_code != 404:
                        raise NightlyError("Cross-workspace query isolation check failed.")
                report["tenant_isolation_passed"] = True
                grounded = (
                    evaluation.supported_claim_count > 0
                    and evaluation.partial_claim_count
                    == evaluation.unsupported_claim_count
                    == evaluation.invalid_citation_count
                    == 0
                )
                if not evaluation.abstained:
                    all_answers_grounded = (
                        all_answers_grounded and grounded and bool(evaluation.cited_source_ids)
                    )
                correct = (
                    evaluation.abstained
                    if query.expect_abstain
                    else (
                        not evaluation.abstained
                        and grounded
                        and set(query.must_cite_sources) <= set(evaluation.cited_source_ids)
                        and matches_rubric(rubrics[query.id], evaluation.answer_text)
                    )
                )
                if not query.expect_abstain:
                    useful.append(float(correct))
                pairs.append((query, evaluation))
                report["queries"].append(
                    {
                        "query_id": query.id,
                        "passed": bool(correct),
                        "run_id": record.capture["query_run_id"],
                    }
                )
                if report["input_tokens"] + report["output_tokens"] > policy.max_provider_tokens:
                    raise NightlyError("Provider token stop exceeded; no further queries issued.")
            if (
                await inspect_nightly_target(
                    client,
                    manifest,
                    approved_labels=approved_labels,
                    isolation_workspace_id=isolation_workspace_id,
                )
                != snapshot
            ):
                raise NightlyError("Deployment, model or corpus changed during evaluation.")
            aggregate = aggregate_metrics(pairs, [1, 5, 10])
            aggregate.pop("estimated_cost_usd_total", None)
            aggregate["useful_answer_rate"] = sum(useful) / len(useful) if useful else 0.0
            report["aggregate"] = aggregate
            report["usage_complete"] = True
            if (
                not all_answers_grounded
                or aggregate["useful_answer_rate"] < policy.min_useful_answer_rate
                or aggregate["abstention_accuracy"] < policy.min_abstention_accuracy
                or aggregate["latency_ms_p95"] > policy.max_latency_ms_p95
            ):
                raise NightlyError("Quality or latency threshold failed.")
            report["status"] = "passed"
    except NightlyError as exc:
        report["failure"] = str(exc)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, TimeoutError):
        report["failure"] = "Public API evaluation failed or timed out; inspect server-side runs."
    if pairs:
        aggregate = aggregate_metrics(pairs, [1, 5, 10])
        aggregate.pop("estimated_cost_usd_total", None)
        aggregate["useful_answer_rate"] = sum(useful) / len(useful) if useful else 0.0
        report["aggregate"] = aggregate
    return report


def _normalized_terms(text: str) -> str:
    text = re.sub(r"(?<=\d),(?=\d)", "", text.casefold())
    text = re.sub(r"\d+(?:\.\d+)?", lambda match: format(Decimal(match[0]).normalize(), "f"), text)
    text = re.sub(r"(?<=\d)(?=[a-z])", " ", text)
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)
    text = re.sub(r"[^a-z0-9.]+", " ", text)
    return " " + " ".join(text.split()) + " "


def matches_rubric(rubric: AnswerRubric, answer: str) -> bool:
    """All concept/value/unit groups must match; no model judge or inferred gold labels.

    This bounded literal rubric is a smoke assertion, not a complete financial-reasoning judge.
    """
    normalized = _normalized_terms(answer)
    return all(
        any(_normalized_terms(term) in normalized for term in group) for group in rubric.groups
    )
