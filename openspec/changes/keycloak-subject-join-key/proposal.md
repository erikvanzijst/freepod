## Why

The API resolves an authenticated caller to a Freepod user record by lowercased email
(`get_current_user`, `api/app/deps.py`), creating a record when no row matches. Email
addresses are not stable: a user can change theirs in the Keycloak account console and an
administrator can change it for them. When that happens the lookup misses and a second,
empty account is created. The first account keeps the deployments, SSH keys, ToS
acceptance and subscription — including its Mollie customer — and the user has no way back
to it. Nothing warns anyone; the account simply appears to have been emptied.

Keycloak issues a stable, opaque subject identifier (`sub`) for exactly this purpose, and
the edge already forwards it: oauth2-proxy's `--set-xauthrequest` populates
`X-Auth-Request-User` from the `sub` claim, and the Traefik forward-auth middleware already
lists that header among the ones it copies onto the upstream request. The API discards it.

The same change is the precondition for ever holding more than one email address on an
account: while email *is* identity, a second address cannot exist; once the subject is
identity, email becomes an ordinary attribute of the record.

## What Changes

- **The Keycloak subject becomes the join key** between a Keycloak identity and a Freepod
  user record. Email becomes a mutable attribute of that record rather than its identity.
- **Users gain a subject column**, nullable, unique among non-deleted rows — mirroring the
  partial unique index the email column already carries.
- **Resolution becomes: subject match, then email match, then create.** An email match on a
  record that carries no subject *adopts* it, stamping the subject onto the record; an
  email match never adopts a record that already carries a different subject.
- **An email change no longer creates a second account.** A request whose subject matches an
  existing record updates that record's email in place.
- **Existing accounts adopt lazily**, on their next authenticated request. No admin-API
  sweep, no backfill script, no downtime, and nothing to run in a maintenance window.
- **The email fallback is permanent, not transitional.** Subjects are realm-scoped, so
  rebuilding or replacing a realm reissues every one of them — as the `master` → `freepod`
  migration already did once. Removing the fallback would orphan every account the next
  time that happens.
- **A missing subject header is tolerated**, resolving by email without stamping, so that
  local development and tests are unaffected.
- **The realm's clients must issue a public (non-pairwise) subject.** A pairwise subject is
  per-client, which would split one person across the browser and CLI clients into separate
  Freepod accounts.
- No Terraform change is required at the edge: the header is already forwarded. The
  specification is being brought up to what the deployment already does, and pinned so it
  cannot be removed as dead configuration.

## Capabilities

### New Capabilities

- `caller-identity-resolution`: How an authenticated request resolves to a Freepod user
  record — the subject as join key, adoption of pre-existing records by verified email,
  in-place email updates, record creation, and the behavior when no subject is presented.

### Modified Capabilities

- `auth-header-integration`: adds the requirement that the edge forwards the Keycloak
  subject as `X-Auth-Request-User`, that its value is edge-determined rather than
  client-supplied, and that it is absent from routes the edge skips.
- `keycloak-user-realm`: the realm capability currently asserts that the email claim is the
  sole join key and that no Keycloak subject identifier is persisted. Both statements
  change. Email verification remains a security control, for a narrower reason: it is what
  makes adoption by email safe. Adds the public-subject-type requirement.

## Impact

- `api/app/models/core.py`: new nullable column on `UserORM` plus a partial unique index
  alongside `uq_user_active`; one Alembic migration in `api/alembic/`.
- `api/app/deps.py`: `get_current_user` reads a second header and gains the resolution
  ladder; `get_optional_user` follows it unchanged.
- `api/tests/conftest.py` and the per-module header fixtures: authenticated test requests
  currently carry only `X-Auth-Request-Email`.
- `ui/src/state/useAuthEmail.ts`: sets the identity header by hand in local development.
- `api/README.md`: the Authentication section states that the caller is resolved by
  `lower(email)` and that no Keycloak identifier is stored.
- `tf/deps/keycloak-config/clients.tf`: asserted, not necessarily changed — the clients must
  use the public subject type.
- `tf/app/login/main.tf`: unchanged. `X-Auth-Request-User` is already in the forward-auth
  middleware's response-header list.
- Not affected: the bearer-token path needs no client change. oauth2-proxy builds a session
  from the token's claims and emits the same header, so the CLI behaves like a browser.
