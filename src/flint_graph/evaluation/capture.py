"""Opt-in fresh query capture. Never infer relevance labels from answer text."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    preparation: dict[str, Any] = Field(default_factory=dict)


class CapturedEvaluation(RecordedEvaluation):
    capture: dict[str, Any]


class _FreshConversation(BaseModel):
    id: UUID
    tenant_id: UUID
    next_turn_number: int = Field(strict=True, ge=1, le=1)
    archived_at: None


class _ConversationRun(BaseModel):
    id: UUID
    tenant_id: UUID
    retrieval_index_version_id: UUID
    query_text: str
    status: str


class _CapturedTurn(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    turn_number: int = Field(strict=True, ge=1)
    idempotency_key: UUID
    run: _ConversationRun


async def capture_dataset(
    client: httpx.AsyncClient,
    dataset: GoldenDataset,
    manifest: CaptureManifest,
    *,
    git_sha: str | None = None,
    query_timeout_seconds: float = 300.0,
    conversation: bool = False,
    conversation_timeout_seconds: float = 900.0,
) -> list[CapturedEvaluation]:
    if (manifest.dataset_name, manifest.dataset_version) != (
        dataset.metadata.name,
        dataset.metadata.version,
    ):
        raise ValueError("Capture manifest does not match the dataset name/version.")
    if not dataset.queries or query_timeout_seconds <= 0:
        raise ValueError("Capture requires a nonempty dataset and a positive timeout.")
    if conversation and (
        len(dataset.queries) > 8
        or not math.isfinite(query_timeout_seconds)
        or query_timeout_seconds > 300
        or not math.isfinite(conversation_timeout_seconds)
        or not 0 < conversation_timeout_seconds <= 900
    ):
        raise ValueError(
            "Conversation capture requires at most 8 turns, a finite turn timeout <= 300s, "
            "and a finite total timeout in (0, 900]s."
        )
    if conversation:
        async with asyncio.timeout(conversation_timeout_seconds):
            return await _capture_dataset(
                client,
                dataset,
                manifest,
                git_sha=git_sha,
                query_timeout_seconds=query_timeout_seconds,
                conversation=True,
                conversation_timeout_seconds=conversation_timeout_seconds,
            )
    return await _capture_dataset(
        client,
        dataset,
        manifest,
        git_sha=git_sha,
        query_timeout_seconds=query_timeout_seconds,
        conversation=False,
        conversation_timeout_seconds=conversation_timeout_seconds,
    )


async def _capture_dataset(
    client: httpx.AsyncClient,
    dataset: GoldenDataset,
    manifest: CaptureManifest,
    *,
    git_sha: str | None,
    query_timeout_seconds: float,
    conversation: bool,
    conversation_timeout_seconds: float,
) -> list[CapturedEvaluation]:
    headers = {"X-Tenant-ID": str(manifest.tenant_id)}
    conversation_id = None
    if conversation:
        async with asyncio.timeout(query_timeout_seconds):
            created_conversation = await client.post("/v1/conversations", headers=headers, json={})
            created_conversation.raise_for_status()
            try:
                fresh = _FreshConversation.model_validate(created_conversation.json())
            except ValidationError:
                raise ValueError(
                    "Conversation capture received an invalid fresh conversation."
                ) from None
            if fresh.tenant_id != manifest.tenant_id:
                raise ValueError("Conversation capture received a foreign conversation.")
            conversation_id = str(fresh.id)
    records: list[CapturedEvaluation] = []
    conversation_index: UUID | None = None
    for query in dataset.queries:
        started = perf_counter()
        async with asyncio.timeout(query_timeout_seconds):
            turn = None
            if conversation_id is not None:
                key = uuid4()
                created = await client.post(
                    f"/v1/conversations/{conversation_id}/turns",
                    headers=headers,
                    json={"query": query.query, "idempotency_key": str(key)},
                )
                created.raise_for_status()
                try:
                    accepted = _CapturedTurn.model_validate(created.json())
                except ValidationError:
                    raise ValueError(
                        "Conversation capture received invalid turn references."
                    ) from None
                if (
                    accepted.tenant_id != manifest.tenant_id
                    or str(accepted.conversation_id) != conversation_id
                    or accepted.turn_number != len(records) + 1
                    or accepted.idempotency_key != key
                    or accepted.run.tenant_id != manifest.tenant_id
                    or accepted.run.query_text != " ".join(query.query.split())
                    or accepted.run.status != "queued"
                ):
                    raise ValueError("Conversation capture received mismatched turn references.")
                if (
                    conversation_index is not None
                    and accepted.run.retrieval_index_version_id != conversation_index
                ):
                    raise ValueError("Conversation capture changed retrieval index between turns.")
                conversation_index = accepted.run.retrieval_index_version_id
                turn = accepted.model_dump(mode="json")
                run_id = str(accepted.run.id)
            else:
                created = await client.post(
                    "/v1/query-runs", headers=headers, json={"query": query.query}
                )
                created.raise_for_status()
                run_id = str(created.json()["id"])
            path = f"/v1/query-runs/{run_id}"
            # SSE currently starts execution. Consume it, but never turn draft JSON into answers.
            async with client.stream(
                "GET", f"{path}/events/stream", headers=headers, timeout=query_timeout_seconds
            ) as stream:
                stream.raise_for_status()
                async for _line in stream.aiter_lines():
                    pass
            inspected = await client.get(path, headers=headers)
            inspected.raise_for_status()
            run = inspected.json()
            if turn is not None:
                try:
                    final_reference = _ConversationRun.model_validate(run)
                except ValidationError:
                    raise ValueError(
                        "Conversation capture received invalid final run references."
                    ) from None
                if final_reference.model_copy(update={"status": "queued"}) != accepted.run:
                    raise ValueError(
                        "Conversation capture received mismatched final run references."
                    )
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
        evaluation = evaluation.model_copy(
            update={
                "input_tokens": run.get("provider_input_tokens"),
                "output_tokens": run.get("provider_output_tokens"),
            }
        )
        records.append(
            CapturedEvaluation(
                query_id=query.id,
                evaluation=evaluation,
                capture={
                    "format_version": 3 if conversation_id is not None else 2,
                    **(
                        {
                            "conversation_id": conversation_id,
                            "conversation_turn_id": turn["id"],
                            "conversation_turn_number": turn["turn_number"],
                            "conversation_limits": {
                                "max_turns": 8,
                                "turn_timeout_seconds": query_timeout_seconds,
                                "total_timeout_seconds": conversation_timeout_seconds,
                            },
                            "conversation_context": run.get("metadata", {}).get(
                                "conversation_context", {}
                            ),
                        }
                        if turn is not None
                        else {}
                    ),
                    "provider_usage_complete": has_complete_query_usage(run),
                    "usage_scope": "query-invocations-v1",
                    "dataset_name": dataset.metadata.name,
                    "dataset_version": dataset.metadata.version,
                    "captured_at": datetime.now(UTC).isoformat(),
                    "git_sha": git_sha,
                    "query_run_id": run_id,
                    "tenant_id": str(manifest.tenant_id),
                    "retrieval_index_version_id": run["retrieval_index_version_id"],
                    "retrieval_stage": "post_rerank",
                    "query_diagnostics": run.get("query_diagnostics", {}),
                    "preparation": manifest.preparation,
                },
            )
        )
    return records


def has_complete_query_usage(run: dict[str, Any]) -> bool:
    """Legacy totals are lower bounds, not an attestation of complete usage."""
    metadata = run.get("metadata")
    accounting = metadata.get("usage_accounting") if isinstance(metadata, dict) else None
    if not isinstance(accounting, dict):
        return False
    expected, recorded = accounting.get("expected"), accounting.get("recorded")
    return (
        run.get("provider_usage_complete") is True
        and accounting.get("version") == "query-invocations-v1"
        and accounting.get("complete") is True
        and type(accounting.get("unknown_event_count")) is int
        and accounting["unknown_event_count"] == 0
        and isinstance(expected, dict)
        and isinstance(recorded, dict)
        and set(expected) == {"embedding", "answer", "faithfulness"}
        and expected == recorded
        and all(type(value) is int and value >= 0 for value in expected.values())
        and all(type(value) is int and value >= 0 for value in recorded.values())
    )


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
