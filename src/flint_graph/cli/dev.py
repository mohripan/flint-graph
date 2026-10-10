"""Explicit, guarded developer profiles over public workspace APIs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flint_graph.cli.doctor import (
    ActiveIndex,
    EmbeddingConfig,
    HealthReport,
    ModelReport,
    Name,
    QueryConfig,
    SystemReport,
)
from flint_graph.evaluation.datasets import load_dataset
from flint_graph.evaluation.prepare import load_corpus, prepare_corpus

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class InstalledModel(ModelReport):
    digest: Digest | None = None


class ModelPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["embedding", "answer", "support"]
    provider: Literal["ollama"]
    model: Name
    digest: Digest


class ModelLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    profile: Literal["local-real"] = "local-real"
    embedding: EmbeddingConfig
    query: QueryConfig
    models: list[ModelPin] = Field(min_length=3, max_length=3)


class ProfileError(Exception):
    """An actionable fixed diagnostic, never a provider response or token."""


async def inspect_profile(
    client: httpx.AsyncClient,
    profile: str,
    *,
    expected_lock: ModelLock | None = None,
    record_lock: bool = False,
) -> tuple[SystemReport, ModelLock | None, bool]:
    health = await client.get("/health/ready")
    health.raise_for_status()
    if HealthReport.model_validate(health.json()).status != "ready":
        raise ProfileError("Resolve API readiness failures before bootstrap.")
    response = await client.get("/v1/system-readiness")
    response.raise_for_status()
    system = SystemReport.model_validate(response.json())
    capabilities = response.json().get("setup_capabilities")
    capability = (
        isinstance(capabilities, dict) and capabilities.get("preserve_active_bootstrap") is True
    )
    response = await client.get("/v1/model-readiness")
    response.raise_for_status()
    models = [InstalledModel.model_validate(item) for item in response.json()]
    if sorted(item.role for item in models) != ["answer", "embedding", "support"]:
        raise ProfileError("API model report is incomplete; upgrade the API and retry.")
    expected = {
        "embedding": (system.embedding.provider, system.embedding.model),
        "answer": (system.query.answer_provider, system.query.answer_model),
        "support": (system.query.support_provider, system.query.support_model),
    }
    if any((item.provider, item.model) != expected[item.role] for item in models):
        raise ProfileError(
            "Configuration changed between model checks; retry after deployment settles."
        )
    lock = None
    if profile == "local-real":
        if any(
            item.provider != "ollama"
            or item.status != "available"
            or item.digest is None
            or ":" not in item.model.rsplit("/", 1)[-1]
            for item in models
        ):
            raise ProfileError(
                "Local-real needs installed, explicitly tagged Ollama models with SHA-256 digests."
            )
        lock = ModelLock(
            embedding=system.embedding,
            query=system.query,
            models=[
                ModelPin(role=item.role, provider="ollama", model=item.model, digest=item.digest)
                for item in models
                if item.digest is not None
            ],
        )
        if not record_lock and expected_lock is None:
            raise ProfileError(
                "Local-real requires --model-lock; record and review installed models first."
            )
        if expected_lock is not None and lock != expected_lock:
            raise ProfileError(
                "Model digest/configuration differs from the reviewed lock; no setup changed."
            )
    elif (
        (system.embedding.provider, system.embedding.model, system.embedding.dimensions)
        != (
            "deterministic",
            "deterministic-test",
            384,
        )
        or system.query.answer_provider != "deterministic"
        or (system.query.support_provider != "deterministic")
        or any(item.provider != "deterministic" or item.status != "offline" for item in models)
    ):
        raise ProfileError("API configuration does not match offline; select its Compose overlay.")
    index = system.search_readiness.active_index_version
    if index is not None and (
        index.embedding_provider,
        index.embedding_model,
        index.vector_dimension,
    ) != (system.embedding.provider, system.embedding.model, system.embedding.dimensions):
        raise ProfileError("Active index is incompatible; no index was changed. Inspect Setup.")
    return system, lock, capability


def main(
    argv: Sequence[str] | None = None, *, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "bootstrap", "lock"])
    parser.add_argument("--profile", choices=["offline", "local-real"], required=True)
    parser.add_argument("--workspace-id", required=True, type=UUID)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token-env", default="FLINT_GRAPH_API_TOKEN")
    parser.add_argument("--model-lock", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--smoke-corpus", action="store_true")
    parser.add_argument("--dataset", type=Path, default=Path("evals/datasets/acme-smoke"))
    parser.add_argument("--prepare-timeout", type=float, default=600)
    args = parser.parse_args(argv)
    try:
        dataset = None
        sources = []
        if args.smoke_corpus:
            if args.command != "bootstrap" or args.output is None:
                raise ProfileError("--smoke-corpus requires bootstrap and a new --output manifest.")
            if not 0 < args.prepare_timeout <= 1800:
                raise ProfileError("Preparation timeout must be >0 and <=1800 seconds.")
            dataset = load_dataset(args.dataset)
            sources = load_corpus(args.dataset, dataset)
            if len(sources) > 10 or sum(len(source.content) for source in sources) > 1024 * 1024:
                raise ProfileError("Tiny smoke corpus is limited to ten files and 1 MiB total.")
        if args.output is not None and args.command != "lock" and not args.smoke_corpus:
            raise ProfileError("--output is used only for a model lock or opt-in smoke manifest.")
        if args.command == "lock" and (args.profile != "local-real" or args.output is None):
            raise ProfileError("lock requires --profile local-real and a new --output file.")
        if args.output is not None and (args.output.exists() or args.output.is_symlink()):
            raise ProfileError("Output already exists; choose a new file. Nothing was overwritten.")
        expected_lock = None
        if args.model_lock is not None:
            if args.profile != "local-real":
                raise ProfileError("--model-lock applies only to local-real.")
            with args.model_lock.open("r", encoding="utf-8") as lock_file:
                content = lock_file.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ProfileError("Model lock exceeds the size limit.")
            expected_lock = ModelLock.model_validate_json(content)
        url = httpx.URL(args.base_url)
        if (
            url.scheme not in {"https", "http"}
            or not url.host
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (url.scheme == "http" and url.host not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ProfileError("Use credential-free HTTPS or loopback HTTP; no query/fragment.")
        token = os.getenv(args.token_env, "")
        if len(token) > 8192 or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise ProfileError("Token must come from a valid --token-env environment variable.")
        headers = {"X-Tenant-ID": str(args.workspace_id)}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async def execute() -> None:
            async with httpx.AsyncClient(
                base_url=str(url),
                headers=headers,
                timeout=20,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                async with asyncio.timeout(args.prepare_timeout + 60 if args.smoke_corpus else 60):
                    system, lock, guarded_bootstrap = await inspect_profile(
                        client,
                        args.profile,
                        expected_lock=expected_lock,
                        record_lock=args.command == "lock",
                    )
                    if args.command == "lock":
                        if lock is None:
                            raise ProfileError("No local-real model fingerprints available.")
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        with args.output.open("x", encoding="utf-8") as output_file:
                            output_file.write(lock.model_dump_json(indent=2) + "\n")
                        print("Recorded installed model fingerprints; review before bootstrap.")
                    if args.command == "bootstrap":
                        workspaces = await client.get("/v1/workspaces")
                        workspaces.raise_for_status()
                        role = next(
                            (
                                row["role"]
                                for row in workspaces.json()
                                if row["id"] == str(args.workspace_id)
                            ),
                            None,
                        )
                        if role not in {"admin", "owner"}:
                            raise ProfileError(
                                "Bootstrap requires workspace admin or owner access."
                            )
                        index = system.search_readiness.active_index_version
                        if index is None:
                            if not guarded_bootstrap:
                                raise ProfileError("Upgrade the API for guarded index bootstrap.")
                            created = await client.post(
                                "/v1/retrieval-index/bootstrap", params={"preserve_active": "true"}
                            )
                            created.raise_for_status()
                            index = ActiveIndex.model_validate(created.json())
                            if (
                                index.embedding_provider,
                                index.embedding_model,
                                index.vector_dimension,
                            ) != (
                                system.embedding.provider,
                                system.embedding.model,
                                system.embedding.dimensions,
                            ):
                                raise ProfileError(
                                    "Embeddings changed; inspect Setup before retrying."
                                )
                        if args.smoke_corpus and dataset is not None:
                            manifest = await prepare_corpus(
                                client,
                                dataset,
                                sources,
                                workspace_id=args.workspace_id,
                                index_version_id=index.id,
                                timeout_seconds=args.prepare_timeout,
                            )
                            manifest.preparation["developer_profile"] = args.profile
                            manifest.preparation["model_lock"] = lock.model_dump() if lock else None
                            manifest.preparation["system_readiness"] = system.model_dump(
                                mode="json", exclude={"search_readiness"}
                            )
                            args.output.parent.mkdir(parents=True, exist_ok=True)
                            with args.output.open("x", encoding="utf-8") as manifest_file:
                                manifest_file.write(manifest.model_dump_json(indent=2) + "\n")
                            print(f"Prepared {len(sources)} smoke documents in this workspace.")
                        else:
                            print(f"Ready index {index.id}; no documents uploaded.")
            print(f"Profile {args.profile} verified; no query inference or model downloads.")
            print(json.dumps(system.model_dump(mode="json", exclude={"search_readiness"})))

        asyncio.run(execute())
        return 0
    except ProfileError as exc:
        print(f"Profile check failed: {exc}")
        return 1
    except (ValidationError, ValueError, TypeError, OSError, httpx.InvalidURL):
        print("Profile check failed: invalid arguments or diagnostic schema; verify API version.")
        return 1
    except (httpx.HTTPError, TimeoutError):
        print("Profile check failed: API/auth/timeout error; verify URL, token, role and logs.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
