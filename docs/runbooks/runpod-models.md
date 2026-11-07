# The models on Runpod

[ADR 0078](../adr/0078-models-on-runpod-by-the-second.md) explains the design. The server is in
[Deploying to AWS](aws-deployment.md). Everything here is in the Runpod console, or in the Runpod plugin for
Claude Code, whose sign-in is `/mcp`.

## What exists

| What | ID | Costs |
| --- | --- | --- |
| Network volume `flintgraph-models`, 25 GB, `EU-RO-1` | `imfh1i33gn` | $1.75 a month, always |
| Endpoint `flintgraph-assistant` | `afs9c0epe9ynoz` | $0.58 to $0.75 an hour, only while a worker runs |
| Endpoint `flintgraph-generation` | `zxfk4sx2prley7` | The same |

An endpoint's worker may show as `IDLE` for hours. That is a machine holding the image ready, and it is not billed.
Spending is under **Billing** in the console.

The volume holds `models/<name>` with the pinned weights, and `ollama` with the assistant's models.

## When the balance runs out

Workers stop, and every job fails. Runpod may later delete the volume. Top up, and if the volume has gone, follow
[Putting the models back](#putting-the-models-back). No project is lost: those are on the AWS server.

Failed jobs do not refund credits, so if people lost some, give them back from **Invitations**.

## When generating fails

Look at the endpoint's **Workers** tab in the console.

- **`Throttled`, or nothing for minutes:** no card is free in `EU-RO-1`, the only data center with the cheapest cards.
  Waiting usually fixes it. To widen it, add a pool to the endpoint, for example `ADA_24` ($1.34 an hour), which also has
  stock there. The volume cannot move data centers.
- **`Unhealthy`:** the server in the image did not start. Read the worker's logs.
- **A `401` in the worker's logs, or every job failing at once:** the key was revoked or lost its permissions. See
  [Changing the key](#changing-the-key).

The server's own record is on the AWS side: `sudo k3s kubectl logs -n flintgraph deploy/studio-workers`.

## Checking it directly

`deploy/runpod/smoke.py` calls an endpoint as the workers do, and prints how long each part took. It costs a few
cents, and takes the key in `GPU_TOKEN`.

```bash
uv run python deploy/runpod/smoke.py zxfk4sx2prley7 images --seeds 2 --hires --out /tmp/out
uv run python deploy/runpod/smoke.py zxfk4sx2prley7 voices --out /tmp/out
uv run python deploy/runpod/smoke.py afs9c0epe9ynoz assistant
```

Run a call twice within a minute to see a warm one beside the cold one.

## Changing what the workers run

The image names a commit. Run **Deploy Runpod images** in GitHub Actions, which takes about 15 minutes, and change
the endpoint's image to the new commit. In-flight workers keep the old version until they stop.

Do this when `deploy/runpod/`, `runtimes/imagegen` or `runtimes/voicegen` changes. A change to the protocol between
the stand-in and the server must go out on both sides together.

## Changing the key

1. In the console, under **Settings → API Keys**, create a **Restricted** key: **Read/Write** on the two endpoints and
   **None** on everything else. An endpoint added later needs adding here.
2. Store it as the SecureString `/flintgraph/app/FLINT_GRAPH_NARRATIVE_REMOTE_GPU_TOKEN` in Parameter Store. Never paste
   it into a chat or a command line that is saved.
3. Follow **Changing a secret** in [Deploying to AWS](aws-deployment.md#everyday).
4. Revoke the old key.

## Putting the models back

If the volume is new, create the two temporary CPU pods below in its data center, mounting it at `/runpod-volume`. A
`cpu3c` with 2 vCPUs costs $0.06 an hour, and each takes a few minutes. **A pod restarts its container when it exits, and
goes on billing until deleted,** so delete each one when its log shows the last line.

| Image | Command | Last line |
| --- | --- | --- |
| `flint-graph-runpod-assistant` | `--pull <assistant model> <vision model>`, from `deploy/k8s/base/config.env` | `PULLED` |
| `flint-graph-runpod-generation` | `/app/runtimes/imagegen/.venv/bin/python /app/fetch_weights.py` | `FETCHED` |

`fetch_weights.py` checks each manifest against its pin in `deploy/ansible/vars/models.yml`. If it says a model does not
match its pin, it stops there, and the container restarts and says so again. A pin must hash the manifest exactly as
`tools/narrative/fetch_model.py` writes it, with LF line endings: `test_a_fresh_download_on_any_machine_reproduces_the_pins`
holds that.

Images built before that fix hold the older pins, so use an image from `deploy-runpod-images.yml` at a later commit.

## Taking it down

Delete the two endpoints, then the volume, which is what goes on billing. Then set the assistant and generating off in
`deploy/k8s/base/config.env` and remove `studio-workers`, because a job with no worker takes credits and never runs.
