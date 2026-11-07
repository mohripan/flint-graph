# Deploying to AWS

[ADR 0077](../adr/0077-one-small-server-and-one-sleeping-gpu.md) explains the design and
[ADR 0070](../adr/0070-a-gpu-that-sleeps.md) the GPU's sleep. Prices and evidence are in
`docs/reports/2026-11-07-aws-preparation.md`, and `deploy/cost/estimate.py` prints the prices again.

## Where it stands

| Step | State |
| --- | --- |
| Always-on server, sign-in, site | **Running since 2026-11-07** at `54.253.96.189`, `https://54-253-96-189.sslip.io` |
| Your own domain | Not yet: see [Moving to your domain](#moving-to-your-domain) |
| GPU server | **None.** AWS declined the quota, and the owner chose not to appeal: see below |

The site, sign-in, invitations and editing by hand work. The assistant and generating are switched off, because nothing could run them.

## Why there is no GPU

AWS declined the request for 4 vCPUs of "Running On-Demand G and VT instances" on 2026-11-07 (case 179405038200148), and the quota stays at 0. The owner chose not to appeal: this is a personal
project, and it runs on what exists. The Free Plan also refuses every GPU (`The specified instance type is not eligible for Free Tier`), so there is no reason to upgrade for now.

Admission does not check that a worker exists, so a job with none would take credits and never run. That is why the assistant and generating are off rather than waiting.

**The Free Plan ends.** The $120 of credits last about 4.5 months at this size, and the plan itself expires on 2027-05-07. Decide before then whether to upgrade or take the site down.

## Running CDK

`aws login` sessions are not read by the CDK CLI directly, so export them first. Everything below runs from `deploy/cdk`.

```bash
eval "$(aws configure export-credentials --profile flintgraph --format env)"
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --profile flintgraph --query Account --output text)
export AWS_REGION=ap-southeast-2 CDK_DEFAULT_REGION=ap-southeast-2
npx aws-cdk@2.1148.0 synth --strict
npx aws-cdk@2.1148.0 diff FlintGraphFoundation
```

Read the diff before every deploy. `cdk.context.json` holds the project ID and is git-ignored, so it never reaches this public repository.

To get budget emails, add `-c alert_email=you@example.com` to `diff` and `deploy`. Without it the budget exists but tells nobody.

## Looking inside

The server has no SSH port. With the Session Manager plugin, `aws ssm start-session --target <ControlInstanceId> --profile flintgraph`.
Without it, `aws ssm send-command --document-name AWS-RunShellScript` runs a command and `get-command-invocation` reads the result.
Then `sudo k3s kubectl get pods -n flintgraph`. GPU pods stay `Pending` while there is no GPU server, which is correct.

## Deploying a change

Run **Deploy images** in GitHub Actions on `master`, which builds the API and frontend, with:

| Input | Value |
| --- | --- |
| `oidc_authority` | The `SignInIssuer` output of `FlintGraphFoundation` |
| `oidc_client_id` | The `SignInClientId` output |
| `oidc_bearer` | `id_token` |
| `oidc_logout_url` | The `SignInLogoutUrl` output |

Put the commit it ran on in the API's and frontend's `newTag` lines of `deploy/k8s/production/kustomization.yaml` and push. Flux applies it within 10 minutes.

## Moving to your domain

Say the name is `studio.example.com`, on Cloudflare.

1. In Cloudflare, add an `A` record for the name pointing at `54.253.96.189`, set to **DNS only** (the grey cloud), so that Let's Encrypt and
   the assistant's long streams reach the server directly.
2. Replace `54-253-96-189.sslip.io` with the name in `deploy/k8s/production/config.env` and `ingress.yaml`, and push.
3. Change `site_url` in `deploy/cdk/flintgraph_infra/config.py`, then `cdk deploy FlintGraphFoundation`, so that sign-in may return there. No new
   frontend image is needed, because it uses its own address.

## Creating the GPU server

Once the plan and the quota are both done. First turn the features back on: in `deploy/k8s/base/config.env`, set `FLINT_GRAPH_NARRATIVE_ASSISTANT_PROVIDER=ollama` and both
`*_GENERATION_ENABLED=true`. Set `gpu-dispatch` to `replicas: 1`, and put the GPU image back in `deploy-images.yml`, as commit `f18f0c4` removed it. `test_nothing_is_offered_that_no_server_can_run` changes with them.
CloudFormation cannot create a stopped instance, so **this starts about $0.69 an hour straight away**.
Allow about an hour for the driver, a reboot, about 19 GB of models and the images. It stops itself after 5 hours whatever happens. The controller
is off, so nothing stops it sooner than that unless you do.

```bash
npx aws-cdk@2.1148.0 deploy FlintGraphGpu
```

Then, on the always-on server, watch it arrive with `sudo k3s kubectl get nodes` and `sudo k3s kubectl get pods -n flintgraph -w`.

If the node never appears or the pods fail, look on the GPU server itself, in `journalctl -u flintgraph-provision`. Most likely to need attention
*(first time)*: the driver branch in `deploy/ansible/vars/versions.yml`, and whether k3s picked up the `nvidia` runtime
(`sudo grep nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml`).

Sign in with an invitation, send the assistant a message, then generate a sprite and a voice line. When that works, stop the server by hand:
`aws ec2 stop-instances --instance-ids <id> --profile flintgraph`.

### Letting it sleep

Start it again and time how long the first chat reply takes. That is your cold start. Then, in Git:

1. In `deploy/k8s/base/config.env`, set `FLINT_GRAPH_NARRATIVE_GPU_SLEEPS=true` and add
   `FLINT_GRAPH_NARRATIVE_GPU_WAKE_SECONDS=<your cold start>`.
2. In `deploy/k8s/base/controller.yaml`, set `replicas: 1`.

This must come last, since the controller stops a server whose workers are silent, including one still being set up.
`tests/unit/test_deploy_manifests.py` asserts the safe starting values, so update that test in the same change.

Stop the GPU, then check that a chat message starts it, that the page says it is waking, and that it stops five minutes after the last work.
The controller's alarms are listed in [the sleep runbook](gpu-sleep-and-wake.md#alarms).

## Everyday

**If the server runs out of memory:** it has 2 GB, with very little spare. Move to `t3a.medium` by changing `control_instance_type` and deploying,
which restarts it. On the Paid Plan `t3a.small` also becomes possible, for $1.90 a month less.

**If the GPU disk fills up:** raise `gpu_root_gb` in `deploy/cdk/flintgraph_infra/config.py` and `GPU_ROOT_GB` in `deploy/cost/estimate.py`, then deploy. Disks
can only grow. Ubuntu extends the filesystem at the next boot, which here is the next wake.

**If MinIO's image will not pull:** Chainguard offers only `latest` for free, so the pinned digest can disappear. A running server keeps its copy. Find the
current digest with `docker buildx imagetools inspect cgr.dev/chainguard/minio:latest`, and test it before pinning it.

**Changing a secret:** change the parameter under `/flintgraph/app/`, then `sudo rm /var/lib/flintgraph-provisioned`, `sudo systemctl start flintgraph-provision`
and `sudo k3s kubectl rollout restart deployment -n flintgraph`. A new database password must also be set inside PostgreSQL, which only reads its variable when
the folder is empty.

**There are no backups,** by choice. If the data disk is lost, every project is gone.

**Replacing the always-on server:** data is safe on its own disk, but the cluster starts empty with a new join token. Run `flux resume kustomization flintgraph -n flux-system`
again, and on the GPU server `sudo rm /var/lib/flintgraph-provisioned`, uninstall k3s with `/usr/local/bin/k3s-agent-uninstall.sh`, and start `flintgraph-provision`.

## Taking it down

`cdk destroy FlintGraphGpu` removes the GPU server. Foundation has termination protection and its server has API termination protection, on purpose. To remove it, turn both off,
then destroy. **The data disk and the sign-in accounts are kept**, and the disk keeps billing about $2 a month, until you delete them yourself in the console, which permanently
deletes every project.
