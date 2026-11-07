# The AWS deployment

[ADR 0077](../adr/0077-one-small-server-and-one-sleeping-gpu.md), [runbook](../runbooks/aws-deployment.md).

**The always-on server is live**: `54.253.96.189`, at `https://54-253-96-189.sslip.io`, with a real certificate and working sign-in. **There is no GPU server**:
AWS declined the quota on 2026-11-07, and the owner chose not to appeal. People can see the site, sign in and edit by hand. The assistant and generating are switched off.

## What it costs

From `deploy/cost/estimate.py`, using Sydney list prices fetched on 2026-11-07 into `deploy/cost/prices.json`, before tax. The project has $120 of credits.

| Item | USD/month |
| --- | ---: |
| t3.small always on | 19.27 |
| Its public IP address | 3.65 |
| Its disks (20 GB system + 20 GB data) | 3.84 |
| **Now** | **26.76** |
| GPU server's disk while stopped (70 GB), once it exists | 6.72 |
| **With the GPU server, nobody using it** | **33.48** |

Credits last about 4.5 months as it is now, or 3.6 with the GPU server. There are no backups, by the owner's choice. Sign-in is free for up to 10,000 people a month. GitHub's registry is free
for this public repository. The GPU costs $0.69 an hour while running, about $0.26 for a visit: 15 minutes of use, the 5-minute idle wait and an estimated 3-minute boot.

**What else was priced:**

| Always-on server | Nobody | 10 visits | 50 visits | Why it is not the one running |
| --- | ---: | ---: | ---: | --- |
| t3.small, running | 33.48 | 36.12 | 46.69 | |
| t3a.small | 31.58 | 34.23 | 44.79 | The Free Plan refuses it. An option after the upgrade, for $1.90 a month less |
| Lightsail 2 GB | 18.72 | 21.36 | 31.93 | Refused: `your account can not create an instance using this Lightsail plan size` |
| t3a.medium Spot and g4dn Spot | 27.93 | 29.12 | 33.86 | Refused on the Free and Paid Plans alike. Unlocking it is irreversible and removes the spend limit |

**Other Regions would not help.** `RegionFloor` in AWS's managed policy locks the project to Sydney, and only the same irreversible unlock changes that. Sydney was also among the cheapest in Asia for
this: g4dn is $0.684 an hour there, $0.71 in Tokyo and Osaka, $0.736 in Singapore and $0.647 in Seoul. AWS's China Regions are a separate service altogether.

## What the running server measures

| | |
| --- | --- |
| Memory at rest, with the dispatcher still on | 1,520 MB used of 1,905, plus 385 MB in swap, with 395 MB available |
| Memory with it off, just after the final rollout | 1,429 MB used, plus 435 MB in swap, with 488 MB available |
| CPU at rest | about 8%, under the 20% baseline, so credits slowly build. They start at 0 on this type |
| Disk | 10 GB of 19 on the system disk, 69 MB of 20 on the data disk |
| Reboot | Main page and API back by themselves about 3.5 minutes later, with the data disk and swap in place |
| Main page in a browser, from Indonesia | 3.5 seconds before compression. Each connection takes about 0.35 s to Sydney. The main script is now 91 KB instead of 264 KB |

It is tight, as expected. It holds at rest with no visitors. Nobody has used the Studio on it for real yet, so how it feels under one person editing is unknown. One early run took over 40 seconds to load
the main page, while pods were still settling. It did not recur, and the reason was not established.

## What was exercised for real

