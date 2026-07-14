"""Golden dataset schema and loader for the evaluation platform.

A dataset is a directory containing ``dataset.yaml`` (metadata) and ``queries.jsonl``
(one labeled query per line). See docs/architecture/evaluation-contract.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

QueryType = Literal["factoid", "multi_hop", "entity", "abstain_expected"]


class GoldenQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=1000)
    query_type: QueryType
    expected_answer: str | None = Field(default=None, max_length=4000)
    expect_abstain: bool = False
    relevant_chunk_ids: list[str] = Field(default_factory=list, max_length=500)
    relevant_entity_ids: list[str] = Field(default_factory=list, max_length=500)
    must_cite_sources: list[str] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _validate_consistency(self) -> Self:
        expect_abstain = self.expect_abstain or self.query_type == "abstain_expected"
        if expect_abstain and self.expected_answer is not None:
            raise ValueError("abstain-expected queries must not set expected_answer")
        if self.query_type == "abstain_expected" and not self.expect_abstain:
            object.__setattr__(self, "expect_abstain", True)
        return self


class DatasetMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    tenant: str = Field(min_length=1, max_length=200)
    corpus_dir: str = Field(default="corpus/", max_length=500)
    description: str = Field(default="", max_length=2000)


class GoldenDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: DatasetMetadata
    queries: list[GoldenQuery] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> Self:
        seen: set[str] = set()
        for query in self.queries:
            if query.id in seen:
                raise ValueError(f"duplicate query id '{query.id}'")
            seen.add(query.id)
        return self


def load_dataset(directory: Path) -> GoldenDataset:
    metadata = load_metadata(directory / "dataset.yaml")
    queries = load_queries(directory / "queries.jsonl")
    return GoldenDataset(metadata=metadata, queries=queries)


def load_metadata(path: Path) -> DatasetMetadata:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DatasetMetadata.model_validate(raw)


def load_queries(path: Path) -> list[GoldenQuery]:
    queries: list[GoldenQuery] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        queries.append(GoldenQuery.model_validate_json(stripped))
    return queries
