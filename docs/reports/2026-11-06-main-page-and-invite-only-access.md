# Main page, How it works and invite-only access (ADR 0058)

The user asked for a public main page and a "How it works" page ahead of an AWS
deployment. Only invited people may join, through a key or an email invitation, and
each person's generation is limited because GPU time costs money.

## What changed

- **Public pages.** `/` is a main page: a hero with a real playtest, six features, three
  Studio screenshots, and an invite-only call to action. `/how-it-works` covers six
  steps and an FAQ about joining, limits and ownership. `/join` handles joining.
  - All three need no sign-in. The Studio moved to `/studio` and is loaded as a
    separate chunk.
  - Screenshots come from earlier QA evidence and are converted to WebP (145 KB in
    total).
- **Router.** A dependency-free path router. Old `/?project=` links and OIDC callbacks
  still open the Studio. Sign-in now returns to the page that started it, and only to
  same-origin paths.
- **Invite-only access** behind `FLINT_GRAPH_ACCESS_MODE=invite`:
  - operators from `FLINT_GRAPH_ACCESS_ADMIN_EMAILS` (verified email) or the OIDC admin
    group;
  - hashed one-time-display keys (`FG-XXXX-XXXX-XXXX-XXXX`, 80 bits) with a use count
    and expiry;
  - email invitations matched to a verified address;
  - per-user grants that can be suspended;
  - one generic refusal for unknown, expired, revoked and used-up invitations.
  - Migration `0043_access_invitations`.
- **Per-user limits** for images, voice lines, assistant turns, release builds and
  trainings, over the last 24 hours and in total.
  - They are charged in the job's own transaction after its idempotency check:
    replays are free and refusals charge nothing.
  - The user's grant row is locked, so parallel requests cannot pass the last unit.
  - Every image path (portraits, sprites, expressions, backgrounds, CGs, looks, poses,
    repairs) goes through the shared `_queue_job`, so one charge covers them all.
- **Studio:** **Invitations** for operators (create, copy the key, link or message once,
  revoke, see people and their usage, suspend or resume) and **Usage** for invited
  users. A 403 `access-required` anywhere sends the user to Join.

## Verification

- **New tests:**
  - `tests/unit/test_access_keys.py` (4): keys, normalization, limits, messages, and
    operator rules including comma-separated settings;
  - `tests/integration/test_access_invitations_api.py` (4, SQLite): the gate, a key
    used once, email invitations needing a verified address, revoke/expiry/suspend,
    and charges with a free replay and a refused over-limit request;
  - `frontend/tests/site.test.mjs` (4): routes, safe return targets, usage rows,
    invitation states, the allowance form and messages.
- **Real PostgreSQL:** `alembic upgrade head` from empty to `0043` on a new QA
  database (`flint_access_qa`).
- **Browser QA:** run in the built-in browser against a QA API in invite mode
  (port 8121) and a Vite server (5185), from this branch:
  - main page, How it works, and a phone width with no horizontal overflow;
  - `/studio` without access redirected to Join;
  - a made-up key refused with the generic message;
  - the invitation link pre-filled the key, joining went straight into the Studio,
    and a workspace and project were created;
  - asking for 4 backgrounds against a 3-per-day key was refused with the
    remaining count;
  - Usage showed `0 of 3`, because refusals charge nothing;
  - as an operator, an email invitation was created through the form, and the
    invitation list and people's usage were shown.
- **Gates:** see the commit message for the exact commands and results.

## Limits and follow-ups

- The server sends no email yet: operators copy a ready message. Amazon SES would be
  the natural sender.
- Failed jobs are not refunded. Limits count admissions, not GPU seconds.
- The OIDC access token must carry `email`/`email_verified` for email invitations and
  operator emails. Cognito needs a pre-token-generation trigger for that (see the
  runbook).
- AWS Lambda has no GPU. Generation workers need GPU instances (for example
  on-demand or spot EC2 g5/g6 through ECS or AWS Batch, scaled to zero when idle) or
  a serverless GPU provider. The API, relay and assistant can run on small CPU
  hosts.
