# Deploying to AWS

[ADR 0077](../adr/0077-one-small-server-and-one-sleeping-gpu.md) explains the design and
[ADR 0070](../adr/0070-a-gpu-that-sleeps.md) the GPU's sleep. Prices are in
`docs/reports/2026-11-07-aws-preparation.md`, and `deploy/cost/estimate.py` prints them again.

**Nothing here has run on real AWS yet.** Expect to fix things at the steps marked *first time*.

Steps 5 and 8 start spending money. Each step can wait as long as you like, and everything before step 5
costs a few cents a month at most.

## What you need first

1. **The paid plan.** The free plan cannot launch `t3a.medium` or any GPU. Upgrade in AWS Settings;
   remaining credits carry over. Set a spend limit there, knowing that reaching it pauses the project.
2. **A GPU quota.** "Running On-Demand G and VT instances" is 0. In Service Quotas, ask for 4 vCPUs in
   ap-southeast-2 for one `g6.xlarge`. AWS decides this by hand, so it can take days.
3. **A domain name**, and the ability to add an `A` record for it.
4. **A sign-in provider** that speaks OIDC. Cognito is free for up to 10,000 monthly users. Keycloak on the
   always-on server needs about 600 MB more memory than it has spare, so probably a bigger server.
5. **Locally:** the AWS CLI with the `flintgraph` profile, `uv` and Node 22 or 24. Never paste AWS keys into
   a chat.

## 1. Fill in the placeholders

Replace `studio.example.com` in `deploy/k8s/production/config.env` and `deploy/k8s/production/ingress.yaml`,
and set `FLINT_GRAPH_OIDC_ISSUER` and `FLINT_GRAPH_OIDC_AUDIENCE`. `uv run pytest tests/unit/test_deploy_manifests.py`
checks that the application accepts them. These files are public, so secrets never go here.

## 2. Build the images

In GitHub Actions run **Deploy images** on `master` with your issuer URL and client ID, which are written
into the frontend. Put the commit hash it ran on in the three `newTag` lines of
`deploy/k8s/production/kustomization.yaml`, then merge.

The GPU image takes about 30 minutes when its runtimes changed, and is about 4.5 GB to download. **Its final two-layer form has not
finished a build anywhere yet**, and GitHub's runner may run short of disk *(first time)*. The workflow frees space first. If it still runs
out, use a larger runner, or build it elsewhere and push it to the same name. When it finishes, check that
`stat -c %h /app/runtimes/voicegen/.venv/lib/python3.12/site-packages/torch/lib/libtorch_cpu.so` inside the image says 2.

## 3. Store the secrets

Parameter Store holds them, and is free at this size. The always-on server copies everything under
`/flintgraph/app/` into a Kubernetes Secret, using the last part of each name as the key. Generate new
values, and do not let them reach shell history or a chat.

| Parameter | Value |
| --- | --- |
| `/flintgraph/config/acme-email` | Where Let's Encrypt sends certificate warnings (a plain `String`) |
| `/flintgraph/app/POSTGRES_PASSWORD` | A new random password |
| `/flintgraph/app/FLINT_GRAPH_DATABASE_URL` | `postgresql+asyncpg://flint_graph:<that password>@postgres:5432/flint_graph` |
| `/flintgraph/app/FLINT_GRAPH_OBJECT_STORE_ACCESS_KEY_ID` | A new random name |
| `/flintgraph/app/FLINT_GRAPH_OBJECT_STORE_SECRET_ACCESS_KEY` | A new random password |
| `/flintgraph/app/FLINT_GRAPH_ACCESS_ADMIN_EMAILS` | The operators' email addresses |

Except for the email, use `aws ssm put-parameter --type SecureString --region ap-southeast-2 --profile flintgraph`.
The password must be URL-safe, since it goes inside a URL: use `openssl rand -hex 32`.

## 4. Prepare CDK

```powershell
cd deploy/cdk
uv run --frozen pytest
$env:CDK_DEFAULT_ACCOUNT = (aws sts get-caller-identity --profile flintgraph --query Account --output text)
npx aws-cdk@2.1148.0 synth --strict
npx aws-cdk@2.1148.0 bootstrap --profile flintgraph
npx aws-cdk@2.1148.0 diff --profile flintgraph
```

Bootstrap creates a small S3 bucket and some roles, for a few cents a month at most. Read the diff.

To get budget emails, add `-c alert_email=you@example.com` to `diff` and `deploy`. Without it the budget
exists but tells nobody.

## 5. Create the always-on server

This starts about $45 a month, and the GPU server's stopped disk adds about $7 in step 8.

```powershell
npx aws-cdk@2.1148.0 deploy FlintGraphFoundation --profile flintgraph
```

The output has `PublicIp` and `ControlInstanceId`. The server sets itself up in about 10 minutes
*(first time)*:

```powershell
aws ssm start-session --target <ControlInstanceId> --profile flintgraph
journalctl -u flintgraph-provision -f
```

