"""Pin generic manifests in the admission transaction and verify them on replay."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.infrastructure.db.prompt_models import PromptBundleRecord, PromptBundleReference
from flint_graph.prompts.catalog import PromptError, canonical
from flint_graph.prompts.source import PromptBundle, current_snapshot


async def pin_bundle(session: AsyncSession, bundle: PromptBundle | None = None) -> str:
    bundle = bundle or current_snapshot()
    if await session.get(PromptBundleRecord, bundle.sha256) is None:
        try:
            async with session.begin_nested():
                session.add(PromptBundleRecord(sha256=bundle.sha256, manifest=bundle.data))
                await session.flush()
        except IntegrityError:
            if await session.get(PromptBundleRecord, bundle.sha256) is None:
                raise
    return bundle.sha256


async def load_bundle(session: AsyncSession, sha: str) -> PromptBundle:
    row = await session.get(PromptBundleRecord, sha)
    if row is None:
        raise PromptError("historical_bundle_unavailable")
    bundle = PromptBundle.from_bytes(canonical(row.manifest))
    if bundle.sha256 != sha:
        raise PromptError("bundle_hash_mismatch")
    return bundle


async def execution_bundle(session: AsyncSession, row: PromptBundleReference) -> PromptBundle:
    # Old queued work gets its first execution identity; completed historic rows stay unknown.
    if row.prompt_bundle_sha256 is None:
        status = getattr(row, "status", None)
        if getattr(status, "value", status) not in {"queued", "running"}:
            raise PromptError("historical_bundle_unavailable")
        row.prompt_bundle_sha256 = await pin_bundle(session)
        await session.flush()
    return await load_bundle(session, row.prompt_bundle_sha256)
