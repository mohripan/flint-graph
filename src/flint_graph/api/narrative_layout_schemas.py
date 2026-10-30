"""Nested, bounded scene hierarchy: routes, chapters and folders containing scene references."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"^[a-z][a-z0-9_-]{0,63}$"
MAX_DEPTH = 4
MAX_GROUPS = 500
MAX_ITEMS = 20000


class LayoutScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["scene"]
    id: str = Field(pattern=_ID)


class LayoutGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["group"]
    id: str = Field(pattern=_ID)
    name: str = Field(min_length=1, max_length=80)
    collapsed: bool = False
    items: list["LayoutItem"] = Field(default_factory=list, max_length=MAX_ITEMS)


LayoutItem = Annotated[LayoutScene | LayoutGroup, Field(discriminator="type")]


def _check_shape(items: Any) -> None:
    # Iterative walk before recursive model validation: depth, size and uniqueness.
    if not isinstance(items, list):
        return
    stack: list[tuple[Any, int]] = [(item, 1) for item in items]
    groups = total = 0
    scenes: set[str] = set()
    group_ids: set[str] = set()
    while stack:
        item, depth = stack.pop()
        total += 1
        if total > MAX_ITEMS:
            raise ValueError("The layout is too large.")
        if not isinstance(item, dict):
            continue
        if item.get("type") == "group":
            groups += 1
            if depth > MAX_DEPTH or groups > MAX_GROUPS:
                raise ValueError("Folders are nested too deeply or are too many.")
            group_id = item.get("id")
            if isinstance(group_id, str):
                if group_id in group_ids:
                    raise ValueError("Each folder needs a unique id.")
                group_ids.add(group_id)
            children = item.get("items", [])
            if isinstance(children, list):
                stack.extend((child, depth + 1) for child in children)
        elif item.get("type") == "scene":
            scene_id = item.get("id")
            if isinstance(scene_id, str):
                if scene_id in scenes:
                    raise ValueError("A scene can appear only once in the layout.")
                scenes.add(scene_id)


class LayoutWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int = Field(ge=0, le=2**31 - 1)
    items: list[LayoutItem] = Field(max_length=MAX_ITEMS)

    @model_validator(mode="before")
    @classmethod
    def _bounded(cls, value: Any) -> Any:
        if isinstance(value, dict):
            _check_shape(value.get("items"))
        return value


class LayoutResponse(BaseModel):
    project_id: UUID
    version: int
    items: list[LayoutItem]
