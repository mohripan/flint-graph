# Deploying to AWS

[ADR 0077](../adr/0077-one-small-server-and-one-sleeping-gpu.md) explains the design and
[ADR 0070](../adr/0070-a-gpu-that-sleeps.md) the GPU's sleep. Prices and evidence are in
`docs/reports/2026-11-07-aws-preparation.md`, and `deploy/cost/estimate.py` prints the prices again.

## Where it stands

| Step | State |
| --- | --- |
| Always-on server, sign-in, site | **Running since 2026-11-07** at `https://flintgraph.digital` and `https://54-253-96-189.sslip.io`, on `54.253.96.189` |
| The models | **On Runpod, billed by the second:** see [the Runpod runbook](runpod-models.md) |
| A GPU server on AWS | **None.** AWS declined the quota, and the owner chose not to appeal |

## The plan and its credits

The project moved to the **Paid Plan** on 2026-11-07. The $120 of credits still apply first, and the server costs about $26.76 a month, so they last about 4.5 months. After that it bills
the card. The budget emails at $50.

AWS declined the request for 4 vCPUs of "Running On-Demand G and VT instances" on 2026-11-07 (case 179405038200148). A second request cannot be opened while that one stands. The manifests
for an AWS GPU are kept in `deploy/k8s/aws-gpu`, unused and still tested, and [the steps below](#creating-a-gpu-server-on-aws) remain.

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

**Always add `-c alert_email=<the owner's address>` to `diff` and `deploy`.** Without it, a deploy removes the budget's email and the budget then tells nobody. The address is not in this public repository.

## Looking inside

The server has no SSH port. With the Session Manager plugin, `aws ssm start-session --target <ControlInstanceId> --profile flintgraph`.
Without it, `aws ssm send-command --document-name AWS-RunShellScript` runs a command and `get-command-invocation` reads the result.
Then `sudo k3s kubectl get pods -n flintgraph`.

## Deploying a change

Run **Deploy images** in GitHub Actions on `master`, which builds the API and frontend, with:

| Input | Value |
| --- | --- |
| `oidc_authority` | The `SignInIssuer` output of `FlintGraphFoundation` |
| `oidc_client_id` | The `SignInClientId` output |
| `oidc_bearer` | `id_token` |
| `oidc_logout_url` | The `SignInLogoutUrl` output |

Put the commit it ran on in the API's and frontend's `newTag` lines of `deploy/k8s/production/kustomization.yaml` and push. Flux applies it within 10 minutes.

## Playtests

A playtest is the Godot player compiled for the browser, in a frame on its own address (`https://play.54-253-96-189.sslip.io`), so that what a story does cannot reach the signed-in site. It holds no secrets and calls no API. **Each side has the other's address built in:** the frontend has the
playtest's, and the playtest image has the one site allowed to embed it, `https://flintgraph.digital`. So a playtest does not work from the `sslip.io` address of the site itself, and changing either address means running **Deploy images** with `preview_origin` or `playtest_parent_origin`. Release builds are not deployed.

**If a playtest says "The story player did not start":** the dialog has already given the player 90 s, started a fresh one, and given that 90 s too. Closing it and retrying is safe. To see how far the download got, run `sudo k3s kubectl logs -n flintgraph deploy/playtest | grep index.wasm`. The last number is the bytes sent, and a whole download is about 10 MB. Fewer means it was cut off, as in [this report](../reports/2026-11-07-models-on-runpod.md#the-stalled-playtest).

## The domain

`flintgraph.digital` is on Cloudflare: an `A` record for `@`, pointing at `54.253.96.189`, set to **DNS only** (the grey cloud), so that Let's Encrypt and the assistant's long streams reach the server
directly. With the orange cloud the certificate check fails.

**If a certificate fails, do not restart Traefik.** It asks as soon as it starts, before traffic reaches it, so Let's Encrypt gets `Connection refused`, or a `404` from the old pod during a rollout. Only
a few failures an hour are allowed. Make the running Traefik look again by adding a route that wants no certificate, then deleting it: an `Ingress` for a name such as `nudge.invalid`, with the annotation
`traefik.ingress.kubernetes.io/router.entrypoints: web`. Certificates are kept on a small volume, so restarts do not lose them.

To move to another name, change it in `deploy/k8s/production/config.env` and `ingress.yaml`, change `site_url` in `deploy/cdk/flintgraph_infra/config.py`, and deploy `FlintGraphFoundation`, so that sign-in may
return there. No new frontend image is needed, because it uses its own address.

## Creating a GPU server on AWS

Not in use: the models are on Runpod. These steps need the AWS quota, and the manifests moved back from `deploy/k8s/aws-gpu` to `base`.

Set `gpu-dispatch` to `replicas: 1`, and put the GPU image back in `deploy-images.yml`, as commit `f18f0c4` removed it. `test_everything_offered_has_a_worker_and_a_place_to_run` changes with them.
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
which restarts it. On the Paid Plan `t3a.small` is also possible, for $1.90 a month less.

**If the disk of an AWS GPU server fills up:** raise `gpu_root_gb` in `deploy/cdk/flintgraph_infra/config.py` and `GPU_ROOT_GB` in `deploy/cost/estimate.py`, then deploy. Disks
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
