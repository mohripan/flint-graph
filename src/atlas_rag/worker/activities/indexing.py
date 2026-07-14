from __future__ import annotations

from uuid import UUID

import httpx
from temporalio import activity
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from atlas_rag.application.embeddings import DeterministicEmbeddingModel, EmbeddingModel
from atlas_rag.application.outbox_contracts import (
    DocumentIndexingFailurePayload,
    IndexDocumentBatchPayload,
    IndexDocumentVersionPayload,
    IngestionJobQueuedPayload,
    PreparedDocumentIndexingPayload,
)
from atlas_rag.application.services.indexing import (
    IndexingBatchRequest,
    cancel_document_indexing,
    complete_document_indexing,
    fail_document_indexing,
    index_document_version_batch,
    plan_document_indexing,
    select_active_retrieval_index_version,
)
from atlas_rag.config import Settings, get_settings
from atlas_rag.infrastructure.db.session import SessionFactory
from atlas_rag.infrastructure.embeddings import OpenAICompatibleEmbeddingModel
from atlas_rag.infrastructure.neo4j import create_neo4j_client
from atlas_rag.infrastructure.ollama import OllamaEmbeddingModel
from atlas_rag.infrastructure.opensearch import create_opensearch_client
from atlas_rag.infrastructure.temporal import connect_temporal
from atlas_rag.workflows.indexing import (
    INDEX_DOCUMENT_BATCH_ACTIVITY,
    INDEX_DOCUMENT_VERSION_WORKFLOW,
    MARK_INDEXING_CANCELLED_ACTIVITY,
    MARK_INDEXING_COMPLETED_ACTIVITY,
    MARK_INDEXING_FAILED_ACTIVITY,
    PLAN_DOCUMENT_INDEXING_ACTIVITY,
)
from atlas_rag.workflows.ingestion import (
    ENQUEUE_DOCUMENT_INDEXING_ACTIVITY,
    PREPARE_DOCUMENT_INDEXING_ACTIVITY,
)


async def prepare_document_indexing_for_payload(
    payload: IngestionJobQueuedPayload,
    *,
    settings: Settings,
) -> PreparedDocumentIndexingPayload:
    mode = settings.indexing_mode
    if mode == "disabled":
        return {"mode": mode, "should_index": False}

    tenant_id = UUID(payload["tenant_id"])
    try:
        configured_index_version_id = (
            UUID(settings.active_retrieval_index_version_id)
            if settings.active_retrieval_index_version_id is not None
            else None
        )
        async with SessionFactory() as session:
            index_version = await select_active_retrieval_index_version(
                session,
                tenant_id=tenant_id,
                configured_index_version_id=configured_index_version_id,
            )
    except Exception:
        if mode == "required":
            raise
        return {"mode": mode, "should_index": False}

    if index_version is None:
        if mode == "required":
            raise RuntimeError("required indexing has no active retrieval index version")
        return {"mode": mode, "should_index": False}

    return {
        "mode": mode,
        "should_index": True,
        "payload": {
            "tenant_id": payload["tenant_id"],
            "document_id": payload["document_id"],
            "document_version_id": payload["document_version_id"],
            "retrieval_index_version_id": str(index_version.id),
            "source": "ingestion",
        },
    }


@activity.defn(name=PREPARE_DOCUMENT_INDEXING_ACTIVITY)
async def prepare_document_indexing(
    payload: IngestionJobQueuedPayload,
) -> PreparedDocumentIndexingPayload:
    return await prepare_document_indexing_for_payload(payload, settings=get_settings())


@activity.defn(name=ENQUEUE_DOCUMENT_INDEXING_ACTIVITY)
async def enqueue_document_indexing(payload: IndexDocumentVersionPayload) -> None:
    settings = get_settings()
    client = await connect_temporal(settings)
    await client.start_workflow(
        INDEX_DOCUMENT_VERSION_WORKFLOW,
        payload,
        id=_indexing_workflow_id(payload),
        task_queue=settings.temporal_task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )


