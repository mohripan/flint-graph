# Run an invite-only Studio

[ADR 0058](../adr/0058-invite-only-access-and-usage-limits.md) adds public pages,
invitation keys, email invitations and per-user generation limits.
[ADR 0059](../adr/0059-credits-and-unlimited-access.md) adds credits: each person has a
balance that generation spends at a price per item, operators top it up, and an
invitation or person can be unlimited. Local development stays open unless you turn
this on.

## Pages

| Path | Who | What |
| --- | --- | --- |
| `/` | anyone | Main page |
| `/how-it-works` | anyone | How the Studio works, with a short FAQ |
| `/join` | signed in | Redeem a key or accept an email invitation; `?key=` pre-fills the key |
| `/studio` | joined | The Studio; old `/?project=…` links still open it |

Hosting must answer these paths with `index.html` (SPA fallback). With S3 and
CloudFront, map 403/404 to `/index.html` with status 200. The Vite dev server already
does this. The Studio is a separate JavaScript chunk, so the public pages stay light.

## Settings (API)

| Setting | Default | Notes |
| --- | --- | --- |
| `FLINT_GRAPH_ACCESS_MODE` | `open` | `invite` requires a redeemed invitation for every Studio API call |
| `FLINT_GRAPH_ACCESS_ADMIN_EMAILS` | empty | Comma-separated operator emails; in OIDC mode the token's `email_verified` must be true |
| `FLINT_GRAPH_OIDC_SYSTEM_ADMIN_GROUP` | none | Operators may come from this group claim (`FLINT_GRAPH_OIDC_GROUPS_CLAIM`) instead |
| `FLINT_GRAPH_ACCESS_DEFAULT_LIMITS` | see below | JSON: what a new invitation grants when the operator leaves the form as is |
| `FLINT_GRAPH_ACCESS_DEFAULT_CREDITS` | `100` | Credits a new invitation grants when the operator gives none |
| `FLINT_GRAPH_ACCESS_CREDIT_PRICES` | `{}` | JSON overrides of single prices, e.g. `{"image.pose": 10}`; unknown items stop the API from starting |
| `FLINT_GRAPH_PUBLIC_BASE_URL` | none | Makes invitation links absolute; the Invitations page uses the browser origin otherwise |

Default allowance per person (units in the last 24 hours / in total):

| Kind | Counts | Per 24 h | Total |
| --- | --- | --- | --- |
| `image` | each candidate: portraits, sprites, expressions, backgrounds, CGs, looks, poses, repairs | 40 | 300 |
| `voice` | each line spoken | 150 | 1000 |
| `assistant` | each assistant turn | 40 | 300 |
| `release` | each release build | 5 | 30 |
| `training` | each style or character adapter training | 1 | 4 |

A blank limit means no limit of that kind; `0` means the kind is not included.
These caps stay beside credits as rate limits: a request must fit both.

## Prices

Each admission costs the item's price times its quantity. The code table is in
`src/flint_graph/application/credit_prices.py`. Defaults:

| Kind | Item: credits |
| --- | --- |
| Images (each) | expression 1 · standard (portrait, background) 2 · transparent sprite 3 · high resolution 5 · event CG 6 · pose repair 6 · pose 8 |
| Voice lines (each) | Kokoro-82M 1 · Chatterbox-Turbo 2 · Chatterbox, Chatterbox Multilingual, Qwen3-TTS stock 3 · Qwen3-TTS cloning 4 · IndexTTS-2.5 5 |
| Assistant (each turn) | test model 1 · Ollama 2 · Anthropic 10 |
| Release build | 25 |
| Training (each 100 steps, rounded up) | project style 20 · character 25 · character with reference 30 |

Everyone signed in reads the live table, with overrides applied, from
`GET /v1/access/me` (`prices`, plus `assistant_item` for this server's provider).
The Studio shows a price beside every control that starts paid work, and the
person's balance in the header. A price change applies to new jobs only.

## Sign-in provider

Any OIDC provider works (Keycloak, Amazon Cognito, Auth0). The Studio sends the
**access token**, so it must carry what the server reads:
- `email` and `email_verified`, for email invitations and operators by email;
- the groups claim, if operators come from a group.

Keycloak adds these with protocol mappers. Cognito access tokens carry no email by
default: add it with a pre-token-generation trigger (V2), or use the group claim
for operators and keys for everyone else.

## Operating

1. Add your own email to `FLINT_GRAPH_ACCESS_ADMIN_EMAILS`, set
   `FLINT_GRAPH_ACCESS_MODE=invite`, apply migrations through `0044_access_credits`,
   and restart the API. Operators are unlimited: they spend no credits and have no
   caps.
2. In the Studio, open **Invitations** (operators only).
3. **Invitation key:** choose how many people may use it and when it expires, set its
   credits and caps, and create it.
   - **Unlimited** grants no credits and no caps. Use it for your own second
     account, or a trusted person. Keep it to one redemption and a short expiry,
     because anyone holding the key can generate without limit.
   - Copy the key or the ready message at once: the server keeps only a hash.
   - Anyone signed in may redeem it at `/join`.
4. **Email invitation:** enter the address. The person signs in with that verified
   address and accepts it on `/join`. Nothing is emailed by the server yet; copy the
   message and send it yourself.
5. **Revoke** stops a key or an email invitation from being used again. People who
   already joined keep access.
6. Under **People who joined**, see each person's usage, and **Suspend** or
   **Resume** them. A suspended person cannot redeem another key.
7. **Credits:** for each person, **Add**, **Remove** or **Set to** an amount, with an
   optional note. **Make unlimited** and **Turn off unlimited** keep the balance.
   **History** lists every change: joining, charges, and adjustments with the
   operator's email.
   - Removing more than the balance is refused; set it to 0 instead.
   - People who joined before credits show "no budget (caps only)": set a balance
     first.

Invited users see their balance, caps, prices and credit history under **Usage**.
- A request over a cap is refused with 429 `usage-limit`, saying how many are left.
- A request that costs more than the balance is refused with 402 `out-of-credits`,
  naming the action, its cost and the balance. `errors` carries `credits_needed`
  and `credits_left`.
- Nothing is charged for a refused or replayed request.
- Failed jobs are not refunded yet: top the person up instead.

## Checks

```powershell
uv run pytest tests/unit/test_access_keys.py tests/unit/test_access_credits.py tests/integration/test_access_invitations_api.py tests/integration/test_access_credits_api.py
npm --prefix frontend test
uv run alembic upgrade head --sql
```
