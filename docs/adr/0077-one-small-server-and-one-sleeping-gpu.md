# ADR 0077: One small server and one sleeping GPU

- Status: accepted. The always-on server runs since 2026-11-07, and the GPU server waits for the Paid Plan and a quota
- Date: 2026-11-07
- Issues: #200 (its managed-service plan is replaced for now), builds on ADR 0070

## Context

The first public deployment is for people trying the Studio for about 15 minutes, by invitation. The
aim is the lowest bill that still works, on plain servers the owner controls. #200 planned managed
services: RDS, S3, CloudFront and Fargate. RDS alone would cost about as much as the whole always-on
server here, and the traffic does not need any of them yet.

## Decision

Two EC2 instances in one zone of ap-southeast-2, joined as one k3s cluster, on Ubuntu 24.04.

| Server | Type | Runs |
| --- | --- | --- |
| Always on | t3.small, 2 GB, plus 4 GB swap | Traefik, frontend, API, PostgreSQL, Temporal, MinIO, `narrative_gpu_dispatch`, `narrative_gpu_controller`, Flux |
| GPU, usually stopped | g4dn.xlarge, T4, 16 GB | Ollama, assistant, image and voice workers |

Each tool does one job:

- **CDK** creates what AWS bills for: network, servers, disks, roles, sign-in, budget.
- **Ansible**, run by `ansible-pull` on each server at first boot, sets up what is inside it: k3s, the
  NVIDIA driver, swap, secrets and model downloads.
- **Flux** keeps the cluster equal to `deploy/k8s/production` in Git. It stays suspended until the
  images exist.
- **GitHub Container Registry** holds the images, free for this public repository.

### Choices

**t3.small, because the account refused anything else that small.** At most one or two people a month are invited, and most visitors only see
static pages, so 2 GB is enough. Lightsail's 2 GB plan was the first choice, at $12 a month with its disk and address, and was built and tried: it answered
`your account can not create an instance using this Lightsail plan size`. t3a.small is $1.90 a month less, but the Free Plan refuses it as `not eligible for
Free Tier`. t3.small is the cheapest 2 GB server that plan allows, so nothing irreversible was needed to get the site up. The Lightsail code is in commit `750d53d`.

**Cognito, sending the ID token.** Real people need a real sign-in. It is free for up to 10,000 people a month. The API checks the token's audience and needs its
email, and Cognito's access token has neither without its paid feature plan, while its ID token has both. So the frontend sends the ID token, by a setting that
leaves other providers unchanged. Anyone may create an account: the invitation check in the API is what lets them in, and a real browser run confirmed it keeps them out.

**g4dn, not g6.** It is the cheapest GPU that runs what is deployed: $0.26 of GPU time per visit against
$0.40. Poses and training refuse a GPU without native bf16, which a T4 lacks, but neither is deployed. No
T4 has actually been tried: it should fit, since this all works on a 12 GB laptop, and
`*_RELEASE_OLLAMA_MODEL` frees the assistant's model when a picture needs the memory.

**On-demand, not Spot, because the plan forbids Spot.** The owner wanted Spot, and it would be about half
the price: t3a.medium $13.72 a month against $34.67, and g4dn $0.30 an hour against $0.68. But `DenySpotMarketType`
is in AWS's managed policy for the Free Plan and the Paid Plan alike, and a dry-run confirms it. Unlocking it means
activating advanced features, which AWS says cannot be reversed, and which permanently removes the spend limit. If
that is ever done: request `persistent` with interruption behaviour `stop`, so disks and the address stay and EC2 restarts
it when capacity returns. Termination protection is not allowed on Spot, the type cannot change while stopped so there is
no fallback type, and the request must be cancelled before removing a server. `IncorrectSpotRequestState` needs treating
as no capacity in `narrative_gpu_ec2.py`. Availability also differs: AWS's placement score for a g4dn was 9 of 10 and for
g6 and g5 it was 1, on 2026-11-07, so Spot would rule those two out.

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
- **One server holds everything.** If it dies, the site is down until it is replaced. That is acceptable
  for invited visitors, not for paid customers.
- **One API replica,** because the rate limit lives in its memory.
- **No backups,** the owner's choice. A lost disk, a bad migration or a mistake permanently loses every
  project. That is accepted for now.
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
- **The GPU.** Every GPU type is refused on the Free Plan, the quota was 0, and AWS is reviewing a request. So the assistant and generating have nothing to run them yet.
- **The owner's domain.** The site uses a free `sslip.io` name for its address until then.
- **Poses, training and music.** Their workers and models are not in the first deployment. Poses and
  training also refuse this GPU, so adding them means changing its type, and a larger disk.

## Evidence

See `docs/reports/2026-11-07-aws-preparation.md` for the estimate and for what was and was not exercised. The always-on server, Flux, Traefik, its certificate and
sign-in have all run for real. The GPU path has not: the driver install, the `nvidia` runtime class and waking on real AWS are unproven until the first launch.
