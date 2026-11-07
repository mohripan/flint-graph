"""The deployment files must agree with the application and with each other.

Nothing here touches a cluster or AWS. A wrong setting name is silently ignored at runtime, and a
GPU pod without its tolerations disappears the first time the GPU server sleeps, so both are
checked where they are cheap to find.
"""

import importlib.util
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from flint_graph.config import Settings

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "deploy/k8s/base"
PRODUCTION = ROOT / "deploy/k8s/production"
GPU_KEY = "flintgraph.io/gpu"
# A deployment's own secrets, which the Secret holds and this public repository never does.
SECRETS = {
    "FLINT_GRAPH_DATABASE_URL": "postgresql+asyncpg://flint_graph:x@postgres:5432/flint_graph",
    "FLINT_GRAPH_OBJECT_STORE_ACCESS_KEY_ID": "dummy-access-key",
    "FLINT_GRAPH_OBJECT_STORE_SECRET_ACCESS_KEY": "dummy-secret-key",
    "FLINT_GRAPH_ACCESS_ADMIN_EMAILS": "operator@example.com",
}


def _env_file(path: Path) -> dict[str, str]:
    lines = path.read_text("utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def _config() -> dict[str, str]:
    return {**_env_file(BASE / "config.env"), **_env_file(PRODUCTION / "config.env")}


def _documents() -> Iterator[dict[str, Any]]:
    for path in sorted(BASE.glob("*.yaml")):
        if path.name != "kustomization.yaml":
            yield from yaml.safe_load_all(path.read_text("utf-8"))


def _deployments() -> dict[str, dict[str, Any]]:
    return {
        document["metadata"]["name"]: document
        for document in _documents()
        if document["kind"] == "Deployment"
    }


def _containers(deployment: dict[str, Any]) -> list[dict[str, Any]]:
    spec = deployment["spec"]["template"]["spec"]
    return [*spec.get("initContainers", []), *spec["containers"]]


def _env_names(deployment: dict[str, Any]) -> set[str]:
    return {
        item["name"] for container in _containers(deployment) for item in container.get("env", [])
    }


def _is_gpu(deployment: dict[str, Any]) -> bool:
    return GPU_KEY in deployment["spec"]["template"]["spec"].get("nodeSelector", {})


def test_every_setting_is_one_the_application_reads() -> None:
    names = set(_config()) | set(SECRETS)
    for deployment in _deployments().values():
        names |= {name for name in _env_names(deployment) if name.startswith("FLINT_GRAPH_")}
    known = {f"FLINT_GRAPH_{field.upper()}" for field in Settings.model_fields}
    assert names - known == set()


def test_production_settings_pass_the_applications_own_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {**_config(), **SECRETS}.items():
        monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.env == "production"
    assert settings.auth_mode == "oidc"
    assert settings.access_mode == "invite"
    assert settings.require_tls
    assert "api" in settings.trusted_hosts
    assert settings.narrative_gpu_daily_cap_hours == 3
    # The controller needs a real tag to find the GPU server, the same one CDK puts on it.
    assert settings.narrative_gpu_instance_tag == "flintgraph-gpu=1"


def test_those_checks_would_notice_a_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _config().items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_a_smaller_gpu_can_free_the_assistant_model_for_a_picture_or_voice() -> None:
    # A 16 GB card cannot hold the assistant's model and SDXL together, and without these a job
    # that finds the GPU busy would fail rather than ask Ollama to let go.
    config = _config()
    assistant = config["FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL"]
    assert config["FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL"] == assistant
    assert config["FLINT_GRAPH_NARRATIVE_VOICE_RELEASE_OLLAMA_MODEL"] == assistant


def test_nothing_tries_to_change_the_gpu_type_or_take_backups() -> None:
    config = _config()
    assert "FLINT_GRAPH_NARRATIVE_GPU_FALLBACK_INSTANCE_TYPE" not in config
    assert "FLINT_GRAPH_NARRATIVE_GPU_INSTANCE_TYPE" not in config
    foundation = ROOT / "deploy/cdk/flintgraph_infra/foundation.py"
    assert "dlm" not in foundation.read_text("utf-8")


def test_the_public_never_gets_development_sign_in() -> None:
    assert _config()["FLINT_GRAPH_AUTH_MODE"] == "oidc"
    assert "FLINT_GRAPH_ALLOW_UNSAFE_DEV_AUTH" not in _config()
    frontend = (ROOT / "ops/deploy/frontend.Dockerfile").read_text("utf-8")
    assert "VITE_FLINT_GRAPH_AUTH_MODE=oidc" in frontend


def test_each_worker_is_a_real_process_with_its_own_switch() -> None:
    modules = {path.stem for path in (ROOT / "src/flint_graph/processes").glob("*.py")}
    for name, deployment in _deployments().items():
        command = _containers(deployment)[-1].get("command", [])
        if command[:2] == ["python", "-m"]:
            module = command[2].removeprefix("flint_graph.processes.")
            assert module in modules, name


@pytest.mark.parametrize(
    ("name", "flag"),
    [
        ("gpu-dispatch", "FLINT_GRAPH_NARRATIVE_GPU_DISPATCH_ENABLED"),
        ("gpu-controller", "FLINT_GRAPH_NARRATIVE_GPU_CONTROLLER_ENABLED"),
        ("assistant-worker", "FLINT_GRAPH_NARRATIVE_ASSISTANT_WORKER_ENABLED"),
        ("image-worker", "FLINT_GRAPH_NARRATIVE_IMAGE_WORKER_ENABLED"),
        ("voice-worker", "FLINT_GRAPH_NARRATIVE_VOICE_WORKER_ENABLED"),
    ],
)
def test_a_switch_is_on_only_where_its_process_runs(name: str, flag: str) -> None:
    assert flag not in _config()
    owners = [key for key, value in _deployments().items() if flag in _env_names(value)]
    assert owners == [name]


def test_gpu_pods_wait_for_the_gpu_server_and_nothing_else_lands_there() -> None:
    gpu = 0
    for name, deployment in _deployments().items():
        spec = deployment["spec"]["template"]["spec"]
        if not _is_gpu(deployment):
            assert "tolerations" not in spec, name
            continue
        gpu += 1
        tolerations = {item["key"]: item for item in spec["tolerations"]}
        assert {GPU_KEY, "node.kubernetes.io/unreachable", "node.kubernetes.io/not-ready"} <= set(
            tolerations
        ), name
        # A time limit here would evict the pod a few minutes into every sleep.
        assert all("tolerationSeconds" not in item for item in tolerations.values()), name
        assert deployment["spec"]["strategy"]["type"] == "Recreate", name
    assert gpu == 4


def test_gpu_pods_that_use_the_gpu_can_see_it() -> None:
    for name in ("ollama", "image-worker", "voice-worker"):
        deployment = _deployments()[name]
        assert deployment["spec"]["template"]["spec"]["runtimeClassName"] == "nvidia", name
        assert "NVIDIA_VISIBLE_DEVICES" in _env_names(deployment), name


def test_gpu_workers_only_execute() -> None:
    for name, deployment in _deployments().items():
        if _is_gpu(deployment) and name != "ollama":
            assert "FLINT_GRAPH_NARRATIVE_GPU_EXECUTE_ONLY" in _env_names(deployment), name
    assert "FLINT_GRAPH_NARRATIVE_GPU_EXECUTE_ONLY" not in _config()


def test_no_image_can_change_unseen() -> None:
    for name, deployment in _deployments().items():
        for container in _containers(deployment):
            image = container["image"]
            if image.startswith("ghcr.io/mohripan/"):
                assert image.endswith(":unset"), name
            else:
                assert "@sha256:" in image, name


def test_the_data_lives_on_the_retained_disk_under_fixed_folders() -> None:
    tasks = (ROOT / "deploy/ansible/roles/data_volume/tasks/main.yml").read_text("utf-8")
    for name in ("postgres", "minio", "temporal"):
        spec = _deployments()[name]["spec"]["template"]["spec"]
        assert spec["volumes"][0]["hostPath"]["path"] == f"/var/lib/flintgraph/{name}"
        # Created by Ansible, so a data disk that failed to mount stops the pod rather than
        # letting it write to the root disk and lose the data at the next replacement.
        assert spec["volumes"][0]["hostPath"]["type"] == "Directory"
        assert f"{{name: {name}," in tasks


def test_model_pins_agree_between_download_and_workers() -> None:
    config = _config()
    models = yaml.safe_load((ROOT / "deploy/ansible/vars/models.yml").read_text("utf-8"))
    pins = {model["name"]: model["manifest_sha256"] for model in models["flintgraph_models"]}
    settings = {
        "animagine-xl-4.0": ("IMAGE_MODEL_DIR", "IMAGE_MODEL_MANIFEST_SHA256"),
        "anime-seg": ("IMAGE_CUTOUT_MODEL_DIR", "IMAGE_CUTOUT_MANIFEST_SHA256"),
        "ip-adapter": ("IMAGE_IP_ADAPTER_MODEL_DIR", "IMAGE_IP_ADAPTER_MANIFEST_SHA256"),
        "kokoro-82m": ("VOICE_MODEL_DIR", "VOICE_MODEL_MANIFEST_SHA256"),
    }
    assert set(pins) == set(settings)
    for name, (directory, manifest) in settings.items():
        assert config[f"FLINT_GRAPH_NARRATIVE_{directory}"] == f"/models/{name}"
        assert config[f"FLINT_GRAPH_NARRATIVE_{manifest}"] == pins[name]


def test_the_gpu_cannot_be_stopped_until_it_has_been_set_up() -> None:
    assert _deployments()["gpu-controller"]["spec"]["replicas"] == 0
    # "It will wake" would be untrue with no controller running.
    assert _config()["FLINT_GRAPH_NARRATIVE_GPU_SLEEPS"] == "false"


def test_flux_applies_nothing_until_it_is_turned_on() -> None:
    documents = yaml.safe_load_all(
        (ROOT / "deploy/flux/production/flintgraph.yaml").read_text("utf-8")
    )
    application = next(item for item in documents if item["kind"] == "Kustomization")
    assert application["spec"]["suspend"] is True
    assert application["spec"]["path"] == "./deploy/k8s/production"
    assert application["spec"]["wait"] is False


def test_the_daily_limit_matches_the_cost_estimate() -> None:
    estimate = (ROOT / "deploy/cost/estimate.py").read_text("utf-8")
    match = re.search(r"^DAILY_CAP_HOURS\s*=\s*(\d+)", estimate, re.MULTILINE)
    assert match is not None
    assert _config()["FLINT_GRAPH_NARRATIVE_GPU_DAILY_CAP_HOURS"] == match.group(1)


@pytest.mark.parametrize(
    ("estimate_name", "field"),
    [
        ("CONTROL", "control_instance_type"),
        ("CONTROL_ROOT_GB", "control_root_gb"),
        ("DATA_GB", "data_gb"),
        ("GPU", "gpu_instance_type"),
        ("GPU_ROOT_GB", "gpu_root_gb"),
    ],
)
def test_the_estimate_prices_what_cdk_would_create(estimate_name: str, field: str) -> None:
    estimate = (ROOT / "deploy/cost/estimate.py").read_text("utf-8")
    config = (ROOT / "deploy/cdk/flintgraph_infra/config.py").read_text("utf-8")
    priced = re.search(rf"^{estimate_name}\s*=\s*\"?([\w.]+)\"?$", estimate, re.MULTILINE)
    created = re.search(rf"^\s+{field}:\s*\w+\s*=\s*\"?([\w.]+)\"?$", config, re.MULTILINE)
    assert priced is not None and created is not None
    assert priced.group(1) == created.group(1)


def test_images_name_a_user_kubernetes_can_verify_is_not_root() -> None:
    # A name fails every pod with runAsNonRoot, with CreateContainerConfigError.
    for name in ("Dockerfile", "ops/deploy/gpu-worker.Dockerfile"):
        users = re.findall(r"^USER (\S+)$", (ROOT / name).read_text("utf-8"), re.MULTILINE)
        assert users == ["10001"], name


def test_a_code_change_does_not_download_the_gpu_runtimes_again() -> None:
    text = (ROOT / "ops/deploy/gpu-worker.Dockerfile").read_text("utf-8")
    runtimes = text.split("AS runtimes", 1)[1].split("AS application", 1)[0]
    # Built from their locks alone, so nothing else invalidates them.
    assert "COPY src" not in runtimes
    assert "COPY runtimes ./runtimes" not in runtimes
    # And their own layer of the image, before the part that changes.
    final = text.split("AS runtime\n", 1)[1]
    assert final.index("--from=runtimes") < final.index("--from=application")


def test_identical_runtime_files_share_one_copy(tmp_path: Path) -> None:
    specification = importlib.util.spec_from_file_location(
        "share_identical_files", ROOT / "ops/deploy/share_identical_files.py"
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)

    first, second = tmp_path / "first", tmp_path / "second"
    for folder in (first, second):
        (folder / "torch").mkdir(parents=True)
        (folder / "torch/same.so").write_bytes(b"identical")
    (first / "pyvenv.cfg").write_text("home = one")
    (second / "pyvenv.cfg").write_text("home = two")
    (second / "only-here.txt").write_text("kept")

    assert module.share(first, second) == len(b"identical")

    assert (first / "torch/same.so").samefile(second / "torch/same.so")
    assert not (first / "pyvenv.cfg").samefile(second / "pyvenv.cfg")
    assert (second / "pyvenv.cfg").read_text() == "home = two"
    assert (second / "only-here.txt").read_text() == "kept"


def test_local_virtual_environments_stay_out_of_images() -> None:
    # ".venv" alone matches only at the top, which once made a 606 MB image 9.5 GB.
    ignored = (ROOT / ".dockerignore").read_text("utf-8").splitlines()
    assert "**/.venv" in ignored
    assert "**/node_modules" in ignored


def test_each_data_folder_belongs_to_the_user_its_image_runs_as() -> None:
    tasks = (ROOT / "deploy/ansible/roles/data_volume/tasks/main.yml").read_text("utf-8")
    owners = dict(re.findall(r'\{name: (\w+), owner: "(\d+)"\}', tasks))
    assert owners == {"postgres": "70", "minio": "65532", "temporal": "1000"}


def test_minio_comes_from_where_it_can_still_be_pulled() -> None:
    # minio/minio is gone from Docker Hub and Quay, and only ever worked here from a local cache.
    image = _containers(_deployments()["minio"])[0]["image"]
    assert image.startswith("cgr.dev/chainguard/minio@sha256:")
    # That build has no "mc", so nothing else may rely on it.
    for name, deployment in _deployments().items():
        for container in _containers(deployment):
            assert "mc " not in " ".join(container.get("command", [])), name


def test_traefik_is_given_settings_its_chart_actually_reads() -> None:
    # The chart ignores unknown names silently: "ports.web.redirections" left http as a 404.
    template = ROOT / "deploy/ansible/roles/k3s_server/templates/traefik-config.yaml.j2"
    outer = yaml.safe_load(re.sub(r"\{\{.*?\}\}", "dummy", template.read_text("utf-8")))
    values = yaml.safe_load(outer["spec"]["valuesContent"])
    assert values["ports"]["web"]["http"]["redirections"]["entryPoint"]["to"] == "websecure"
    assert values["service"]["spec"]["externalTrafficPolicy"] == "Local"
    assert "letsencrypt" in values["certificatesResolvers"]


def test_only_the_controller_can_reach_the_instance_role() -> None:
    policy = next(item for item in _documents() if item["kind"] == "NetworkPolicy")
    selector = policy["spec"]["podSelector"]["matchExpressions"][0]
    assert selector == {"key": "app", "operator": "NotIn", "values": ["gpu-controller"]}
    block = policy["spec"]["egress"][0]["to"][0]["ipBlock"]
    assert block["except"] == ["169.254.169.254/32"]


def test_the_public_route_reaches_only_what_it_should() -> None:
    ingress = yaml.safe_load((PRODUCTION / "ingress.yaml").read_text("utf-8"))
    paths = ingress["spec"]["rules"][0]["http"]["paths"]
    routes = {item["path"]: item["backend"]["service"]["name"] for item in paths}
    assert routes == {"/v1": "api", "/health/live": "api", "/": "frontend"}
    live = next(item for item in paths if item["path"] == "/health/live")
    assert live["pathType"] == "Exact"


def test_the_production_example_can_be_read_by_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bare URL in a list setting stops the application when it reads its settings.
    for key, value in _env_file(ROOT / ".env.production.example").items():
        monkeypatch.setenv(key, re.sub(r"\$\{\w+\}", "placeholder", value))
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.allowed_origins == ["https://app.example.com"]
    assert settings.trusted_hosts == ["api.example.com"]


def test_cdks_local_cache_cannot_be_committed() -> None:
    ignored = (ROOT / "deploy/cdk/.gitignore").read_text("utf-8").splitlines()
    assert "cdk.context.json" in ignored


def test_nothing_private_is_in_the_public_repository() -> None:
    account = re.compile(r"\b\d{12}\b")
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    allowed_domains = ("example.com", "noreply.github.com")
    kinds = {".py", ".yml", ".yaml", ".env", ".j2", ".conf", ".json", ".toml"}
    for folder in ("deploy", "ops/deploy"):
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file() or path.suffix not in kinds:
                continue
            # cdk.context.json is CDK's local cache, holds the project ID, and is git-ignored.
            skipped = {"prices.json", "uv.lock", "cdk.context.json"}
            if {"cdk.out", ".venv"} & set(path.parts) or path.name in skipped:
                continue
            text = path.read_text("utf-8")
            assert not account.search(text), path
            for found in email.findall(text):
                assert found.endswith(allowed_domains), path
