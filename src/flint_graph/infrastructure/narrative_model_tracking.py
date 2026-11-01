"""Optional numeric-only MLflow mirror. Never controls training or publication."""

import math
import time
from typing import Any
from uuid import UUID

import httpx


class ModelTracker:
    def __init__(self, url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self.url, self.client = url.rstrip("/"), client

    async def record(
        self,
        *,
        job_id: UUID,
        base_hash: str,
        dataset_hash: str,
        recipe_hash: str,
        weights_hash: str,
        losses: list[float],
        runtime: dict[str, str],
        image_count: int,
    ) -> str | None:
        client = self.client or httpx.AsyncClient(timeout=2, trust_env=False)
        try:

            async def post(path: str, body: dict[str, object]) -> dict[str, Any]:
                response = await client.post(
                    self.url + "/api/2.0/mlflow/" + path, json=body, timeout=2
                )
                response.raise_for_status()
                return dict(response.json())

            experiment = await client.get(
                self.url + "/api/2.0/mlflow/experiments/get-by-name",
                params={"experiment_name": "flint-project-style"},
                timeout=2,
            )
            if experiment.status_code == 404:
                experiment_id = (await post("experiments/create", {"name": "flint-project-style"}))[
                    "experiment_id"
                ]
            else:
                experiment.raise_for_status()
                experiment_id = experiment.json()["experiment"]["experiment_id"]
            timestamp = int(time.time() * 1000)
            created = await post(
                "runs/create",
                {
                    "experiment_id": experiment_id,
                    "start_time": timestamp,
                    "tags": [{"key": "flint.job_id", "value": str(job_id)}],
                },
            )
            run_id = str(created["run"]["info"]["run_id"])
            metrics = [
                {"key": "loss", "value": value, "step": step, "timestamp": timestamp}
                for step, value in enumerate(losses, 1)
            ]
            for key in (
                "seconds",
                "peak_allocated_bytes",
                "host_rss_bytes",
                "dedicated_used_bytes_after",
            ):
                if key in runtime and math.isfinite(value := float(runtime[key])):
                    metrics.append({"key": key, "value": value, "step": 0, "timestamp": timestamp})
            await post(
                "runs/log-batch",
                {
                    "run_id": run_id,
                    "metrics": metrics,
                    "params": [
                        {"key": key, "value": value}
                        for key, value in {
                            "base_sha256": base_hash,
                            "dataset_sha256": dataset_hash,
                            "recipe_sha256": recipe_hash,
                            "weights_sha256": weights_hash,
                            "images": str(image_count),
                            "rank": "4",
                            "steps": str(len(losses)),
                        }.items()
                    ],
                    "tags": [],
                },
            )
            await post(
                "runs/update", {"run_id": run_id, "status": "FINISHED", "end_time": timestamp}
            )
            return run_id
        except Exception:
            return None
        finally:
            if self.client is None:
                await client.aclose()
