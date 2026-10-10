"""Bounded, opt-in synthetic-corpus preparation through public ingestion APIs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from flint_graph.evaluation.capture import CaptureManifest
from flint_graph.evaluation.datasets import GoldenDataset

_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".text": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
}
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_CORPUS_BYTES = 64 * 1024 * 1024
_MAX_FILES = 100


@dataclass(frozen=True, slots=True)
class CorpusSource:
    label: str
    filename: str
    content_type: str
    content: bytes


def load_corpus(directory: Path, dataset: GoldenDataset) -> list[CorpusSource]:
    root = directory.resolve(strict=True)
    corpus = (root / dataset.metadata.corpus_dir).resolve(strict=True)
    if not corpus.is_relative_to(root) or corpus == root:
        raise ValueError("Corpus directory must stay within the dataset directory.")
    files = sorted(path for path in corpus.rglob("*") if path.is_file())
    if not files or len(files) > _MAX_FILES:
        raise ValueError(f"Corpus must contain 1..{_MAX_FILES} files.")
    sources: list[CorpusSource] = []
    labels: set[str] = set()
    total_bytes = 0
    for path in files:
        resolved_path = path.resolve(strict=True)
        if not resolved_path.is_relative_to(corpus):
            raise ValueError(
                "Corpus files must stay within the corpus directory (including symlinks)."
            )
        if path.suffix.lower() not in _CONTENT_TYPES:
            raise ValueError(f"Unsupported corpus file '{path.name}'.")
        if path.stem in labels:
            raise ValueError(f"Duplicate corpus label '{path.stem}'.")
        if not path.stem or len(path.stem) > 200:
            raise ValueError("Corpus filename stems must contain 1..200 characters.")
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError(f"Corpus file '{path.name}' exceeds the byte limit.")
        with resolved_path.open("rb") as source_file:
            content = source_file.read(_MAX_FILE_BYTES + 1)
        total_bytes += len(content)
        if not content or len(content) > _MAX_FILE_BYTES or total_bytes > _MAX_CORPUS_BYTES:
            raise ValueError("Corpus contains an empty file or exceeds bounded file/corpus bytes.")
        labels.add(path.stem)
        sources.append(
            CorpusSource(path.stem, path.name, _CONTENT_TYPES[path.suffix.lower()], content)
        )
    return sources


async def prepare_corpus(
    client: httpx.AsyncClient,
    dataset: GoldenDataset,
    sources: Sequence[CorpusSource],
    *,
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 1,
    on_workspace_created: Callable[[UUID], None] | None = None,
) -> CaptureManifest:
    if (
        not sources
        or len(sources) > _MAX_FILES
        or timeout_seconds <= 0
        or poll_interval_seconds < 0
    ):
        raise ValueError("Preparation requires a bounded corpus and valid timeout/poll interval.")
    if (
        len({source.label for source in sources}) != len(sources)
        or sum(len(source.content) for source in sources) > _MAX_CORPUS_BYTES
        or any(not source.content or len(source.content) > _MAX_FILE_BYTES for source in sources)
    ):
        raise ValueError("Preparation requires unique labels and bounded nonempty source bytes.")
    workspace_id: UUID | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            workspace_name = (
                f"eval-{dataset.metadata.name[:100]}-v{dataset.metadata.version}-{uuid4().hex[:8]}"
            )
            workspace = await client.post(
                "/v1/workspaces",
                json={
                    "name": workspace_name,
                },
            )
            workspace.raise_for_status()
            workspace_id = UUID(workspace.json()["id"])
            if on_workspace_created is not None:
                on_workspace_created(workspace_id)
            headers = {"X-Tenant-ID": str(workspace_id)}
            index = await client.post("/v1/retrieval-index/bootstrap", headers=headers)
            index.raise_for_status()
            index_id = str(index.json()["id"])
            document_labels: dict[str, str] = {}
            versions: dict[str, str] = {}
            jobs: dict[str, str] = {}
            for source in sources:
                uploaded = await client.post(
                    "/v1/documents/uploads",
                    headers={**headers, "Idempotency-Key": f"eval-{uuid4().hex}"},
                    data={"title": source.label, "external_id": source.label},
                    files={"file": (source.filename, source.content, source.content_type)},
                )
                uploaded.raise_for_status()
                body = uploaded.json()
                document_labels[str(body["document_id"])] = source.label
                versions[str(body["document_version_id"])] = str(body["document_id"])
                jobs[str(body["ingestion_job_id"])] = source.label
            completed_jobs: set[str] = set()
            visible_projections: set[tuple[str, str]] = set()
            while True:
                for job_id, label in jobs.items():
                    if job_id in completed_jobs:
                        continue
                    response = await client.get(f"/v1/ingestion-jobs/{job_id}", headers=headers)
                    response.raise_for_status()
                    status = response.json()["status"]
                    if status in {"failed", "cancelled"}:
                        raise ValueError(
                            f"Ingestion {status} for '{label}'; workspace '{workspace_id}' remains."
                        )
                    if status == "completed":
                        completed_jobs.add(job_id)
                coverage = await client.get(
                    "/v1/index-coverage",
                    headers=headers,
                    params={
                        "retrieval_index_version_id": index_id,
                        "limit": 500,
                    },
                )
                coverage.raise_for_status()
                covered: set[str] = set()
                for row in coverage.json():
                    version_id = str(row["document_version_id"])
                    if (
                        version_id not in versions
                        or str(row["retrieval_index_version_id"]) != index_id
                    ):
                        continue
                    if row["status"] in {"failed", "cancelled"}:
                        raise ValueError(
                            f"Index coverage {row['status']}; workspace '{workspace_id}' remains."
                        )
                    if row["status"] == "completed" and row["chunk_count"] > 0:
                        covered.add(version_id)
                if len(completed_jobs) == len(jobs) and covered == set(versions):
                    for version_id, document_id in versions.items():
                        for kind in ("lexical", "vector"):
                            probe_id = (version_id, kind)
                            if probe_id in visible_projections:
                                continue
                            probe = await client.post(
                                f"/v1/search/{kind}",
                                headers=headers,
                                json={
                                    "query": document_labels[document_id],
                                    "limit": 50,
                                    "retrieval_index_version_id": index_id,
                                    "filters": {"document_version_id": version_id},
                                },
                            )
                            probe.raise_for_status()
                            if any(
                                str(hit["document_version_id"]) == version_id
                                for hit in probe.json()["results"]
                            ):
                                visible_projections.add(probe_id)
                    if len(visible_projections) == 2 * len(versions):
                        break
                await asyncio.sleep(poll_interval_seconds)
            entities = await client.get(
                "/v1/entities", headers=headers, params={"status": "active", "limit": 500}
            )
            entities.raise_for_status()
            readiness = await client.get("/v1/system-readiness", headers=headers)
            readiness.raise_for_status()
            return CaptureManifest(
                tenant_id=workspace_id,
                dataset_name=dataset.metadata.name,
                dataset_version=dataset.metadata.version,
                document_labels=document_labels,
                entity_labels={str(row["id"]): row["canonical_name"] for row in entities.json()},
                preparation={
                    "prepared_at": datetime.now(UTC).isoformat(),
                    "retrieval_index_version_id": index_id,
                    "document_versions": versions,
                    "ingestion_jobs": jobs,
                    "projection_visibility_probed": True,
                    "system_readiness": readiness.json(),
                },
            )
    except TimeoutError as exc:
        raise ValueError(
            f"Preparation timed out; created workspace '{workspace_id}' remains inspectable."
        ) from exc
