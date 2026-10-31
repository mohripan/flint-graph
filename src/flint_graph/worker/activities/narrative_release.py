"""Trusted activity edge: source/ZIPs remain local, history receives only IDs/status."""

import asyncio
import hashlib
from typing import TypedDict
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from flint_graph.application.narrative_workflow import (
    BUILD_ACTIVITY_ID,
    BUILD_NARRATIVE_RELEASE_ACTIVITY,
    FINALIZE_ACTIVITY_ID,
    FINALIZE_NARRATIVE_RELEASE_ACTIVITY,
    NARRATIVE_RELEASE_WORKFLOW,
    ReleasePayload,
    ReleaseResult,
    SupervisionPayload,
    release_workflow_id,
    validate_release_payload,
    validate_release_result,
)
from flint_graph.application.services.narrative_release_execution import (
    FAILURE_CODES,
    ReleaseInput,
    ReleaseInputError,
    claim_release_execution,
    finalize_release_workflow,
    finish_release_failure,
    load_release_input,
    lock_release_execution,
    workflow_cleanup_plan,
)
from flint_graph.application.services.narrative_release_publication import (
    KINDS,
    Kind,
    make_release_manifest,
    publish_release_artifacts,
)
from flint_graph.application.services.narrative_releases import BuildIdentity
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    S3NarrativeArtifactStore,
    release_artifact_key,
)
from flint_graph.infrastructure.narrative_builder import BuildError, DockerNarrativeBuilder
from flint_graph.narrative.package import attach_assets
from flint_graph.narrative.values import PackageError, StoryPackage


class ReleaseScope(TypedDict):
    tenant_id: UUID
    release_id: UUID
    job_id: UUID