| Claim | Evidence |
| --- | --- |
| CDK creates it | `cdk bootstrap` and `cdk deploy FlintGraphFoundation`, after reading each diff |
| Ansible sets it up | `ansible-pull` on first boot: 30 tasks, none failed |
| Flux deploys it | Fetched `master`, applied revision `8d1610d`, `Ready` |
| Images can be pulled | Built by GitHub Actions, anonymous pull works |
| A real certificate | Traefik obtained one from Let's Encrypt without an email address, and `curl` trusts it |
| Migrations run | All of them, to `0058`, on real PostgreSQL |
| HTTP redirects | 301 to HTTPS |
| Only the right things are public | Unsigned `/v1` is 401. `/health/ready` and `/docs` get the page |
| **Sign-in works** | A real browser with a throwaway account (since deleted): auth code with PKCE S256, Cognito's page, back to the site |
| **The API trusts real tokens** | `/v1/access/me` is 200 with the real ID token |
| **The invitation gate works** | That account got `has_access=false`, and `/studio` sent it to `/join` |

The local run before that, on k3s of the same version, also proved: no TLS redirect loop; a client cannot forge its address; data survives every pod being replaced; only pods with the controller's label reach the
instance role; GPU pods land only on the GPU server; and stopping a GPU server for 6 min 41 s leaves its pods in place, while a control with the default limit was evicted at about 6 min 19 s, and they return 5 s after the node starts.

### Problems found

Each would otherwise have shown up on a billed server or a billed hour, and each now has a test where a test can hold it.

1. **MinIO could not be pulled.** The pin worked only from this machine's cache: `minio/minio` is gone from Docker Hub, and Quay refuses too. Now Chainguard's build. **`compose.yaml` and `ops/langfuse/compose.yml` still
   name the old image, so they fail on a machine without a cached copy.** That was left alone as a separate problem.
2. **Every application pod failed** with `CreateContainerConfigError`, because the images named their user, which `runAsNonRoot` cannot verify.
3. **A 606 MB image came out at 9.5 GB,** because `.dockerignore` only matched `.venv` at the top level.
4. **List settings crashed the application** as bare URLs, including in `.env.production.example`. They must be JSON.
5. **HTTP gave a 404,** because the Traefik chart silently ignored a setting name that had changed.
6. **A failed k3s download could go unnoticed** with `curl | sh`.
7. **The GPU image was 24.1 GB,** because both runtimes carry the same 7 GB of PyTorch. Hard links keep one copy: 13 GB to store and 4.5 GB to download.
8. **Any code change would have re-downloaded all of that** on a machine billed by the hour. The runtimes are now their own layer, built from their locks alone. Its saving has not been measured.
9. **PostgreSQL crashed on the real server,** because its folder was root's with mode 0700, and its image works as uid 70. The local run missed it because its folders were open to everyone.
10. **Cognito's sign-out had no endpoint to call,** and its access token no audience or email. See ADR 0077.

## What has not been exercised

- **Anything on the GPU:** the driver install, k3s picking up the `nvidia` runtime, pods seeing the GPU, a T4 running these models, and WireGuard between real servers. Without the toolkit a pod reports
  `FailedCreatePodSandBox ... unable to get OCI runtime`, which is what to look for.
- **The controller against real EC2,** as ADR 0070 already says. It has only run against a fake.
- **A person using the Studio on the server,** and an operator signing in with a real address.
- **Image or voice generation inside the GPU image.** Its imports and CUDA were checked on the laptop's GPU, in an earlier layout. Its final two-layer form did build on GitHub's runner.

## Not built

- **Playtests:** `serve_preview.py` refuses anything but a `localhost` parent on `127.0.0.1`, deliberately. The Play button will not work until it has a production mode on its own hostname.
- **Release builds:** `narrative_worker` runs `docker`, and k3s has only containerd.
- **Poses, training and music** on the deployed GPU. Poses and training also refuse a T4.

## Checks run

Passed: `uv run pytest tests/unit/test_deploy_manifests.py`, `uv run --frozen pytest` in `deploy/cdk`, `node --test tests/oidc-tokens.test.mjs`, `npx tsc --noEmit`, `uv run ruff check .`, `cdk synth --strict`, and CI on GitHub, which runs the full test suite, for each push reported here.
