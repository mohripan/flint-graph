# ADR 0077: One small server and one sleeping GPU

- Status: accepted for preparation; nothing has been created in AWS
- Date: 2026-11-07
- Issues: #200 (its managed-service plan is replaced for now), builds on ADR 0070

## Context

The first public deployment is for people trying the Studio for about 15 minutes, by invitation. The
aim is the lowest bill that still works, on plain servers the owner controls. #200 planned managed
services: RDS, S3, CloudFront and Fargate. RDS alone would cost about as much as the whole always-on
server here, and the traffic does not need any of them yet.

## Decision

Two EC2 instances in one zone of ap-southeast-2, joined as one k3s cluster.

| Server | Type | Runs |
| --- | --- | --- |
| Always on | t3a.medium, 4 GB, plus 4 GB swap | Traefik, frontend, API, PostgreSQL, Temporal, MinIO, `narrative_gpu_dispatch`, `narrative_gpu_controller`, Flux |
| GPU, usually stopped | g6.xlarge, L4, 24 GB | Ollama, assistant, image and voice workers |

Each tool does one job:

- **CDK** creates what AWS bills for: network, servers, disks, roles, backups, budget.
- **Ansible**, run by `ansible-pull` on each server at first boot, sets up what is inside it: k3s, the
  NVIDIA driver, swap, secrets and model downloads.
- **Flux** keeps the cluster equal to `deploy/k8s/production` in Git. It stays suspended until the
  images exist.
- **GitHub Container Registry** holds the images, free for this public repository.

### Choices

**g6, not g4dn.** g4dn is cheaper by $0.14 per 15-minute visit, but pose and training jobs refuse a
GPU without native bf16, which its T4 is expected to lack. g5 is the fallback when g6 has no capacity.

**On-demand, not Spot, for now.** Spot is 42% cheaper on g6, and can stop the machine in the middle of
someone's generation. It is one setting to change once this runs.

**Data on a retained disk.** PostgreSQL, MinIO and Temporal use fixed folders on a separate encrypted
volume, which survives the server and even the stack being deleted. They mount it as
`hostPath` of type `Directory`, so if the disk fails to mount, the pod stops instead of writing to
the system disk. k3s's own volumes are named at random and listed in a cluster database on the system
disk, so a replacement server would not find them.

**No device plugin.** There is one GPU and everything on that server shares it. The plugin would give
the whole GPU to one pod, or need time-slicing configured to undo that. Pods use the `nvidia` runtime
class and `NVIDIA_VISIBLE_DEVICES=all` instead.

**Pods wait for the GPU server.** GPU pods tolerate `unreachable` and `not-ready` with no time limit,
so stopping that server is not a failure and they restart where they were. Flux does not wait for
health, because those pods are pending by design.

**Only the controller can use the instance role.** The role can read secrets and start the GPU. Instance
metadata needs hop limit 2 for the controller's pod to reach it, which would let every pod reach it, so a
`NetworkPolicy` blocks that address for all the others.

**Three limits on GPU hours.** Idle for 5 minutes stops it, 3 hours a day caps it, and a timer on the
machine itself stops it after 5 hours of uptime in case the always-on server is down. The very first
boot schedules a shutdown before doing anything else, since a CloudFormation launch starts billing at
once and the timer is not installed yet.

## What this gives up

- **Temporal is the development server**, with one SQLite file. It restarts cleanly from that file and
  saves about 1 GB over a real cluster, but has no high availability and no upgrade path of its own.
- **One server holds everything.** If it dies, the site is down until it is replaced. Daily disk
  snapshots mean up to a day of work can be lost. That is acceptable for invited visitors, not for paid
  customers.
- **One API replica,** because the rate limit lives in its memory.
- **Files on a disk, not S3, with software nobody upstream maintains.** Keeping everything on one server is
  the owner's choice. MinIO stopped publishing images in October 2025 and archived its repository in February
  2026, and `minio/minio` can no longer be pulled from Docker Hub or Quay. This uses Chainguard's build of it,
  which only ever offers `latest` for free, so the pinned digest may stop being available: the server keeps its
  own copy, but a replacement server might need a new pin. MinIO is reachable only inside the cluster. S3 would
  save $0.71 a month per 10 GB and 200 MB of memory, and be far more durable than a daily snapshot. The code
  already speaks S3, but pods would need scoped credentials, as the instance role is blocked for them.

## Not included yet

These stop the deployment being complete, and are listed honestly so that nobody assumes otherwise:

- **Playtests.** `serve_preview.py` deliberately serves only `127.0.0.1` for a `localhost` parent, so
  the Play button has nothing to reach. It needs a production mode on its own hostname.
- **Release builds.** `narrative_worker` builds games by calling `docker`, and k3s has only containerd.
  `FLINT_GRAPH_NARRATIVE_RELEASES_ENABLED` stays false.
- **Sign-in.** Real people must sign in with OIDC. No provider is deployed: the issuer in
  `deploy/k8s/production/config.env` is a placeholder. Development sign-in makes everyone the same user
  and must never be exposed.
- **Poses, training and music.** Their workers and models are not in the first deployment. They would
  use more of the GPU disk.

## Evidence

See `docs/reports/2026-11-07-aws-preparation.md` for the estimate and for what was and was not exercised.
The GPU path has not run anywhere yet: the driver install, the `nvidia` runtime class and waking on real
AWS are all unproven until the first real launch. The GPU image's final form has not finished a build either.
