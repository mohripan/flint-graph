# Run an invite-only Studio

[ADR 0058](../adr/0058-invite-only-access-and-usage-limits.md) adds public pages,
invitation keys, email invitations and per-user generation limits. Local
development stays open unless you turn this on.

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
   `FLINT_GRAPH_ACCESS_MODE=invite`, apply migration `0043_access_invitations`, and
   restart the API.
2. In the Studio, open **Invitations** (operators only).
3. **Invitation key:** choose how many people may use it and when it expires, adjust
   the allowance, and create it.
   - Copy the key or the ready message at once: the server keeps only a hash.
   - Anyone signed in may redeem it at `/join`.
4. **Email invitation:** enter the address. The person signs in with that verified
   address and accepts it on `/join`. Nothing is emailed by the server yet; copy the
   message and send it yourself.
5. **Revoke** stops a key or an email invitation from being used again. People who
   already joined keep access.
6. Under **People who joined**, see each person's usage, and **Suspend** or
   **Resume** them. A suspended person cannot redeem another key.

Invited users see their allowance under **Usage**. A request over a limit is refused
with 429 `usage-limit`, saying how many are left. Nothing is charged for a
refused or replayed request. Failed jobs are not refunded yet.

## Checks

```powershell
uv run pytest tests/unit/test_access_keys.py tests/integration/test_access_invitations_api.py
npm --prefix frontend test
uv run alembic upgrade head --sql
```