It has no SSH port: Session Manager is the only way in. If provisioning failed, fix the cause in Git, then
`sudo systemctl start flintgraph-provision`.

## 6. Open the site

Point the domain's `A` record at `PublicIp`, then turn on Flux, on the server:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
sudo -E flux resume kustomization flintgraph -n flux-system
sudo k3s kubectl get pods -n flintgraph
```

Pods for the GPU stay `Pending`, which is correct. Everything else should become `Ready`. Then
`https://<your domain>/` should load with a real certificate, and signing in should work.

## 7. Stop and look

This is a good place to stop and look at the site before GPU costs begin. Until the GPU server exists the Studio works for
editing by hand, but the assistant and generating wait with nothing to run them. Do not invite anyone yet.

## 8. Create the GPU server

CloudFormation cannot create a stopped instance, so **this starts about $1 an hour straight away**. Allow
about an hour for the driver, a reboot, about 19 GB of models and the images. It stops itself after 5 hours
whatever happens. The controller is off, so nothing stops it sooner than that unless you do.

```powershell
npx aws-cdk@2.1148.0 deploy FlintGraphGpu --profile flintgraph
```

Then, on the always-on server, watch it arrive:

```bash
sudo k3s kubectl get nodes
sudo k3s kubectl get pods -n flintgraph -w
```

If the node never appears or the pods fail, look on the GPU server itself, with `aws ssm start-session` and
`journalctl -u flintgraph-provision`. Things most likely to need attention *(first time)*: the driver branch in
`deploy/ansible/vars/versions.yml`, and whether k3s picked up the `nvidia` runtime
(`sudo grep nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml`).

Sign in with an invitation, send the assistant a message, then generate a sprite and a voice line. When that
works, stop the server by hand: `aws ec2 stop-instances --instance-ids <id> --profile flintgraph`.

## 9. Let it sleep

Start it again and time how long the first chat reply takes. That is your cold start. Then, in Git:

1. In `deploy/k8s/base/config.env`, set `FLINT_GRAPH_NARRATIVE_GPU_SLEEPS=true` and add
   `FLINT_GRAPH_NARRATIVE_GPU_WAKE_SECONDS=<your cold start>`.
2. In `deploy/k8s/base/controller.yaml`, set `replicas: 1`.

This must come last, since the controller stops a server whose workers are silent, including one still being set
up. `tests/unit/test_deploy_manifests.py` asserts the safe starting values, so update that test in the same change.

Stop the GPU, then check all of this:

- Sending a chat message starts it, and the page says it is waking.
- Five minutes after the last work, it stops.
- `aws ec2 describe-instances --filters Name=tag:flintgraph-gpu,Values=1 --query "Reservations[].Instances[].State.Name" --profile flintgraph` agrees.

The controller's alarms are listed in [the sleep runbook](gpu-sleep-and-wake.md#alarms).

## Everyday

**Deploying a change:** run **Deploy images**, then update `newTag` in Git. Flux applies it within 10 minutes. GPU
pods change when that server next wakes.

**Looking inside:** `aws ssm start-session`, then `sudo k3s kubectl ...`. Nothing but 80 and 443 is open to the internet.

**If the GPU disk fills up:** raise `gpu_root_gb` in `deploy/cdk/flintgraph_infra/config.py` and `GPU_ROOT_GB` in
`deploy/cost/estimate.py`, then deploy. Disks can only grow. Ubuntu extends the filesystem at the next boot, which here is the next wake.

**If MinIO's image will not pull:** Chainguard offers only `latest` for free, so the pinned digest can disappear. A running server keeps its
copy. Find the current digest with `docker buildx imagetools inspect cgr.dev/chainguard/minio:latest`, and test it before pinning it.

**Changing a secret:** change the parameter, then `sudo /usr/local/sbin/flintgraph-provision` on the always-on server,
then `sudo k3s kubectl rollout restart deployment -n flintgraph`. A new database password must also be set inside
PostgreSQL, which only reads its variable when the folder is empty.

**Restoring from a snapshot:** stop the always-on server, create a volume from the snapshot in the same zone, swap it
for the one attached at `/dev/sdf`, start the server. A swapped volume keeps its label, so it mounts by itself.

**Replacing the always-on server:** data is safe on its own disk, but the cluster starts empty with a new join token.
Run `flux resume` again and `sudo rm /var/lib/flintgraph-provisioned` on the GPU server, uninstall k3s there with
`/usr/local/bin/k3s-agent-uninstall.sh`, and start `flintgraph-provision`.

## Taking it down

```powershell
npx aws-cdk@2.1148.0 destroy FlintGraphGpu --profile flintgraph
```

Foundation has termination protection and its server has API termination protection, on purpose. To remove it, turn both
off, then destroy. **The data disk and its snapshots are kept and keep billing** (about $5 a month) until you delete them
yourself in the console, which permanently deletes every project.
