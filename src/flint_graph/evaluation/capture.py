"""Opt-in fresh query capture. Never infer relevance labels from answer text."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from flint_graph.evaluation.datasets import GoldenDataset
from flint_graph.evaluation.metrics import QueryEvaluation
from flint_graph.evaluation.recorded import RecordedEvaluation


class CaptureManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    dataset_name: str
    dataset_version: int = Field(ge=1)
    chunk_labels: dict[str, str] = Field(default_factory=dict)
    document_labels: dict[str, str] = Field(default_factory=dict)
    entity_labels: dict[str, str] = Field(default_factory=dict)
    relationship_labels: dict[str, str] = Field(default_factory=dict)


class CapturedEvaluation(RecordedEvaluation):
    capture: dict[str, Any]


async def capture_dataset(
    client: httpx.AsyncClient,
    dataset: GoldenDataset,
    manifest: CaptureManifest,
    *,
    git_sha: str | None = None,
    query_timeout_seconds: float = 300.0,
) -> list[CapturedEvaluation]:
    if (manifest.dataset_name, manifest.dataset_version) != (
        dataset.metadata.name,
        dataset.metadata.version,
    ):
        raise ValueError("Capture manifest does not match the dataset name/version.")
    if not dataset.queries or query_timeout_seconds <= 0:
        raise ValueError("Capture requires a nonempty dataset and a positive timeout.")
    headers = {"X-Tenant-ID": str(manifest.tenant_id)}
    records: list[CapturedEvaluation] = []
    for query in dataset.queries:
        started = perf_counter()
        async with asyncio.timeout(query_timeout_seconds):
            created = await client.post(
                "/v1/query-runs", headers=headers, json={"query": query.query}
            )
            created.raise_for_status()
            run_id = str(created.json()["id"])
            path = f"/v1/query-runs/{run_id}"
            # SSE currently starts execution. Consume it, but never turn draft JSON into answers.
            async with client.stream("GET", f"{path}/events/stream", headers=headers) as stream:
                stream.raise_for_status()
                async for _line in stream.aiter_lines():
                    pass
            inspected = await client.get(path, headers=headers)
            inspected.raise_for_status()
            run = inspected.json()
            if run["status"] != "completed":
                raise ValueError(
                    f"Query '{query.id}' run '{run_id}' did not complete ({run['status']})."
                )
            retrieval = await client.get(f"{path}/retrieval", headers=headers)
            retrieval.raise_for_status()
            provenance = await client.get(f"{path}/provenance", headers=headers)
            provenance.raise_for_status()
        evaluation = _evaluation(
            retrieval.json(),
            provenance.json(),
            manifest,
            (perf_counter() - started) * 1000,
        )
        records.append(
            CapturedEvaluation(
                query_id=query.id,
                evaluation=evaluation,
                capture={
                    "format_version": 1,
                    "dataset_name": dataset.metadata.name,
                    "dataset_version": dataset.metadata.version,
                    "captured_at": datetime.now(UTC).isoformat(),
                    "git_sha": git_sha,
                    "query_run_id": run_id,
                    "tenant_id": str(manifest.tenant_id),
                    "retrieval_index_version_id": run["retrieval_index_version_id"],
                    "retrieval_stage": "post_rerank",
                    "query_diagnostics": run.get("query_diagnostics", {}),
                },
            )
        )
    return records


def _evaluation(
    trace: dict[str, Any],
    provenance: dict[str, Any],
    manifest: CaptureManifest,
    latency_ms: float,
) -> QueryEvaluation:
    selected = sorted(
        (row for row in trace["candidates"] if row.get("rerank_rank") is not None),
        key=lambda row: (row["rerank_rank"], row["candidate_id"]),
    )
    chunks: list[str] = []
    entities: list[str] = []
    for row in selected:
        if row["candidate_type"] == "chunk":
            chunks.append(_source_label(row["source_ids"], row.get("document_id"), manifest))
        for key in ("subject_entity_id", "object_entity_id"):
            if row.get(key):
                entity_id = str(row[key])
                if entity_id not in manifest.entity_labels:
                    raise ValueError(
                        f"Unmapped retrieved entity '{entity_id}' in capture manifest."
                    )
                entities.append(manifest.entity_labels[entity_id])
    citations = {row["citation_id"]: row for row in provenance["citations"]}
    cited: list[str] = []
    invalid = 0
    for reference in provenance["answer_citations"]:
        citation = citations.get(reference["citation_id"])
        if citation is None or citation.get("source_active") is False:
            invalid += 1
            continue
        cited.append(
            _source_label(citation["source_ids"], citation.get("source_document_id"), manifest)
        )
    statuses = [claim["support_status"] for claim in provenance["claims"]]
    return QueryEvaluation(
        retrieved_chunk_ids=list(dict.fromkeys(chunks)),
        retrieved_entity_ids=list(dict.fromkeys(entities)),
        answer_text=provenance.get("answer_text") or "",
        abstained=provenance["abstained"],
        cited_source_ids=list(dict.fromkeys(cited)),
        supported_claim_count=statuses.count("supported"),
        partial_claim_count=statuses.count("partial"),
        unsupported_claim_count=statuses.count("unsupported"),
        invalid_citation_count=invalid,
        latency_ms=latency_ms,
    )


def _source_label(source_ids: dict[str, str], document_id: Any, manifest: CaptureManifest) -> str:
    chunk_id = source_ids.get("chunk_id")
    if chunk_id in manifest.chunk_labels:
        return manifest.chunk_labels[chunk_id]
    if document_id is not None and str(document_id) in manifest.document_labels:
        return manifest.document_labels[str(document_id)]
    relationship_id = source_ids.get("relationship_id")
    if relationship_id in manifest.relationship_labels:
        return manifest.relationship_labels[relationship_id]
    raise ValueError(f"Unmapped retrieved/cited source '{source_ids}' in capture manifest.")
