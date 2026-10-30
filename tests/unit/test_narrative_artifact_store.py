import hashlib
import io
import tracemalloc

import pytest

from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    S3NarrativeArtifactStore,
)

ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


class PreconditionFailed(Exception):
    def __init__(self):
        self.response = {"ResponseMetadata": {"HTTPStatusCode": 412}}


class Body(io.BytesIO):
    def read(self, size=-1):
        assert 0 < size <= 65536, "Object reads must have a bounded request size"
        return super().read(size)


class S3Fixture:
    def __init__(self):
        self.objects = {}
        self.body = None

    def put_object(self, *, Bucket, Key, Body, ContentType, IfNoneMatch, Metadata):
        assert Bucket == "owned-fixture" and IfNoneMatch == "*"
        if Key in self.objects:
            raise PreconditionFailed
        self.objects[Key] = Body

    def head_object(self, *, Bucket, Key):
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, *, Bucket, Key):
        self.body = Body(self.objects[Key])
        return {"Body": self.body}


@pytest.mark.anyio
async def test_immutable_artifact_upload_replay_and_verified_read_close_the_body():
    client = S3Fixture()
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    key = "tenants/fixture/releases/original/source.zip"
    first = await store.put_once(
        key, b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
    )
    replay = await store.put_once(
        key, b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
    )
    assert first == replay
    assert first.key == key and first.size_bytes == 3 and first.sha256 == ABC_SHA256
    assert await store.get_verified(key, expected_size=3, expected_sha256=ABC_SHA256) == b"abc"
    assert client.body.closed


@pytest.mark.anyio
async def test_conflicting_bytes_never_overwrite_a_private_artifact_key():
    client = S3Fixture()
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    await store.put_once(
        "private/key", b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
    )
    with pytest.raises(ArtifactStoreError, match=r"^artifact_conflict$"):
        await store.put_once(
            "private/key",
            b"different",
            expected_sha256=hashlib.sha256(b"different").hexdigest(),
            content_type="application/zip",
        )
    assert client.objects["private/key"] == b"abc"
    assert client.body.closed


@pytest.mark.anyio
@pytest.mark.parametrize("data", [b"ab", b"abcd", b"xyz"])
async def test_head_size_and_object_metadata_cannot_authorize_wrong_actual_bytes(data):
    class MisreportedClient(S3Fixture):
        def get_object(self, **_):
            self.body = Body(data)
            return {"Body": self.body, "Metadata": {"sha256": ABC_SHA256}}

    client = MisreportedClient()
    client.objects["key"] = b"abc"
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    with pytest.raises(ArtifactStoreError, match=r"^artifact_integrity$"):
        await store.get_verified("key", expected_size=3, expected_sha256=ABC_SHA256)
    assert client.body.closed


@pytest.mark.anyio
async def test_large_or_incorrect_head_rejects_before_opening_a_body():
    class OversizeHead(S3Fixture):
        def head_object(self, **_):
            return {"ContentLength": 67108865}

    client = OversizeHead()
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    with pytest.raises(ArtifactStoreError, match=r"^artifact_integrity$"):
        await store.get_verified("key", expected_size=3, expected_sha256=ABC_SHA256)
    assert client.body is None


@pytest.mark.anyio
async def test_read_failures_close_the_body_and_suppress_private_sdk_error_details():
    class BrokenBody(Body):
        def read(self, size=-1):
            raise OSError("PRIVATE_STORE_CREDENTIAL")

    class BrokenClient(S3Fixture):
        def get_object(self, **_):
            self.body = BrokenBody(b"abc")
            return {"Body": self.body}

    client = BrokenClient()
    client.objects["key"] = b"abc"
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    with pytest.raises(ArtifactStoreError, match=r"^artifact_unavailable$") as caught:
        await store.get_verified("key", expected_size=3, expected_sha256=ABC_SHA256)
    assert client.body.closed and caught.value.__suppress_context__


