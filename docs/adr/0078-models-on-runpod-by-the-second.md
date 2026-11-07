# ADR 0078: Models on Runpod, by the second

- Status: accepted, 2026-11-07. Replaces the GPU server of [ADR 0077](0077-one-small-server-and-one-sleeping-gpu.md) for this deployment.
- Date: 2026-11-07
- Builds on: [ADR 0039](0039-local-gpu-image-generation-in-an-isolated-child.md) (the isolated child and its trusted parent), [ADR 0070](0070-a-gpu-that-sleeps.md)

## Context

The site runs on one `t3.small`, with no GPU. AWS declined the GPU quota and the owner does not want to
appeal. A person uses the Studio for about 15 minutes, one or two people a month, so a GPU that is billed
only while a model is running suits this far better than any machine that has to be started and stopped.

Modal was tried first and fits well: lazy image loading and a free monthly credit. It would not accept the
owner's card, which left $1. Runpod took the deposit.

## Decision

Two Runpod Serverless **load-balancing** endpoints, which scale to zero, in one data center.

| Endpoint | Image | Runs | Idle before it stops |
| --- | --- | --- | --- |
| `flintgraph-generation` | `flint-graph-runpod-generation` | The same `runtimes/imagegen` and `runtimes/voicegen` children, from the same locks | 60 s |
| `flintgraph-assistant` | `flint-graph-runpod-assistant` | Ollama, with the same models | 180 s, because the next message usually comes within minutes |

Both may use one worker, at most, on the `AMPERE_16` pool ($0.58 an hour) or `AMPERE_24` ($0.75), with
FlashBoot on. Weights and Ollama's models are on one network volume mounted at `/runpod-volume`. The owner's
prepaid balance is the spending limit, with auto-pay off.

**The trusted parent does not change.** `LocalImageGenerator` and `LocalVoiceGenerator` start
`narrative_remote_child.py` under `python -I` instead of `generate.py`, with one JSON request on stdin, and
read the same JSON lines and files. So all their checks on events, sizes and hashes stay, wherever the work
ran. The worker pod holds only the pinned manifests, at the paths the weights have on Runpod, so model
identity is still checked against its pin.

**A job is not one request.** Runpod ends a request after 5.5 minutes and refuses a body over 30 MB, and
something on the way can drop one that stays silent for about 100 seconds. A job holds at most four images,
which measured about 3 minutes from cold, so it would normally fit, but a slower card or a worker that is
still busy need not. So the stand-in chooses the job's identity, starts it with `POST /images/jobs/<id>`, and
collects frames with `GET /images/jobs/<id>?after=<n>`, no request waiting more than 20 seconds. Repeating a
start is safe. Frames stay on the worker until the next request confirms them, so a reply lost on the way can
be asked for again. A reply holds at most 20 MB.

**Waiting is expected.** While a worker starts, Runpod answers with an error and expects a retry. The stand-in
retries a start for 10 minutes, since a new machine may first have to pull the image, and a collect for 2. It
does not wait on 401, 403 or 404: a 404 means a new worker that knows nothing of the job.

**Nobody collecting stops the job.** If nothing asks for 2 minutes, the worker that asked has gone, so the
server kills the child rather than keep a paid GPU busy.

**The assistant's reply starts at once.** A request that says nothing for about 100 seconds can be dropped on
the way, and loading a model takes about that long. So `assistant.py` sends blank lines until Ollama speaks.
Readers skip blank lines and JSON allows them before a document. An upstream error therefore arrives as a body,
not a status, so any error status the client sees came from the way there, and it retries those except 401, 403
and 404.

**Authentication happens at Runpod's edge.** A request without a valid key is refused before it reaches a
worker, so the workers check nothing. The server holds one key, restricted to these two endpoints, as
`FLINT_GRAPH_NARRATIVE_REMOTE_GPU_TOKEN` in Parameter Store. It reaches the stand-in in its environment, never
its arguments, and neither it nor the address reaches a log.

**One worker process on the server.** The three workers only wait on the network, so they share
`narrative_studio_workers`, which saves about 200 MB on a 2 GB server.

**Voices run on the CPU of the generation worker,** so a picture and a voice line can run together.

## Why not

- **A queue endpoint.** It waits for a worker by itself, but its request limit is 10 MB, and two reference images
  in one request can exceed that.
- **Weights in the image.** Faster to load, but a very large image takes much longer to pull onto a new machine,
  and the repository would then be redistributing them.
- **A warm worker.** No cold start, and about $423 a month on the cheapest pool.
- **Keeping the AWS GPU manifests deployed.** They are kept, unused, in `deploy/k8s/aws-gpu`, and still tested.

## Consequences

- A volume lives in one data center, so a worker can only start there. At creation, `EU-RO-1` was the only place
  with the cheapest cards, and its stock was reported as low. If no card is free, the request waits and may fail
  the job. Failed jobs are not refunded ([ADR 0059](0059-credits-and-unlimited-access.md)), so a person loses those
  credits until an operator tops them up by hand.
- The balance can reach zero. Workers then stop, and Runpod may eventually delete the volume. That costs a
  download, not any project: projects, approved images and voices are on the AWS server.
- Runpod stores what a job sends only while it runs, but prompts and reference images do leave AWS for Europe.
- Other models (poses, cloned voices, music, training) are not offered in this deployment, because no worker runs them.
