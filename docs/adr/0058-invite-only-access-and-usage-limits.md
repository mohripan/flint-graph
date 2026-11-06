# ADR 0058: Invite-only access, invitation keys and per-user usage limits

Status: accepted (2026-11-06)

## Context

The Studio is about to be deployed for people outside this machine: a public main
page, a "How it works" page, and a way for invited people to join. Generation is the
expensive part (GPU time for images, poses, voices and training, model time for the
assistant), so the operator must decide who gets in and how much each person can
generate.

The operator often does not know a visitor's address: a company contact may reply
from a shared company mailbox. So an invitation must work both as a bearer **key**
the operator hands over, and as an **email invitation** bound to one address.

Sign-in itself stays with the existing OIDC provider (ADR on the M12 access boundary).
Any OIDC provider that issues verifiable tokens works, including Amazon Cognito.

## Decision

1. **Access mode.** `FLINT_GRAPH_ACCESS_MODE` is `open` (default; every signed-in user
   may use the Studio, as before) or `invite`.
   - In `invite` mode every API dependency that needs the current user also requires
     an active **access grant**, or **operator** rights, or it answers 403
     `access-required`.
   - Only `/v1/access/*` (status and joining) and `/v1/admin/access/*` (operators) are
     reachable without a grant.
   - Health checks and the public pages need no sign-in.
2. **Operators** are configured, never self-assigned: `FLINT_GRAPH_ACCESS_ADMIN_EMAILS`
   (comma-separated), or membership in `FLINT_GRAPH_OIDC_SYSTEM_ADMIN_GROUP`.
   - In OIDC mode the email must be verified (`email_verified` claim).
   - Operators always have access, have no usage limits, and manage invitations and
     grants.
3. **Invitations** (`access_invitations`) are created by an operator with a label,
   optional expiry and the usage limits they grant.
   - **Key:** a random `FG-XXXX-XXXX-XXXX-XXXX` code (80 bits) shown once.
     - Only its SHA-256 (over the normalized code) and the last four characters are
       stored.
     - It allows a fixed number of redemptions (default 1).
     - Anyone signed in may redeem it.
   - **Email:** bound to one lower-cased address and redeemable once, by a user whose
     verified email matches. A link is produced for the operator to send; the server
     sends no mail itself yet.
   - Revoking stops further redemptions. Expired, revoked or used-up invitations are
     refused with one generic message, so keys cannot be probed.
4. **Joining** (`POST /v1/access/join`) creates the user's single grant
   (`access_grants`) with a copy of the invitation's limits. With no key, it uses an
   email invitation addressed to the user. Redemption locks the invitation row, so
   concurrent joins cannot exceed its count. A user who already has access keeps their
   grant. An operator can suspend and resume a grant.
5. **Usage limits** are counted per user, never per workspace, so creating more
   workspaces gives no more generation.
   - Each grant has, per kind, an optional limit for the last 24 hours and an optional
     lifetime total. The kinds:
     - `image`: candidates from portrait, sprite, expression, background, CG, look,
       pose and repair jobs;
     - `voice`: lines spoken;
     - `assistant`: turns;
     - `release`: release builds;
     - `training`: adapter trainings.
   - Admission charges a `usage_charges` row in the same transaction as the job, after
     the idempotency check, so a replayed request is free and a refused one charges
     nothing. The user's grant row is locked while checking, so two parallel requests
     cannot both pass the last unit.
   - Over a limit answers 429 `usage-limit`, naming the kind and the reset.
   - Failed jobs are not refunded in this slice; limits are set with room for retries.
   - Users without a grant (open mode, operators) are not charged.
6. **Public pages.** The frontend serves `/` (main page), `/how-it-works` and `/join`
   without signing in, and the Studio at `/studio`. Old links with `?project=` at `/`
   still open the Studio. Joining asks for sign-in, then a key; an email invitation is
   detected without one.

## Consequences

- An open-mode deployment behaves exactly as before; nothing changes locally unless
  the mode is set.
- Hosting must serve `index.html` for `/how-it-works`, `/join` and `/studio`: an SPA
  fallback, for example a CloudFront custom error response.
- Keys are bearer secrets: anyone holding an unused key can join. Keep the
  redemption count low and revoke leaked keys.
- Limits cap admissions, not GPU seconds. A slow job costs one admission like a fast
  one.
- Sending invitation email (for example through Amazon SES), refunds for failed jobs,
  per-workspace budgets and billing are follow-ups.
