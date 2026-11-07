"""What deleting a project forever must cover, read from the schema so nothing can be forgotten."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint

import flint_graph.infrastructure.db.models  # noqa: F401
from flint_graph.application.services.narrative_project_purge import (
    RUNNING_WORK,
    project_loops,
    project_tables,
)
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    S3NarrativeArtifactStore,
)


def test_every_table_that_reaches_a_project_is_deleted():
    reaches = {"narrative_projects"}
    changed = True
    while changed:
        changed = False
        for table in Base.metadata.tables.values():
            if table.name not in reaches and any(
                key.column.table.name in reaches for key in table.foreign_keys
            ):
                reaches.add(table.name)
                changed = True
    assert {table.name for table in project_tables()} == reaches - {"narrative_projects"}


def test_children_are_deleted_before_what_they_point_to():
    order = [table.name for table in project_tables()]
    cleared = {(table.name, column) for table, column in project_loops()}
    for table in project_tables():
        for constraint in table.foreign_key_constraints:
            parent = constraint.referred_table.name
            if parent not in order or parent == table.name:
                continue
            if any((table.name, column) in cleared for column in constraint.column_keys):
                continue  # Emptied before anything is deleted, so the order does not matter.
            assert order.index(table.name) < order.index(parent), (table.name, parent)


def test_each_loop_between_tables_can_be_broken():
    loops = {(table.name, column) for table, column in project_loops()}
    assert {
        ("narrative_assets", "voice_job_id"),
        ("narrative_assets", "music_job_id"),
        ("narrative_assets", "folder_id"),
        ("narrative_image_jobs", "base_asset_id"),
    } <= loops
    assert "narrative_revisions" not in {name for name, _column in loops}, "they cannot be updated"
    # A table pointing at its own rows has to be cleared too, wherever one is added.
    for table in project_tables():
        if table.name != "narrative_revisions":
            for constraint in table.foreign_key_constraints:
                if constraint.referred_table is table:
                    assert any((table.name, name) in loops for name in constraint.column_keys)


def test_every_kind_of_job_that_can_be_running_is_checked():
    running = set()
    for table in project_tables():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and "'queued'" in str(constraint.sqltext):
                running.add(table.name)
    assert running == {name for name, _one, _many in RUNNING_WORK}


class Bucket:
    def __init__(self, keys, *, page=1000, errors=False, broken=False):
        self.keys, self.page, self.errors, self.broken = set(keys), page, errors, broken
        self.deleted_batches = []

    def list_objects_v2(self, *, Bucket, Prefix):
        if self.broken:
            raise RuntimeError(f"secret detail about {Prefix}")
        found = sorted(key for key in self.keys if key.startswith(Prefix))
        return {"Contents": [{"Key": key} for key in found[: self.page]]}

    def delete_objects(self, *, Bucket, Delete):
        keys = [item["Key"] for item in Delete["Objects"]]
        self.deleted_batches.append(keys)
        if self.errors:
            return {"Errors": [{"Key": keys[0], "Code": "AccessDenied"}]}
        self.keys -= set(keys)
        return {}


TENANT, PROJECT, RELEASE, OTHER = (UUID(int=number) for number in (1, 2, 3, 4))


def store(bucket):
    return S3NarrativeArtifactStore(bucket, bucket="studio")


@pytest.mark.anyio
async def test_only_this_projects_files_and_its_releases_are_removed():
    mine = f"tenants/{TENANT}/narrative/projects/{PROJECT}"
    keep = {
        f"tenants/{TENANT}/narrative/projects/{OTHER}/assets/a/image.png",
        f"tenants/{TENANT}/narrative/releases/{OTHER}/jobs/j/source.zip",
        f"tenants/{OTHER}/narrative/projects/{PROJECT}/assets/a/image.png",
        f"tenants/{TENANT}/documents/d/raw/source",
    }
    bucket = Bucket(
        {
            f"{mine}/assets/a/image.png",
            f"{mine}/assets/a/thumbnail.png",
            f"{mine}/voice-references/r/reference.wav",
            f"{mine}/style-adapters/s/executions/e/adapter.safetensors",
            f"tenants/{TENANT}/narrative/releases/{RELEASE}/jobs/j/executions/e/web.zip",
            *keep,
        }
    )
    await store(bucket).delete_project_files(
        tenant_id=TENANT, project_id=PROJECT, release_ids=[RELEASE]
    )
    assert bucket.keys == keep


@pytest.mark.anyio
async def test_a_project_with_more_files_than_one_page_is_emptied():
    keys = {
        f"tenants/{TENANT}/narrative/projects/{PROJECT}/assets/{number}" for number in range(25)
    }
    bucket = Bucket(keys, page=10)
    await store(bucket).delete_project_files(tenant_id=TENANT, project_id=PROJECT, release_ids=[])
    assert bucket.keys == set()
    assert [len(batch) for batch in bucket.deleted_batches] == [10, 10, 5]


@pytest.mark.anyio
async def test_deleting_again_after_everything_is_gone_is_fine():
    await store(Bucket(set())).delete_project_files(
        tenant_id=TENANT, project_id=PROJECT, release_ids=[RELEASE]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [{"errors": True}, {"broken": True}])
async def test_a_file_that_will_not_go_is_a_failure_without_private_detail(failure):
    bucket = Bucket({f"tenants/{TENANT}/narrative/projects/{PROJECT}/assets/a"}, **failure)
    with pytest.raises(ArtifactStoreError) as caught:
        await store(bucket).delete_project_files(
            tenant_id=TENANT, project_id=PROJECT, release_ids=[]
        )
    assert caught.value.code == "artifact_unavailable"
    assert "secret" not in str(caught.value)


@pytest.mark.anyio
async def test_only_real_ids_can_become_a_prefix():
    bucket = Bucket({"tenants/x"})
    with pytest.raises(ValueError):
        await store(bucket).delete_project_files(
            tenant_id=TENANT,
            project_id="../..",
            release_ids=[],  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        await store(bucket).delete_project_files(
            tenant_id="",
            project_id=uuid4(),
            release_ids=[],  # type: ignore[arg-type]
        )
    assert bucket.keys == {"tenants/x"}
