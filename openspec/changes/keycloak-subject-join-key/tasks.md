## 1. Schema

- [x] 1.1 Add a nullable `keycloak_subject` column to `UserORM` (`api/app/models/core.py`) and verify it is absent from `UserCreate` and `UserRead`, so the join key is not settable or readable through the API.
- [x] 1.2 Add a partial unique index on `keycloak_subject` where `deleted_at IS NULL`, mirroring `uq_user_active`, and verify a second non-deleted row with the same subject is refused by the database.
- [x] 1.3 Write the Alembic migration for both and verify `uv run alembic upgrade head` followed by `downgrade -1` runs clean against the test database.

## 2. Resolution

- [x] 2.1 Read `X-Auth-Request-User` in `get_current_user` (`api/app/deps.py`) alongside the email header, and verify an authenticated request with both headers still resolves exactly as before for a record that already carries that subject.
- [x] 2.2 Implement the ladder — subject match, then email match against a record carrying no subject, then create with both — and verify a record carrying a *different* subject is not matched by email: while it still holds the address, the request is refused (2.5) and no record is created or changed.
- [x] 2.3 Stamp the presented subject onto a record adopted by email, and verify the same caller then resolves to it after changing their email address.
- [x] 2.4 Update the stored email in place when a subject-matched record's email differs, and verify the record's deployments, SSH keys, ToS acceptance and subscription remain attached and no second record is created.
- [x] 2.5 Handle the `uq_user_active` collision from design.md D7, reached by creating a record or by updating one's email, by answering `409` with a clear error rather than mutating either row, and verify with tests that construct both states.
- [x] 2.6 Resolve a request that carries no subject by email alone, and verify it neither stamps a record that carries none nor overwrites one that does.
- [x] 2.7 Verify `get_optional_user` and the endpoints that depend on it (`GET /api/products`) behave identically for anonymous, subject-bearing and subject-less requests.

## 3. Test and development fixtures

- [x] 3.1 Add a subject to the shared authenticated-request fixtures in `api/tests/conftest.py` and the per-module header dicts that build their own, and verify `uv run --no-sync pytest` passes with the ladder's primary branch now exercised by default.
- [x] 3.2 Keep explicit coverage of the subject-less path (a fixture that sends only the email header) so both branches stay tested, and verify both appear in the authorization test module.
- [x] 3.3 Send a subject header from the local development UI (`ui/src/state/useAuthEmail.ts`) alongside the email it already sets, derived from that email so each typed address stays one account (the dev UI picks who you are; it has no email-change action), and verify re-entering an address presents the same subject and resolves to the same record.

## 4. Realm and edge assertions

- [x] 4.1 Confirm no client in the `freepod` realm carries the pairwise subject mapper (`oidc-sha256-pairwise-sub-mapper`) and verify by decoding an access token from the browser client and one from the CLI client for the same user, asserting the `sub` values match.
- [x] 4.2 Verify against a deployed environment that `X-Auth-Request-User` reaches the API on both a cookie-authenticated and a bearer-token request, and that a client-supplied `X-Auth-Request-User` is overwritten rather than passed through.
- [x] 4.3 Add a comment at the `X-Auth-Request-User` entry in the forward-auth middleware (`tf/app/login/main.tf`) recording that the API now resolves callers by it, so it is not removed as unused. No configuration change.

## 5. App sign-in

- [x] 5.1 Grant `SELECT (keycloak_subject)` on `"user"` to `caelus_app_auth` in `tf/app/caelus/app-auth-bootstrap.sql`, and verify the role can read it and still cannot read the user's other columns.
- [x] 5.2 Read the owner's subject alongside their email in the daemon's access-list load (`daemons/app-auth/store.go`), and match the owner in `admit` by subject when their record carries one, by `lower(email)` only when it does not (design.md D8). Verify with tests: a bound owner signing in with a changed email is admitted, another subject presenting the owner's email is refused, an unbound owner is admitted by email.
- [x] 5.3 Carry the owner's subject through the memstore test double and the verifier's cached list, and verify the broker, OIDC provider and verifier tests cover the bound-owner and foreign-subject cases.
- [x] 5.4 Update `daemons/app-auth/README.md` where it describes recognizing the owner, bump `daemons/VERSION`, and point `app_auth_image` in `tf/app/variables.tf` at the new version.

## 6. Documentation

- [x] 6.1 Update the Authentication section of `api/README.md`, which states that the caller is resolved by `lower(email)` and that no Keycloak identifier is stored, and verify the described ladder matches the implementation.
- [x] 6.2 Note in the same section that a subject-less request is a development and test path only, cross-referencing the existing skip-auth footgun warning.

## 7. Rollout

- [x] 7.1 Deploy and verify one account adopts end to end: a record with a null subject carries the caller's subject after their next authenticated request.
- [x] 7.2 Verify a CLI (bearer-token) request adopts and resolves identically to a browser request for the same user.
- [x] 7.3 Run the one-off, uncommitted backfill (design.md D4) against the environment, and confirm the only non-deleted records still carrying a null subject belong to people without a verified Keycloak account.
- [x] 7.4 Apply the bootstrap grants, then roll out the app-auth release, and verify on dev that a `listed` deployment's owner signs in to it and a non-listed account is refused.
