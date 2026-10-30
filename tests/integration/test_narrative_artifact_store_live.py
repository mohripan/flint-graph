"""Explicit owned MinIO qualification; never select the application's store."""

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config

from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    ObjectReceipt,
    S3NarrativeArtifactStore,
    release_artifact_key,
)


@pytest.fixture
def owned_store():
    path = os.environ.get("FLINT_GRAPH_NARRATIVE_STORE_FIXTURE")
    if not path:
        pytest.skip("Explicit owned disposable MinIO receipt required")
    metadata = json.loads(Path(path).read_bytes())
    info = json.loads(subprocess.check_output(["docker", "inspect", metadata["container_id"]]))[0]
    assert (
        info["Config"]["Labels"].get("io.flintgraph.narrative.store-fixture")
        == metadata["label_token"]
    )
    assert info["Image"] == metadata["image"]
    endpoint = urlsplit(metadata["endpoint_url"])
    assert endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1"
    assert not endpoint.username and not endpoint.password and not endpoint.path
    assert not endpoint.query and not endpoint.fragment
    published = info["NetworkSettings"]["Ports"]["9000/tcp"][0]
    assert published["HostIp"] == "127.0.0.1" and int(published["HostPort"]) == endpoint.port
    assert metadata["bucket"] == "narrative-" + metadata["label_token"]
    client = boto3.client(
        "s3",
        endpoint_url=metadata["endpoint_url"],
        aws_access_key_id=metadata["access_key"],
        aws_secret_access_key=metadata["secret_key"],
        region_name="us-east-1",
        config=Config(
            connect_timeout=1,
            read_timeout=3,
            retries={"max_attempts": 1},
            s3={"addressing_style": "path"},
            proxies={},
        ),
    )
    store = S3NarrativeArtifactStore(client, bucket=metadata["bucket"])
    keys = []

    def key(kind="source"):
        result = release_artifact_key(
            tenant_id=uuid4(),
            release_id=uuid4(),
            job_id=uuid4(),
            execution_token=uuid4(),
            kind=kind,
        )
        keys.append(result)
        return result

    try:
        yield store, client, metadata, key
    finally:
        current = json.loads(
            subprocess.check_output(["docker", "inspect", metadata["container_id"]])
        )[0]
        assert (
            current["Config"]["Labels"].get("io.flintgraph.narrative.store-fixture")
            == metadata["label_token"]
        )
        for known_key in keys:
            client.delete_object(Bucket=metadata["bucket"], Key=known_key)
        client.close()


@pytest.mark.anyio
async def test_real_conditional_put_replay_conflict_and_bounded_verified_read(owned_store):
    store, _, _, new_key = owned_store
    key, data = new_key(), b"original fixture" * 100000
    digest = hashlib.sha256(data).hexdigest()
    first = await store.put_once(key, data, expected_sha256=digest, content_type="application/zip")
    assert first == await store.put_once(
        key, data, expected_sha256=digest, content_type="application/zip"
    )
    with pytest.raises(ArtifactStoreError, match=r"^artifact_conflict$"):
        await store.put_once(
            key,
            b"different",
            expected_sha256=hashlib.sha256(b"different").hexdigest(),
            content_type="application/zip",
        )
    assert await store.get_verified(key, expected_size=len(data), expected_sha256=digest) == data


@pytest.mark.anyio
async def test_real_concurrent_different_uploads_have_one_winner(owned_store):
    store, _, _, new_key = owned_store
    key, payloads = new_key(), [b"alpha" * 1000, b"bravo" * 1000]
    results = await asyncio.gather(
        *(
            store.put_once(
                key,
                data,
                expected_sha256=hashlib.sha256(data).hexdigest(),
                content_type="application/zip",
            )
            for data in payloads
        ),
        return_exceptions=True,
    )
    receipts = [result for result in results if isinstance(result, ObjectReceipt)]
    assert len(receipts) == 1
    assert (
        sum(
            isinstance(result, ArtifactStoreError) and result.code == "artifact_conflict"
            for result in results
        )
        == 1
    )
    winner = receipts[0]
    actual = await store.get_verified(
        key, expected_size=winner.size_bytes, expected_sha256=winner.sha256
    )
    assert actual in payloads


@pytest.mark.anyio
async def test_real_same_size_tampering_is_rejected(owned_store):
    store, client, metadata, new_key = owned_store
    key, data = new_key(), b"original"
    digest = hashlib.sha256(data).hexdigest()
    await store.put_once(key, data, expected_sha256=digest, content_type="application/zip")
    # Deliberate corruption only in this labeled fixture's unique test key.
    await asyncio.to_thread(client.put_object, Bucket=metadata["bucket"], Key=key, Body=b"modified")
    with pytest.raises(ArtifactStoreError, match=r"^artifact_integrity$"):
        await store.get_verified(key, expected_size=len(data), expected_sha256=digest)


@pytest.mark.anyio
async def test_actual_engine_artifact_bytes_roundtrip_through_owned_store(owned_store):
    folder = os.environ.get("FLINT_GRAPH_NARRATIVE_ARTIFACT_SOURCE_DIR")
    if not folder:
        pytest.skip("Explicit actual runner proof ZIP directory required")
    store, _, metadata, new_key = owned_store
    hashes = {}
    for kind in ("source", "web"):
        payload = (Path(folder) / (kind + ".zip")).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        key = new_key(kind)
        await store.put_once(key, payload, expected_sha256=digest, content_type="application/zip")
        assert (
            await store.get_verified(key, expected_size=len(payload), expected_sha256=digest)
            == payload
        )
        hashes[kind] = {"sha256": digest, "bytes": len(payload)}
    evidence = os.environ.get("FLINT_GRAPH_NARRATIVE_STORE_EVIDENCE_DIR")
    if evidence:
        output = Path(evidence)
        await asyncio.to_thread(output.mkdir)
        receipt = {
            "image": metadata["image"],
            "version": metadata["version"],
            "scope": "private store roundtrip only; no database publication",
            "actual_engine_artifacts": hashes,
        }
        (output / "qualification.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