@activity.defn(name=PLAN_DOCUMENT_INDEXING_ACTIVITY)
async def plan_document_indexing_activity(
    payload: IndexDocumentVersionPayload,
) -> dict[str, int]:
    settings = get_settings()
    async with SessionFactory() as session:
        try:
            plan = await plan_document_indexing(
                session,
                tenant_id=UUID(payload["tenant_id"]),
                document_id=UUID(payload["document_id"]),
                document_version_id=UUID(payload["document_version_id"]),
                retrieval_index_version_id=UUID(payload["retrieval_index_version_id"]),
                batch_size=settings.embedding_batch_size,
            )
            await session.commit()
            return {
                "chunk_count": plan.chunk_count,
                "batch_count": plan.batch_count,
            }
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=INDEX_DOCUMENT_BATCH_ACTIVITY)
async def index_document_batch(payload: IndexDocumentBatchPayload) -> dict[str, int]:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=_embedding_base_url(settings)) as http_client:
        embedding_model = _embedding_model_from_settings(settings, http_client=http_client)
        neo4j_client = create_neo4j_client(settings)
        opensearch_client = create_opensearch_client(settings)
        async with SessionFactory() as session:
            try:
                result = await index_document_version_batch(
                    session,
                    IndexingBatchRequest(
                        tenant_id=UUID(payload["tenant_id"]),
                        document_id=UUID(payload["document_id"]),
                        document_version_id=UUID(payload["document_version_id"]),
                        retrieval_index_version_id=UUID(payload["retrieval_index_version_id"]),
                        batch_index=payload["batch_index"],
                        batch_size=settings.embedding_batch_size,
                    ),
                    embedding_model=embedding_model,
                    neo4j_client=neo4j_client,
                    opensearch_client=opensearch_client,
                )
                await session.commit()
                return {
                    "embedded_count": result.embedded_count,
                    "vector_count": result.vector_count,
                    "lexical_count": result.lexical_count,
                }
            except Exception:
                await session.rollback()
                raise
            finally:
                await neo4j_client.close()
                await opensearch_client.close()


@activity.defn(name=MARK_INDEXING_COMPLETED_ACTIVITY)
async def mark_document_indexing_completed(payload: IndexDocumentVersionPayload) -> None:
    async with SessionFactory() as session:
        try:
            await complete_document_indexing(
                session,
                tenant_id=UUID(payload["tenant_id"]),
                document_version_id=UUID(payload["document_version_id"]),
                retrieval_index_version_id=UUID(payload["retrieval_index_version_id"]),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=MARK_INDEXING_FAILED_ACTIVITY)
async def mark_document_indexing_failed(failure: DocumentIndexingFailurePayload) -> None:
    payload = failure["payload"]
    async with SessionFactory() as session:
        try:
            await fail_document_indexing(
                session,
                tenant_id=UUID(payload["tenant_id"]),
                document_version_id=UUID(payload["document_version_id"]),
                retrieval_index_version_id=UUID(payload["retrieval_index_version_id"]),
                error_code=failure["error_code"],
                error_message=failure["error_message"],
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@activity.defn(name=MARK_INDEXING_CANCELLED_ACTIVITY)
async def mark_document_indexing_cancelled(payload: IndexDocumentVersionPayload) -> None:
    async with SessionFactory() as session:
        try:
            await cancel_document_indexing(
                session,
                tenant_id=UUID(payload["tenant_id"]),
                document_version_id=UUID(payload["document_version_id"]),
                retrieval_index_version_id=UUID(payload["retrieval_index_version_id"]),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _embedding_model_from_settings(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient,
) -> EmbeddingModel:
    if settings.embedding_provider == "deterministic":
        return DeterministicEmbeddingModel()
    if settings.embedding_provider == "ollama":
        return OllamaEmbeddingModel(
            model=settings.embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
            http_client=http_client,
            base_url=settings.embedding_ollama_base_url,
        )
    if settings.embedding_openai_api_key is None:
        raise RuntimeError("embedding_openai_api_key is required")
    return OpenAICompatibleEmbeddingModel(
        model=settings.embedding_model,
        api_key=settings.embedding_openai_api_key,
        timeout_seconds=settings.embedding_timeout_seconds,
        http_client=http_client,
        base_url=settings.embedding_openai_base_url,
    )


def _embedding_base_url(settings: Settings) -> str:
    if settings.embedding_provider == "ollama":
        return settings.embedding_ollama_base_url
    return settings.embedding_openai_base_url or "https://api.openai.com"


def _indexing_workflow_id(payload: IndexDocumentVersionPayload) -> str:
    return (
        "index-document-version-"
        f"{payload['document_version_id']}-{payload['retrieval_index_version_id']}"
    )