async def _drain[T](task: asyncio.Task[T]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            pass
        except Exception:
            break
    try:
        task.result()
    except (Exception, asyncio.CancelledError):
        pass


class NarrativeReleaseActivities:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession],
        builder: DockerNarrativeBuilder,
        store: S3NarrativeArtifactStore,
        namespace: str,
        task_queue: str,
    ) -> None:
        self.factory, self.builder, self.store = factory, builder, store
        self.namespace, self.queue = namespace, task_queue
        self.identity = BuildIdentity(builder.image, builder.toolchain)

    def _context(self, payload: object, *, finalizer: bool = False) -> tuple[ReleasePayload, UUID]:
        try:
            data = validate_release_payload(payload)
            info = activity.info()
            expected_id = FINALIZE_ACTIVITY_ID if finalizer else BUILD_ACTIVITY_ID
            expected_type = (
                FINALIZE_NARRATIVE_RELEASE_ACTIVITY
                if finalizer
                else BUILD_NARRATIVE_RELEASE_ACTIVITY
            )
            run_id = UUID(info.workflow_run_id or "")
            if (
                info.workflow_id != release_workflow_id(data)
                or info.workflow_type != NARRATIVE_RELEASE_WORKFLOW
                or info.namespace != self.namespace
                or info.task_queue != self.queue
                or info.activity_id != expected_id
                or info.activity_type != expected_type
                or info.is_local
                or type(info.attempt) is not int
                or info.attempt < 1
                or str(run_id) != info.workflow_run_id
            ):
                raise ValueError
            return data, run_id
        except Exception:
            raise ApplicationError("activity_identity", non_retryable=True) from None

    @staticmethod
    def _scope(data: ReleasePayload) -> ReleaseScope:
        return ReleaseScope(
            tenant_id=UUID(data["tenant_id"]),
            release_id=UUID(data["release_id"]),
            job_id=UUID(data["job_id"]),
        )

    @staticmethod
    def _result(data: ReleasePayload, status: str) -> ReleaseResult:
        return validate_release_result(
            {"job_id": data["job_id"], "status": status}, job_id=data["job_id"]
        )

    async def _status(self, data: ReleasePayload) -> ReleaseResult:
        async with self.factory() as session:
            _, job, _ = await lock_release_execution(session, **self._scope(data))
            status = job.status if job.status in ("completed", "failed", "cancelled") else "stale"
            return self._result(data, status)

    async def _check(self, data: ReleasePayload, token: UUID) -> None:
        activity.heartbeat({"job_id": data["job_id"]})
        async with self.factory() as session:
            _, job, active = await lock_release_execution(session, **self._scope(data))
            if active != job.id or job.status != "running" or job.execution_token != token:
                raise ReleaseInputError("execution_stale")
            if job.cancel_requested:
                raise ReleaseInputError("execution_cancelled")

    async def _finish(
        self, data: ReleasePayload, token: UUID, *, code: str | None = None, cancelled: bool = False
    ) -> ReleaseResult:
        async with self.factory() as session:
            await finish_release_failure(
                session, **self._scope(data), token=token, error_code=code, cancelled=cancelled
            )
            await session.commit()
        return await self._status(data)

    async def _attached(self, loaded: ReleaseInput) -> StoryPackage:
        """Fetch each bound asset's verified bytes; the checks run again on attach."""
        fetched: dict[str, bytes] = {}
        data: dict[str, bytes] = {}
        for source in loaded.assets:
            if source.object_key not in fetched:
                fetched[source.object_key] = await self.store.get_verified(
                    source.object_key,
                    expected_size=source.size,
                    expected_sha256=source.sha256,
                    max_bytes=source.max_bytes,
                )
            data[source.id] = fetched[source.object_key]
        if not data:
            return loaded.package
        try:
            return await asyncio.to_thread(attach_assets, loaded.package, data)
        except PackageError:
            raise ReleaseInputError("input_integrity") from None

    async def _execute(
        self, data: ReleasePayload, run_id: UUID, token: UUID, ready: asyncio.Event
    ) -> ReleaseResult:
        scope = self._scope(data)
        async with self.factory() as session:
            claim = await claim_release_execution(
                session,
                **scope,
                token=token,
                workflow_run_id=run_id,
                activity_attempt=activity.info().attempt,
            )
            await session.commit()
        if not claim.acquired:
            return await self._status(data)
        ready.set()
        await self._check(data, token)
        async with self.factory() as session:
            loaded = await load_release_input(session, **scope, token=token, build=self.identity)
            await session.commit()
        package = await self._attached(loaded)
        built = await self.builder.build(
            package, execution_id=token, check=lambda: self._check(data, token)
        )
        if built.package_hash != package.content_hash:
            raise ReleaseInputError("package_integrity")
        receipts = {}
        artifacts: tuple[tuple[Kind, bytes], ...] = (
            ("source", built.source_zip),
            ("web", built.web_zip),
        )
        for kind, content in artifacts:
            await self._check(data, token)
            receipts[kind] = await self.store.put_once(
                release_artifact_key(**scope, execution_token=token, kind=kind),
                content,
                expected_sha256=hashlib.sha256(content).hexdigest(),
                content_type="application/zip",
            )
        await self._check(data, token)
        async with self.factory() as session:
            release, _, _ = await lock_release_execution(session, **scope)
            manifest = make_release_manifest(
                release, job_id=scope["job_id"], source=receipts["source"], web=receipts["web"]
            )
            await session.commit()
        receipts["manifest"] = await self.store.put_once(
            release_artifact_key(**scope, execution_token=token, kind="manifest"),
            manifest,
            expected_sha256=hashlib.sha256(manifest).hexdigest(),
            content_type="application/json",
            max_bytes=1048576,
        )
        await self._check(data, token)
        async with self.factory() as session:
            result = await publish_release_artifacts(
                session,
                **scope,
                token=token,
                receipts={kind: receipts[kind] for kind in KINDS},
                manifest_json=manifest,
            )
            await session.commit()
        return self._result(data, result.status)

    async def _monitored(self, data: ReleasePayload, run_id: UUID, token: UUID) -> ReleaseResult:
        ready = asyncio.Event()

        async def monitor() -> None:
            await ready.wait()
            while True:
                await asyncio.sleep(1)
                await self._check(data, token)

        work = asyncio.create_task(self._execute(data, run_id, token, ready))
        guard = asyncio.create_task(monitor())
        try:
            done, _ = await asyncio.wait({work, guard}, return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                return await work
            guard.result()
            raise ReleaseInputError("execution_stale")
        finally:
            for task in (work, guard):
                if not task.done():
                    task.cancel()
            await _drain(work)
            await _drain(guard)

    async def _build(self, data: ReleasePayload, run_id: UUID) -> ReleaseResult:
        token = uuid4()
        try:
            return await self._monitored(data, run_id, token)
        except ReleaseInputError as exc:
            if exc.code == "execution_registration_pending":
                raise ApplicationError(exc.code, type=exc.code) from None
            if exc.code == "execution_stale":
                return await self._status(data)
            if exc.code == "execution_cancelled":
                return await self._finish(data, token, cancelled=True)
            code = exc.code if exc.code in FAILURE_CODES else "input_integrity"
            return await self._finish(data, token, code=code)
        except BuildError as exc:
            if exc.code == "build_io":
                raise ApplicationError("build_io", type="build_io") from None
            code = exc.code if exc.code in FAILURE_CODES else "engine_failed"
            return await self._finish(data, token, code=code)
        except ArtifactStoreError as exc:
            if exc.code == "artifact_unavailable":
                raise ApplicationError("artifact_storage", type="artifact_storage") from None
            return await self._finish(data, token, code="artifact_invalid")
        except asyncio.CancelledError:
            cancellation = activity.cancellation_details()
            if cancellation is not None and cancellation.cancel_requested:
                cleanup = asyncio.create_task(self._finish(data, token, cancelled=True))
                await _drain(cleanup)
            raise

    @activity.defn(name=BUILD_NARRATIVE_RELEASE_ACTIVITY)
    async def build(self, payload: ReleasePayload) -> ReleaseResult:
        data, run_id = self._context(payload)
        try:
            return await self._build(data, run_id)
        except (ApplicationError, asyncio.CancelledError):
            raise
        except Exception:
            raise ApplicationError("worker_interrupted", type="worker_interrupted") from None

    @activity.defn(name=FINALIZE_NARRATIVE_RELEASE_ACTIVITY)
    async def finalize(self, payload: SupervisionPayload) -> ReleaseResult:
        try:
            if (
                not isinstance(payload, dict)
                or set(payload)
                != {"schema_version", "tenant_id", "release_id", "job_id", "cancelled"}
                or type(payload["cancelled"]) is not bool
            ):
                raise ApplicationError("activity_identity", non_retryable=True)
            base = {key: value for key, value in payload.items() if key != "cancelled"}
            data, run_id = self._context(base, finalizer=True)
            scope = self._scope(data)
            async with self.factory() as session:
                plan = await workflow_cleanup_plan(session, **scope, workflow_run_id=run_id)
                await session.commit()
            if plan is not None:
                if plan.execution_token is not None:
                    await self.builder.cleanup_execution(plan.execution_token)
                async with self.factory() as session:
                    await finalize_release_workflow(
                        session,
                        **scope,
                        workflow_run_id=run_id,
                        expected_token=plan.execution_token,
                        expected_attempt=plan.activity_attempt,
                        cancelled=bool(payload["cancelled"]),
                    )
                    await session.commit()
            return await self._status(data)
        except (ApplicationError, asyncio.CancelledError):
            raise
        except Exception:
            raise ApplicationError("worker_interrupted", type="worker_interrupted") from None
