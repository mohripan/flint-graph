# Preparing the AWS deployment

[ADR 0077](../adr/0077-one-small-server-and-one-sleeping-gpu.md), [runbook](../runbooks/aws-deployment.md).
**Nothing was created in AWS.** The project was checked before and after: no instances, no stacks. The only AWS
calls were read-only: prices, Spot history, quotas, and `--dry-run`.

## What it would cost

From `deploy/cost/estimate.py`, using Sydney list prices fetched on 2026-11-07 into `deploy/cost/prices.json`.
These are estimates, and the disk and visit figures are assumptions until there is real usage.

**About $52 a month with nobody using it:**

| Item | USD/month |
| --- | ---: |
| t3a.medium always on | 34.67 |
| Its public IP address | 3.65 |
| Its disks (20 GB system + 40 GB data) | 5.76 |
| Daily backups (about 15 GB of snapshots) | 0.82 |
| GPU server's disk while stopped (70 GB) | 6.72 |
| **Total** | **51.63** |

**Whole monthly bill with use**, on-demand. A visit is 15 minutes of use, the 5-minute idle wait, and an estimated
3-minute boot. Visits that overlap share the GPU, so these are upper limits for that count.

| Usage | GPU hours | g4dn.xlarge | g6.xlarge | g5.xlarge |
| --- | ---: | ---: | ---: | ---: |
| nobody uses it | 0.0 | 51.63 | 51.63 | 51.63 |
| 10 visits | 3.8 | 54.27 | 55.66 | 56.66 |
| 50 visits | 19.2 | 64.84 | 71.78 | 76.80 |
| 200 visits | 76.7 | 104.45 | 132.24 | 152.29 |
| worst case: 3 h cap every day | 90.0 | 113.64 | 146.26 | 169.80 |

One visit costs about $0.40 of GPU time on g6. The 3-hour daily cap is what makes the worst case a known number.

**Other ways to change it:**

| Choice | Change, USD/month |
| --- | ---: |
| t3a.small (2 GB, same CPU allowance) instead of t3a.medium (4 GB) | -17.30 |
| t3a.large (8 GB) instead of t3a.medium (4 GB) | +34.67 |
| t4g.medium (Arm, needs Arm images) instead of t3a.medium | -3.72 |
| Each 10 GB of art on S3 instead of the server's disk | -0.71 |
| Each 10 GB more GPU disk (music, poses, more voices) | +0.96 |

Also: g6 Spot has a 14-day median of $0.61 an hour against $1.05, with interruptions. The first provisioning is about
an hour of GPU time. The first 100 GB out to the internet each month is free, then $0.114 per GB. GitHub's registry is
free for this public repository. The $100 of credits would last about 1.8 months at 10 visits a month on g6.

**Sizing evidence:** k3s with every always-on service, at idle with no visitors, used 1,376 MB of real memory in the local
run below. Flux would add an estimated 200 MB. So `t3a.small` might work with swap, but this is an idle figure, and
PostgreSQL's cache and uploads need room. It is one setting to change later.

**The GPU disk is 70 GB, not the 60 GB first planned,** from what the first deployment would store:

| Item | GB |
| --- | ---: |
| GPU worker image (measured) | 13.0 |
| API image (measured) | 0.6 |
| Ollama image (3.39 GB download, stored size estimated at 2.5 times that) | 8.5 |
| Pinned models (measured) | 10.1 |
| Assistant and vision models (measured) | 8.5 |
| Ubuntu, driver, k3s, AWS CLI, repository (estimate) | 10.0 |
| **Total** | **50.7** |

That is 84% of 60 GB, where Kubernetes starts removing images at 85%, and is 72% of 70 GB. An update that changes the runtimes'
locks stores another 13 GB until the old image is cleaned up, reaching 91%. Poses and music need the disk to grow. A
disk can grow but not shrink, so it starts here.

## What was exercised, and how

No AWS was involved. The local run used k3s v1.37.2+k3s1 in a Docker container capped at 2.5 GB, with the real
manifests, the real Traefik settings and locally built images. It has been removed.

| Claim | Evidence |
| --- | --- |
| CDK templates are valid | `cdk synth --strict` exits 0. 12 tests on the templates pass |
| Manifests are valid | `kustomize build`, then `kubeconform -strict`: 22 and 2 resources, all valid |
| Settings are accepted | `test_deploy_manifests.py` runs them through the application's own `Settings` |
| Ansible is well formed | `ansible-playbook --syntax-check` and `ansible-lint`. The model download arguments were run for real with `echo` |
| Always-on services start | PostgreSQL, Temporal, MinIO, frontend, dispatcher and API all reached `Available` |
| Migrations run | The init container applied them all on real PostgreSQL, to `0058` |
| Readiness is real | `/health/ready` is 200 through checks of PostgreSQL, MinIO and Temporal |
| No TLS redirect loop | `/health/live` over HTTPS through Traefik is 200, with `FLINT_GRAPH_REQUIRE_TLS=true` |
| HTTP redirects | `http://…/studio?x=1` gives 301 to `https://…/studio?x=1` |
| Only the right things are public | `/v1` without sign-in is 401, and with dev headers too. `/health/ready` and `/docs` get the page. Host `api` and other names are 404 |
| A client cannot forge its address | `X-Forwarded-For: 6.6.6.6` does not appear in the API's log |
| Data survives | Deleting every stateful pod keeps the bucket, the database at `0058` and Temporal's file |
| Only the controller reaches the instance role | With a fake metadata service off the node: the node and a pod with the controller's label reach it, the API and dispatcher are refused, ordinary traffic still works |
| GPU pods land only on the GPU server | A second k3s node with the real label and taint got the GPU pods, and nothing else. k3s's load balancer stayed on the always-on node |
| **Stopping the GPU server is safe** | Stopped for 6 min 41 s. The pod with the real tolerations was untouched, while a control with the default limit was evicted at about 6 min 19 s. The site stayed up |
| **Waking brings pods back** | The same pod (same UID) was ready 5 s after the node started. Real boot and model loading come on top of this |