@pytest.mark.anyio
async def test_malformed_sdk_error_metadata_cannot_escape_with_private_context():
    class PrivateSDKError(Exception):
        response = None

    class BrokenPut(S3Fixture):
        def put_object(self, **_):
            raise PrivateSDKError("PRIVATE_STORE_CREDENTIAL")

    store = S3NarrativeArtifactStore(BrokenPut(), bucket="owned-fixture")
    with pytest.raises(ArtifactStoreError, match=r"^artifact_unavailable$") as caught:
        await store.put_once(
            "key", b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
        )
    assert caught.value.__suppress_context__


@pytest.mark.anyio
async def test_short_read_stream_does_not_amplify_retained_memory():
    data = b"a" * 262144

    class ShortBody(Body):
        def read(self, size=-1):
            return super().read(min(size, 1))

    class ShortClient(S3Fixture):
        def get_object(self, **_):
            self.body = ShortBody(data)
            return {"Body": self.body}

    client = ShortClient()
    client.objects["key"] = data
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    tracemalloc.start()
    try:
        result = await store.get_verified(
            "key", expected_size=len(data), expected_sha256=hashlib.sha256(data).hexdigest()
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result == data and client.body.closed
    assert peak < 4194304


@pytest.mark.anyio
async def test_lost_upload_acknowledgement_replays_verified_existing_bytes():
    class LostAck(S3Fixture):
        lost = False

        def put_object(self, **kwargs):
            super().put_object(**kwargs)
            if not self.lost:
                self.lost = True
                raise TimeoutError("PRIVATE_SDK_DETAILS")

    client = LostAck()
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    with pytest.raises(ArtifactStoreError, match=r"^artifact_unavailable$"):
        await store.put_once(
            "key", b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
        )
    receipt = await store.put_once(
        "key", b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
    )
    assert receipt.sha256 == ABC_SHA256 and client.objects["key"] == b"abc"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "existing,code",
    [(b"abc", None), (b"xyz", "artifact_integrity"), (None, "artifact_unavailable")],
)
async def test_conditional_409_accepts_only_independently_verified_existing_bytes(existing, code):
    class RaceError(Exception):
        def __init__(self):
            self.response = {"ResponseMetadata": {"HTTPStatusCode": 409}}

    class RaceClient(S3Fixture):
        def put_object(self, **_):
            raise RaceError

    client = RaceClient()
    if existing is not None:
        client.objects["key"] = existing
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    if code:
        with pytest.raises(ArtifactStoreError) as caught:
            await store.put_once(
                "key", b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
            )
        assert caught.value.code == code
    else:
        assert (
            await store.put_once(
                "key", b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
            )
        ).size_bytes == 3
    assert client.objects.get("key") == existing


@pytest.mark.anyio
async def test_same_length_412_conflict_is_checked_by_hash():
    client = S3Fixture()
    client.objects["key"] = b"xyz"
    store = S3NarrativeArtifactStore(client, bucket="owned-fixture")
    with pytest.raises(ArtifactStoreError, match=r"^artifact_conflict$"):
        await store.put_once(
            "key", b"abc", expected_sha256=ABC_SHA256, content_type="application/zip"
        )
    assert client.objects["key"] == b"xyz"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "size,cap,digest",
    [
        (0, 64, ABC_SHA256),
        (True, 64, ABC_SHA256),
        (65, 64, ABC_SHA256),
        (3, 67108865, ABC_SHA256),
        (3, 64, "invalid"),
    ],
)
async def test_invalid_expectations_are_rejected_before_contacting_the_sdk(size, cap, digest):
    class ForbiddenSDK:
        def __getattr__(self, _):
            raise AssertionError("SDK must not be contacted")

    store = S3NarrativeArtifactStore(ForbiddenSDK(), bucket="owned-fixture")
    with pytest.raises(ValueError, match=r"^Invalid artifact expectation$"):
        await store.get_verified("key", expected_size=size, expected_sha256=digest, max_bytes=cap)
