# The models on Runpod

[ADR 0078](../adr/0078-models-on-runpod-by-the-second.md) moved every model to two Runpod endpoints that scale to zero, and
[ADR 0079](../adr/0079-a-character-needs-an-approved-image.md) (prompt v15) added two rules from the owner. This report is what
I ran against the live site, what it cost, and what it does not show.

Everything below used the real site, a real browser (headless Edge), a real invitation key, Cognito sign-in and real Runpod
workers, as a throwaway invited person. Characters and stories were generated or written for the test.

## One whole run

| Time | Step | Result |
| --- | --- | --- |
| 28 s | Asked for a story about Hana, with nobody drawn yet | |
| 68 s | The assistant answered | Hana and a picture card, with no lines (rule 2) |
| 73 s to 253 s | Pressed Generate on the card (20 credits) | Four candidates |
| 255 s | Pressed **Use on stage** on the first | `hana` has the expression `default` (rule 1) |
| 263 s to 441 s | Asked again for the scene | 4 lines by Hana, on stage as `hana:default:right` |
| 445 s | Opened the playtest | **Failed:** see [the stalled playtest](#the-stalled-playtest) |
| 826 s to 983 s | Asked for a voice line | A card at 1 credit |
| 984 s to 1032 s | Pressed Generate | A clip in the chat |

The balance ended at 73 of 100 credits. The run took 17.2 minutes.

## Times

| What | Measured |
| --- | --- |
| Assistant, cold: worker's container running | 18 s |
| Assistant, cold: first words | 123.5 s |
| Assistant, warm | 64 tokens a second |
| A real assistant turn from cold | About 3.5 minutes |
| The same when no GPU was free | 424 s, past the 420 s deadline |
| Four high-resolution sprites | 168 s to 180 s |
| One voice line, directly / through the site | 21 s / 48 s |
| Describing a screenshot, cold | 98.6 s |
| A playtest with a real sprite | 15 s |

## What it cost

Runpod's billing for 2026-11-07, read at 20:01 UTC. That day held all the setup and every test here. No charges had arrived for
any hour after 17:00 to 18:00, and both endpoints showed no running workers and no jobs.

| Item | USD |
| --- | ---: |
| Serverless GPU, assistant `afs9c0epe9ynoz` | 0.5728 |
| Serverless GPU, generation `zxfk4sx2prley7` | 0.2641 |
| Serverless disk | 0.0037 |
| Pods that downloaded the weights, CPU | 0.1058 |
| Those pods' disk | 0.0049 |
| Volume | 0.0146 |
| **Total** | **0.9659** |

The GPU figures are 59.3 and 27.3 worker minutes at $0.58 an hour. Nearly all of the pods' cost was one download pod that
crash-looped, which should not recur.

**Billing lags.** A read at about 17:35 UTC showed a total of $0.6884, because that hour's charges had not all arrived. Read
it again later before trusting a figure for the last hour or two.

Worked from the run's log and that rate, the run above is 915 s of assistant worker and 348 s of generation worker, each
including its idle wait, so about **$0.20**. Billing does not split by run, but the 17:00 UTC hour held only that run and one
short assistant turn, which makes the calculation checkable:

| Worker | Calculated | Billed | Difference |
| --- | ---: | ---: | ---: |
| Assistant, with the extra turn | 1118 s | 1106 s | -1.1% |
| Generation | 348 s | 343 s | -1.4% |

`deploy/cost/estimate.py` prints the whole bill from it: $28.51 a month with nobody using the site, $30.55 at 10 visits, and
$69.21 at 200.

## The stalled playtest

One of the four playtests I ran before the fix failed with "The story player did not start". (The commit message says one in
five. It was one in four.) A person who had just accepted a scene waited 90 s to read that.

The playtest server's log shows why:

```text
17:11:42 /index.html  200 509
17:11:53 /index.pck   200 229524
17:12:53 /index.wasm  200 1190266     (a whole download is 10084297)
```

The player's download stopped at 1.19 MB, and nginx dropped it after about 60 s, the length of its default `send_timeout`. The
player only says it is ready once it has booted, so the dialog heard nothing.

**The cause of the stall is not known.** The dialog is ruled out. I first blamed its `onClose` changing on re-render and said so
at the time, which was wrong: it is already stable, and the effect only re-runs when the player becomes ready.

The evidence also points away from these, without excluding them:

- **An overloaded server.** Averaged over those five minutes, CPU was 12.7%, with 63.9 CPU credits, 87% of the disk's I/O balance
  and 99% of its byte balance. An average can hide a short stall on a server this short of memory, and the node did log slow
  housekeeping at 17:11:07 to 17:11:13, just before the download began.
- **The whole connection.** The same browser's API calls reached the server every 6 s throughout.
- **My other work.** The test was the only thing I had started on the laptop. I can't see what else it was doing.

That leaves a stall on the one connection to the playtest address. It did not happen again, so nothing here reproduces it.

**The fix** does not depend on the cause. A player that has not said it is ready after 90 s gets one fresh frame, and the status
says so. Only a second stall shows the error. It cannot lose the asset bytes, because they are only transferred after the
player says it is ready.

To prove it, I held the first `index.wasm` request open in a real browser on the live site:

```text
 34.2s  opened the playtest
 38.8s  index.wasm request 1: holding it, as a stalled connection would
127.2s  status: That took too long, so the story player is starting again…
128.1s  index.wasm request 2: letting it through
137.3s  status: Playing saved revision
```

The screenshot shows the sprite and the first line on stage. A held request stands in for the real stall, which I could not
cause on demand.

The fix has two limits. A person still waits 90 s before the restart, and a slow link that cannot finish about 10 MB and boot
in 90 s gets the restart too, then the error. Reporting download progress from the frame would solve both, but needs a protocol
change and a new playtest image, which one stall does not justify.

## Prompt v15

The live model ignored repair instructions three times running and wrote the scene beside the card, which ended in a proposal
nobody could accept. Telling it again was never going to work, so the server now keeps the character and card and sets the
scene aside (`_pictures_first`). The whole-run table above is that behaviour with the real model. This is one model on a few
requests, so it is evidence and not a measured rate.

## Problems the live site found

| What went wrong | Fix |
| --- | --- |
| Every job failed with `does not match its pin`: manifests were pinned with CRLF | LF everywhere, and a test that a fresh download reproduces the pins |
| Jobs failed with `model_invalid`: ConfigMap symlinks sent `/models/..2026_…/name` | One `subPath` per manifest, and a test that a model has the same path on both sides |
| The certificate would not issue after restarting Traefik | A temporary route on the running Traefik, in the runbook |
| Playtests said "Configure a trusted preview" | The playtest image and its address |
| A character had no expression, so did not appear on stage | Rule 1 of ADR 0079 |
| A duplicate `set_entry` from the model made a proposal invalid | The server drops the model's and writes one |

## What this does not show

- **Whether the output is good.** Nobody has listened to the voice clip, and nobody has judged the sprites beyond seeing one on
  stage.
- **Other people's connections.** Every run came from one laptop on one connection, through a headless browser.
- **A long wait for a GPU.** One turn ran past its deadline at 424 s. `EU-RO-1` is the only data center with the cheapest cards,
  so a turn can fail this way. I did not test how often.
- **An empty Runpod balance.** The runbook describes what should happen, and it has not been tried.
- **Releases, poses, cloned voices, music and training.** None of them run on this deployment.

## Commands

For the playtest fix and the estimate, which is the last change:

| Command | Result |
| --- | --- |
| `node --test tests/narrative-preview.test.mjs` (in `frontend`) | 7 passed; the new test failed first |
| `npx tsc --noEmit` (in `frontend`) | Passed |
| `uv run ruff check deploy/cost/estimate.py` | Passed |
| `uv run pytest -q tests/unit/test_deploy_manifests.py -k "estimate or daily_limit"` | 6 passed |
| GitHub Actions **CI** on `62ce095` | Passed, including the whole test suite |

I did not run the whole `uv run pytest`, `uv run mypy` or the eval gate on the laptop, so those results come from CI.