### Problems this found

Each would otherwise have shown up on a billed server or a billed hour, and each now has a test.

1. **MinIO could not be pulled.** The pin worked only from this machine's cache: the `minio/minio` repository is gone from
   Docker Hub, and Quay refuses too. Now Chainguard's build, as a non-root user. **`compose.yaml` and `ops/langfuse/compose.yml`
   still name the old image, so they fail on a machine without a cached copy.** That was left alone as a separate problem.
2. **Every application pod failed** with `CreateContainerConfigError`, because the images named their user, which
   `runAsNonRoot` cannot verify. The images now use the number.
3. **A 606 MB image came out at 9.5 GB,** because `.dockerignore` only matched `.venv` at the top level.
4. **List settings crashed the application** as bare URLs, including in `.env.production.example`. They must be JSON.
5. **HTTP gave a 404,** because the Traefik chart silently ignored a setting name that had changed.
6. **A failed k3s download could go unnoticed** with `curl | sh`. The installer is now fetched from the pinned release first.
7. **The GPU image was 24.1 GB,** because both runtimes carry the same 7 GB of PyTorch. Hard links keep one copy, making it 13 GB to
   store and 4.5 GB to download instead of 8.5 GB.
8. **Any code change would have rebuilt and re-downloaded all of that** on a machine billed by the hour, with the runtimes and
   application in one layer. The runtimes now build from their locks alone, as their own layer. This one is by reading the
   file, as its build did not finish: see below.

## What has not been exercised

Everything below happens for the first time on real AWS, and the runbook marks it.

- **Any real GPU use in the cluster:** the driver install and reboot, k3s picking up the `nvidia` runtime, and pods seeing the
  GPU through `NVIDIA_VISIBLE_DEVICES`. The stand-in node had no GPU. Without the toolkit a pod reports
  `FailedCreatePodSandBox … unable to get OCI runtime`, which is what to look for.
- **The controller against real EC2,** as ADR 0070 already says. It has only run against a fake.
- **WireGuard between the servers.** The local run used k3s's default network, since Docker Desktop's kernel may lack it.
- **A real certificate.** Traefik accepted the settings and tried Let's Encrypt, which needs a real domain to succeed.
- **`ansible-pull` on a real server.** Only syntax, lint and one expression were checked.
- **Flux,** and **the GPU image as committed:** see the sections below.
- **A signed-in visit.** No sign-in provider exists yet, so nothing past 401 was tried in this deployment.

## Not built

- **Playtests:** `serve_preview.py` refuses anything but a `localhost` parent on `127.0.0.1`, deliberately. The Play button will not
  work until it has a production mode on its own hostname. This matters for a first demo.
- **Release builds:** `narrative_worker` runs `docker`, and k3s has only containerd.
- **A sign-in provider,** and the CDK for one. Real people cannot use the site until this exists.
- **Poses, training and music** on the deployed GPU.

## The GPU worker image

Be exact about which version each result belongs to, as the file changed twice.

| Version of `gpu-worker.Dockerfile` | Result |
| --- | --- |
| One layer | Built in about 28 minutes, 24.1 GB. Both runtimes and both worker modules import. With this laptop's RTX 5070 Ti (`--gpus all`), `nvidia-smi` works and PyTorch sees the GPU, reports bf16 and runs a small tensor on it |
| One layer, hard links | 13 GB stored, 4.46 GB download. Both runtimes import, and `torch` has one inode with two links. No GPU run on this version |
| Two layers (**the file as committed**) | **Has not finished a build.** Claude Code stopped it at about 30 minutes because the machine ran critically low on memory, and it was not retried. It passes `docker buildx build --check`. The commands are the same as the version above, in a different order |

So the saving on code changes follows from the file's structure, and has not been measured. No image or voice was generated inside the
container either, as loading a model was not worth the risk with memory this short. The first full build of this file should check
`stat -c %h` on `lib/python3.12/site-packages/torch/lib/libtorch_cpu.so` in both runtimes, which should say 2.

## Checks run

Passed: `uv run pytest tests/unit/test_deploy_manifests.py tests/unit/test_narrative_builder_prepare.py` (36 tests),
`uv run --frozen pytest` in `deploy/cdk` (12), `uv run ruff check .`, `uv run mypy`, `cdk synth --strict`, the eval gate,
`alembic upgrade head --sql`, `docker compose config -q`, `kustomize build` with `kubeconform -strict`,
`ansible-playbook --syntax-check` and `ansible-lint`.

Not run locally: the full `uv run pytest`, because of the same memory shortage. No application code changed (nothing under `src`, `migrations`,
`frontend`, `prompts`, `runtimes` or `tools`), and CI runs the full suite on the push. Flux itself has not been run: its files passed
`kubeconform`, and the manifests were applied directly with `kubectl`. It can only fetch from `master`, so it needs this commit
first, and another local cluster.
