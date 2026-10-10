"""Pinned public FinQA report excerpts; annotations never become ingestion evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

REVISION = "0f16e2867befa6840783e58be38c9efb9229d742"
SOURCE_ROOT = f"https://raw.githubusercontent.com/czyssrs/FinQA/{REVISION}"
REPORT_ID = re.compile(r"([A-Za-z0-9_.-]{1,100})/(\d{4})/page_(\d{1,5})\.pdf-\d{1,5}")


class CorpusError(ValueError):
    """Safe, actionable errors without source text or exception payloads."""


@dataclass(frozen=True)
class CorpusSource:
    path: str
    size: int
    git_blob_sha1: str


PINNED_SOURCES = (
    CorpusSource("LICENSE", 1067, "fb3b513238ba5ec7e0799cb1190ff30c759a5bdf"),
    CorpusSource("dataset/dev.json", 10954658, "970f239f591c782b17df420c0d343b780737f3da"),
    CorpusSource("dataset/test.json", 14395143, "59958c7c3bb3b21f4dff6bc912a0fe0ae710aee0"),
)
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_CORPUS_BYTES = 32 * 1024 * 1024
MAX_EXAMPLES = 5000


@dataclass(frozen=True)
class ReportExcerpt:
    company: str
    year: int
    page: int
    source_id: str
    text: str


def render_report_excerpt(record: dict[str, Any]) -> ReportExcerpt:
    source_id = record.get("id")
    match = REPORT_ID.fullmatch(source_id) if isinstance(source_id, str) else None
    if match is None:
        raise CorpusError("Invalid FinQA report identity.")
    company, year, page = match.groups()
    sections: list[list[str]] = []
    for field in ("pre_text", "post_text"):
        values = record.get(field)
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise CorpusError("Invalid FinQA report text.")
        sections.append(values)
    table = record.get("table")
    if (
        not isinstance(table, list)
        or not table
        or any(
            not isinstance(row, list) or not row or any(not isinstance(cell, str) for cell in row)
            for row in table
        )
    ):
        raise CorpusError("Invalid FinQA report table.")
    # The question suffix must not split identical report-page evidence into duplicate documents.
    heading = f"# {company} {year} financial report excerpt, page {page}\n\n"
    heading += "Historical report excerpt supplied by FinQA; not a complete annual report.\n\n"
    rows = [
        "| " + " | ".join(cell.replace("\n", " ").replace("|", "\\|") for cell in row) + " |"
        for row in table
    ]
    rows.insert(1, "| " + " | ".join("---" for _ in table[0]) + " |")
    text = heading + "\n\n".join(("\n".join(sections[0]), "\n".join(rows), "\n".join(sections[1])))
    return ReportExcerpt(company, int(year), int(page), match.group(0), text + "\n")


async def _download(client: httpx.AsyncClient, source: CorpusSource) -> bytes:
    async with client.stream(
        "GET", f"{SOURCE_ROOT}/{source.path}", follow_redirects=False
    ) as response:
        if response.status_code != 200:
            raise CorpusError("Pinned source download failed; redirects are not followed.")
        length = response.headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > source.size):
            raise CorpusError("Pinned source exceeds its byte budget.")
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
            if len(body) + len(chunk) > source.size:
                raise CorpusError("Pinned source exceeds its byte budget.")
            body.extend(chunk)
    if len(body) != source.size:
        raise CorpusError("Pinned source byte count does not match.")
    blob = f"blob {len(body)}\0".encode() + body
    if hashlib.sha1(blob, usedforsecurity=False).hexdigest() != source.git_blob_sha1:
        raise CorpusError("Pinned source Git blob checksum does not match.")
    return bytes(body)


def _write_artifact(output: Path, path: str, body: bytes) -> dict[str, Any]:
    target = output / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(body)
    return {"path": path, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def _new_directory(output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise CorpusError("Choose a new directory; existing artifacts are never overwritten.")
    output.mkdir(parents=True)


async def collect_financial_corpus(
    client: httpx.AsyncClient,
    output: Path,
    *,
    sources: tuple[CorpusSource, ...] = PINNED_SOURCES,
    max_bytes: int = MAX_SOURCE_BYTES,
    max_documents: int = 2000,
    timeout_seconds: float = 180,
) -> dict[str, Any]:
    """Fetch only three allowlisted, pinned files. A manifest marks a complete collection.

    ``sources`` is an integrity-fixture seam, not exposed as CLI/user configuration.
    Nothing imports downloaded code, calls inference, or uploads documents.
    """
    allowed = {"LICENSE", "dataset/dev.json", "dataset/test.json"}
    if {source.path for source in sources} != allowed or len(sources) != 3:
        raise CorpusError("Only the pinned public license/dev/test source paths are allowed.")
    if (
        not 1 <= max_bytes <= MAX_SOURCE_BYTES
        or any(
            not 0 < source.size <= 20 * 1024 * 1024
            or re.fullmatch(r"[0-9a-f]{40}", source.git_blob_sha1) is None
            for source in sources
        )
        or sum(source.size for source in sources) > max_bytes
    ):
        raise CorpusError("Pinned sources exceed the configured byte budget.")
    if not 1 <= max_documents <= MAX_EXAMPLES or not 0 < timeout_seconds <= 600:
        raise CorpusError("Invalid document count or timeout budget.")
    await asyncio.to_thread(_new_directory, output)
    payloads: list[bytes] = []
    try:
        # Sequential bounded downloads keep at most one request in flight and cap total memory.
        async with asyncio.timeout(timeout_seconds):
            for source in sources:
                payloads.append(await _download(client, source))
    except (httpx.HTTPError, TimeoutError) as exc:
        raise CorpusError(
            "Pinned source download failed or timed out; no complete manifest."
        ) from exc
    return await asyncio.to_thread(_build_collection, output, sources, payloads, max_documents)


def _build_collection(
    output: Path, sources: tuple[CorpusSource, ...], payloads: list[bytes], max_documents: int
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    documents: dict[str, dict[str, Any]] = {}
    annotations: list[dict[str, Any]] = []
    report_ids: set[tuple[str, int]] = set()
    corpus_bytes = 0
    examples_seen: set[tuple[str, str]] = set()
    for source, body in zip(sources, payloads, strict=True):
        path = "LICENSE" if source.path == "LICENSE" else f"raw/{Path(source.path).name}"
        artifact = _write_artifact(output, path, body)
        files.append(artifact)
        source_records.append(
            {
                **artifact,
                "source_path": source.path,
                "url": f"{SOURCE_ROOT}/{source.path}",
                "git_blob_sha1": source.git_blob_sha1,
            }
        )
        if source.path == "LICENSE":
            continue
        try:
            records = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise CorpusError("Pinned source is not valid JSON.") from exc
        if not isinstance(records, list) or len(records) > MAX_EXAMPLES:
            raise CorpusError("Invalid or oversized public example list.")
        split = Path(source.path).stem
        for record in records:
            if not isinstance(record, dict):
                raise CorpusError("Invalid public example record.")
            excerpt = render_report_excerpt(record)
            identity = (split, excerpt.source_id)
            if identity in examples_seen or len(examples_seen) >= MAX_EXAMPLES:
                raise CorpusError("Duplicate or excessive public example identities.")
            examples_seen.add(identity)
            encoded = excerpt.text.encode("utf-8")
            digest = hashlib.sha256(encoded).hexdigest()
            # Limit applies to unique documents; all associated expert annotations remain separate.
            if digest not in documents and len(documents) >= max_documents:
                continue
            qa = record.get("qa")
            if not isinstance(qa, dict):
                raise CorpusError("Invalid public annotation record.")
            example = {"split": split, "source_id": excerpt.source_id, "source_path": source.path}
            if digest not in documents:
                if (
                    len(encoded) > MAX_DOCUMENT_BYTES
                    or corpus_bytes + len(encoded) > MAX_CORPUS_BYTES
                ):
                    raise CorpusError("Rendered evidence exceeds its byte budget.")
                artifact = _write_artifact(output, f"corpus/finqa-{digest}.md", encoded)
                files.append(artifact)
                documents[digest] = {
                    **artifact,
                    "company": excerpt.company,
                    "year": excerpt.year,
                    "page": excerpt.page,
                    "examples": [],
                }
                corpus_bytes += len(encoded)
                report_ids.add((excerpt.company, excerpt.year))
            documents[digest]["examples"].append(example)
            annotations.append({**example, "document_path": documents[digest]["path"], "qa": qa})
    if not documents:
        raise CorpusError("No financial report evidence was selected.")
    annotation_bytes = "".join(
        json.dumps(item, ensure_ascii=False) + "\n" for item in annotations
    ).encode()
    if len(annotation_bytes) > MAX_SOURCE_BYTES:
        raise CorpusError("Annotation artifact exceeds its byte budget.")
    files.append(_write_artifact(output, "annotations.jsonl", annotation_bytes))
    attribution = (
        f"FinQA public development and test report excerpts, revision {REVISION}.\n"
        "Source: https://github.com/czyssrs/FinQA\n"
        "Dataset release: MIT, Copyright (c) 2021 Zhiyu Chen; see LICENSE.\n"
        "Original issuer reports retain their applicable rights. These are historical excerpts,\n"
        "not complete annual reports, current financial advice, or a redistribution clearance.\n"
        "Only corpus/ contains uploadable evidence. raw/ and annotations.jsonl contain gold\n"
        "labels and MUST NOT be ingested. Public benchmark contamination is possible.\n"
        "No private_test data, train data, downloaded code, or inference models are fetched.\n"
    ).encode()
    files.append(_write_artifact(output, "ATTRIBUTION.txt", attribution))
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset": "finqa-public-excerpts",
        "revision": REVISION,
        "license": "MIT dataset release; original issuer rights preserved",
        "source_bytes": sum(len(body) for body in payloads),
        "corpus_bytes": corpus_bytes,
        "example_count": len(annotations),
        "available_example_count": len(examples_seen),
        "document_count": len(documents),
        "report_count": len(report_ids),
        "truncated": len(annotations) != len(examples_seen),
        "sources": source_records,
        "documents": list(documents.values()),
        "files": files,
    }
    _write_artifact(output, "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest


def verify_financial_corpus(
    output: Path, *, sources: tuple[CorpusSource, ...] = PINNED_SOURCES
) -> dict[str, Any]:
    """Verify artifact integrity plus source bytes against independently pinned Git blob IDs.

    Re-render verified sources so rewriting a local manifest cannot inject gold labels.
    """
    manifest_path = output / "manifest.json"
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or manifest_path.stat().st_size > 10 * 1024 * 1024
    ):
        raise CorpusError("Missing or oversized corpus manifest.")
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (ValueError, UnicodeError) as exc:
        raise CorpusError("Invalid corpus manifest.") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("revision") != REVISION
    ):
        raise CorpusError("Unsupported corpus manifest or revision.")
    files = manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_EXAMPLES + 5:
        raise CorpusError("Invalid artifact file list.")
    verified: dict[str, dict[str, Any]] = {}
    verified_bytes = 0
    root = output.resolve()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise CorpusError("Invalid artifact path.")
        relative = PurePosixPath(item["path"])
        target = output / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in item["path"]
            or ":" in item["path"]
            or target.is_symlink()
            or not target.resolve().is_relative_to(root)
            or item["path"] in verified
        ):
            raise CorpusError("Unsafe or duplicate artifact path.")
        size = item.get("bytes")
        if not isinstance(size, int) or not 0 <= size <= MAX_SOURCE_BYTES or not target.is_file():
            raise CorpusError("Invalid artifact size or missing file.")
        verified_bytes += size
        if verified_bytes > 4 * MAX_SOURCE_BYTES:
            raise CorpusError("Artifact files exceed the total verification byte budget.")
        if target.stat().st_size != size or hashlib.sha256(
            target.read_bytes()
        ).hexdigest() != item.get("sha256"):
            raise CorpusError("Artifact checksum or size does not match.")
        verified[item["path"]] = item
    source_records = manifest.get("sources")
    if not isinstance(source_records, list) or len(source_records) != len(sources):
        raise CorpusError("Invalid pinned source list.")
    evidence_hashes: set[str] = set()
    for source in sources:
        matches = [
            item
            for item in source_records
            if isinstance(item, dict) and item.get("source_path") == source.path
        ]
        if len(matches) != 1:
            raise CorpusError("Missing or duplicate pinned source.")
        record = matches[0]
        expected_path = "LICENSE" if source.path == "LICENSE" else f"raw/{Path(source.path).name}"
        if record.get("path") != expected_path or expected_path not in verified:
            raise CorpusError("Invalid pinned source artifact path.")
        raw = (output / expected_path).read_bytes()
        blob = f"blob {len(raw)}\0".encode() + raw
        if (
            len(raw) != source.size
            or hashlib.sha1(blob, usedforsecurity=False).hexdigest() != source.git_blob_sha1
        ):
            raise CorpusError("Pinned source checksum does not match reviewed source identity.")
        if source.path != "LICENSE":
            for record in json.loads(raw):
                evidence_hashes.add(
                    hashlib.sha256(render_report_excerpt(record).text.encode()).hexdigest()
                )
    documents = manifest.get("documents")
    if not isinstance(documents, list) or len(documents) != manifest.get("document_count"):
        raise CorpusError("Invalid evidence document list.")
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("path"), str):
            raise CorpusError("Invalid evidence document record.")
        artifact = verified.get(document["path"])
        if (
            not document["path"].startswith("corpus/finqa-")
            or artifact is None
            or any(artifact[key] != document.get(key) for key in ("bytes", "sha256"))
        ):
            raise CorpusError("Evidence document checksum does not match.")
        if document["sha256"] not in evidence_hashes:
            raise CorpusError("Document differs from pinned source evidence.")
    return manifest


def export_financial_dataset(
    directory: Path,
    output: Path,
    *,
    max_documents: int = 100,
    offset: int = 0,
    sources: tuple[CorpusSource, ...] = PINNED_SOURCES,
) -> dict[str, Any]:
    """Create a <=100-document evidence-only batch for the existing opt-in prepare command.

    No automatically generated gold queries: label selection/review is a separate quality task.
    """
    if not 1 <= max_documents <= 100 or offset < 0:
        raise CorpusError("Dataset batch must contain 1..100 documents and a nonnegative offset.")
    manifest = verify_financial_corpus(directory, sources=sources)
    selected = manifest["documents"][offset : offset + max_documents]
    if not selected:
        raise CorpusError("Dataset batch selection is empty.")
    _new_directory(output)
    for document in selected:
        _write_artifact(output, document["path"], (directory / document["path"]).read_bytes())
    for path in ("LICENSE", "ATTRIBUTION.txt"):
        _write_artifact(output, path, (directory / path).read_bytes())
    metadata = {
        "name": f"finqa-{REVISION[:8]}-batch-{offset}",
        "version": 1,
        "tenant": "financial-report-evaluation",
        "corpus_dir": "corpus/",
        "description": "Pinned FinQA excerpts; annotations excluded; no reviewed gold queries yet.",
    }
    _write_artifact(output, "dataset.yaml", (json.dumps(metadata, indent=2) + "\n").encode())
    _write_artifact(output, "queries.jsonl", b"")
    batch = {
        "revision": REVISION,
        "offset": offset,
        "document_count": len(selected),
        "documents": selected,
        "source_manifest_sha256": hashlib.sha256(
            (directory / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    _write_artifact(output, "batch.json", (json.dumps(batch, indent=2) + "\n").encode())
    return batch
