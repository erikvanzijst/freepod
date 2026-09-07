## Context

See proposal.md — Why. The state that shapes the approach:

- `get_current_user` (`api/app/deps.py`) reads one header, `X-Auth-Request-Email`, lowercases
  it, selects the non-deleted `UserORM` whose lowercased email matches, and creates one when
  there is no match. Every authenticated endpoint funnels through it, and `get_optional_user`
  delegates to it.
- `UserORM` (`api/app/models/core.py`) carries `email` with a partial unique index
  (`uq_user_active`) over `lower(email)` where `deleted_at IS NULL`.
- The edge already produces what this change needs. oauth2-proxy's `--set-xauthrequest`
  emits `X-Auth-Request-User` populated from the `sub` claim (its `UserClaim` defaults to the
  `sub` constant), for cookie sessions and verified bearer tokens alike, and the Traefik
  forward-auth middleware in `tf/app/login/main.tf` already lists `X-Auth-Request-User` among
  the headers it copies from the auth response onto the upstream request — which also makes
  it a sanitizer for a client-supplied value.
- The realm's `master` → `freepod` migration reissued every subject once already. Whatever
  this change does must survive that happening again.

## Goals / Non-Goals

**Goals:**

- One user record per Keycloak identity, across an email change.
- No migration event: existing records bind themselves as their owners show up.
- No new edge configuration, and no new failure mode for the CLI or bearer-token path.

**Non-Goals:**

- Multiple email addresses per account. This change is what makes it expressible later;
  it does not add it, and no schema here anticipates its shape.
- Exposing the subject through the API. It is an internal join key; `/api/me`, the admin
  users panel and the CLI keep showing email.
- Reconciling the two accounts a past email change has already produced. If any exist, they
  are an operator's data-repair job, not this change's.
- Changing what the edge authenticates, which routes are public, or how authorization
  decisions are made once a caller has resolved.

## Decisions

### D1: The subject, not the username

Keycloak's `sub` is opaque, immutable for the life of the account, and never reissued
within a realm. The alternatives all move:

- **Username** — an administrator can change it at any time, and a realm configured to use
  the email address as the username changes it exactly when the email changes, which is the
  failure being fixed.
- **A Freepod-issued identifier stored as a user attribute** — needs a write path into
  Keycloak at registration, a protocol mapper to emit it, and it would still be missing for
  every account that predates it. Strictly more machinery for a weaker guarantee.

The subject is stored as an opaque string. It is a UUID in this deployment, but nothing may
depend on that: a client configured for pairwise subjects (see D5) or a future federated
identity provider produces other forms.

### D2: `X-Auth-Request-User`, not a new header

It already carries the subject and is already forwarded, so the change is zero Terraform.
The considered alternative, `X-Auth-Request-Preferred-Username`, would have required a
middleware change and carries a mutable value — D1 rules it out on the merits regardless.

Two configuration facts become load-bearing and are pinned in the spec rather than left as
incidental: the `--set-xauthrequest` flag, and the header's presence in the middleware's
`authResponseHeaders`. Both currently read as generic pass-through and would survive a
tidy-up otherwise.

### D3: Subject → adoptable email → create, and never email onto a bound record

The ladder is ordered so the strongest evidence wins and the weakest is available only when
there is nothing stronger to contradict it.

The rule that email never matches a record already carrying a subject is what keeps address
reuse from becoming account takeover. The realm forbids two accounts from holding one
address *simultaneously*, but not *sequentially*: a user can change their address away from
`x@example.com`, after which a different person can register it and verify it. If email
matched a bound record, that second person would land on the first person's account. With
the rule, they get a new one.

The residual exposure is a record that carries no subject: whoever holds its verified
address first will bind it. That is precisely the trust model in place today — the platform
already treats "controls the verified address" as "is that account" — so the change removes
this exposure per account, on first authentication, rather than introducing it. It is also
why the realm's `verifyEmail` is restated as a security control in the realm spec instead of
being relaxed now that it is no longer the join key.

### D4: Lazy adoption, no backfill

The alternative is a one-off sweep of the Keycloak admin API mapping email to subject. It
was rejected because it needs an admin credential on a migration path, it is a point-in-time
snapshot that is stale for anyone who registers between the sweep and the deploy, and the
lazy path has to exist anyway to serve those users. A sweep would be strictly additional
code guarding a strictly smaller window.

The cost of lazy adoption is a tail: a record whose owner never signs in again keeps a null
subject forever. That is harmless — such a record is also never resolved.

### D5: Pairwise subjects are the one way this silently breaks

A client with the pairwise subject identifier mapper (`oidc-sha256-pairwise-sub-mapper`)
issues a per-client subject. Freepod is reached through two clients per environment — the
oauth2-proxy session client and the public CLI client — so a pairwise subject on either
would give one person two subjects, and therefore two accounts, one for the browser and one
for the CLI. Nothing would error; the CLI would simply report that the user owns nothing.

The clients do not have that mapper today, and the realm spec now forbids adding it. This is
recorded as a requirement rather than a code check because there is nothing the API could
usefully do at runtime: two subjects for one person is indistinguishable from two people.

### D6: A missing subject resolves by email instead of failing closed

Three paths present an email and no subject: the local development UI, which sets the header
by hand (`ui/src/state/useAuthEmail.ts`); the API's own tests, whose fixtures build header
dicts; and any route matched by `skip_auth_routes`, where the edge injects nothing at all.

Failing closed would break the first two and protect nothing in the third — a skipped route
must not identify a caller from client-controlled headers whatever they contain, which the
existing skip-auth footgun note in `api/README.md` already governs. On an edge-authenticated
route the header is always present, so the tolerant branch is unreachable in production.

Consequently a subject-less request neither stamps a record nor clears an existing stamp: a
development or test session must not be able to bind a record to nothing, or unbind one.

### D7: The email column is updated in place

No history table and no second address column — both would be anticipating the multi-address
feature that is explicitly a non-goal, and would have to be redesigned when it arrives.

`uq_user_active` stays. It is not what makes adoption safe (the realm's verification is), but
it still keeps the subject-less path from producing two records for one address. It does
introduce one narrow failure: if record A holds `x@example.com` and its owner has since moved
to another address without signing in, and a different person now takes `x@example.com` and
authenticates first, updating A's email later collides. The right response is to fail the
request loudly rather than mutate or delete another account's row silently. It is rare
enough — it needs an address change, a re-registration, and an ordering — that a clear error
and a manual repair is the proportionate answer.

## Risks / Trade-offs

- **`--prefer-email-to-user` would silently turn the header into an email.** oauth2-proxy
  supports that flag; it is not set, and setting it would make every caller's "subject" their
  address, reintroducing the bug behind a header that still looks correct. → Do not set it;
  the spec pins the header's meaning, and the adoption path means the damage would be
  wrong-but-recoverable rather than data loss.
- **A realm replacement invalidates every stored subject at once.** → Covered explicitly in
  the spec: an operator clears the subject column and the population re-binds by adoption.
  This is the reason the adoption path is specified as permanent rather than transitional.
- **The email-update collision in D7.** → Fail the request with a clear error; repair by hand.
  Expected frequency at current scale is zero.
- **Test and dev fixtures exercise only the subject-less path.** If they are left alone, the
  new ladder ships with its main branch untested. → The task breakdown adds the subject to
  the shared fixtures and keeps explicit coverage of the subject-less path, so both branches
  are exercised.
- **Trade-off accepted:** a user who changes their email keeps their account, which also
  means an administrator who changes a user's email in Keycloak silently moves that Freepod
  account's address. That is the intended direction, but it makes the admin console a way to
  edit Freepod account data — worth knowing when granting realm admin.

## Migration Plan

1. Alembic migration adds the nullable subject column and its partial unique index
   (`deleted_at IS NULL`), mirroring `uq_user_active`. Additive; no table rewrite of
   consequence at current row counts.
2. Deploy the API. Every authenticated request from that point resolves by the ladder, and
   each pre-existing record is adopted on its owner's next request.
3. Verification: the count of non-deleted records with a null subject should fall toward the
   set of accounts that are simply inactive. Confirm one adoption end to end, and confirm a
   CLI (bearer-token) request adopts and resolves identically to a browser one.

**Rollback:** redeploy the previous image. The column is additive and nothing else reads it,
so records adopted in the meantime continue to resolve by email exactly as before. The
migration does not need to be reversed, and reversing it is safe if wanted.
