## 1. Schema

> Implemented ahead of this change by `per-user-tls-certificates`, which needs the column
> to have a name to issue a certificate for. 1.1 and 1.2 are done there; confirm rather
> than rebuild them.

- [ ] 1.1 Add a nullable `subdomain` column to `UserORM` (`api/app/models/core.py`) with a partial unique index over `lower(subdomain)` where `deleted_at IS NULL`, mirroring `uq_user_active`, and verify a second non-deleted row with the same label — in any case — is refused by the database.
- [ ] 1.2 Write the Alembic migration and verify `uv run alembic upgrade head` then `downgrade -1` runs clean against the test database.
- [ ] 1.3 Verify a deleted user's row keeps its subdomain and that the label stays unclaimable, by attempting a claim for a soft-deleted account's label.

## 2. Claim service and API

- [ ] 2.1 Add the candidate format check (single lowercase DNS label, no dots, length bounded so `<app>.<label>.<domain>` stays under 253) in `api/app/services/users.py`, and verify a dotted value, a leading/trailing hyphen and an over-long label are each refused.
- [ ] 2.2 Refuse a candidate whose `<label>.<wildcard domain>` appears in `reserved_hostnames`, and verify adding a hostname to that one list immediately makes its label unclaimable with no second list touched.
- [ ] 2.3 Refuse a candidate whose `<label>.<wildcard domain>` is held by an active deployment, and verify a deleted deployment's label does not block a claim.
- [ ] 2.4 Implement `POST /api/me/subdomain`, normalizing to lowercase, and verify a first claim stores it and a second claim — including one submitting the identical label — returns **409** with the held value unchanged.
- [ ] 2.5 Implement `GET /api/me/subdomain` reporting the held label and the FQDN it forms, and verify an account holding none gets a **200** naming that absence rather than a 404.
- [ ] 2.6 Verify no endpoint, CLI command or admin panel action changes, clears or transfers a subdomain, by reviewing the route table and the admin users panel.

## 3. Hostname validation

- [ ] 3.1 Add the `claimed` check to `require_valid_hostname_for_deployment` between `reserved` and availability, and verify the ordering with a hostname that is both reserved and claimed (reports `reserved`) and one that is both claimed and in use (reports `claimed`).
- [ ] 3.2 Add `claimed` to the reason codes in `api/app/services/errors.py` and the `HostnameCheck` docstring in `api/app/api/hostnames.py`, and verify `GET /api/hostnames/{fqdn}` returns `usable=false, reason="claimed"` for a claimed label to an unauthenticated caller.
- [ ] 3.3 Verify the check does not apply outside the configured wildcard domains, using a custom-domain hostname whose first label is a claimed subdomain.

## 4. Deployment precondition

- [ ] 4.1 Require a claimed subdomain in `create_deployment` (`api/app/services/deployments.py`), beside the ToS check, and verify a create for an account holding none is refused with **400** and creates nothing.
- [ ] 4.2 Verify the refusal distinguishes itself from the ToS refusal for a user who has settled neither, and that updating an existing deployment does not apply the check.

## 5. Web UI

- [ ] 5.1 Build the address widget — reel, editable label, static domain suffix, status adornment — and verify it renders the full hostname with only the user's part editable. Reference: <https://claude.ai/code/artifact/359c879f-7851-47a2-b869-dc25448cc756>
- [ ] 5.2 Implement the reel: cubic ease-out over ~2.6s landing on a non-name placeholder set in the UI face and italic, and verify it never comes to rest on a real name, that the last names before rest are readable, and that `prefers-reduced-motion` skips the animation entirely.
- [ ] 5.3 Wire live validation against the hostname checker with the same 400 ms debounce `HostnameField` uses, and verify each reason code renders its own message and that the claim action is unavailable while checking or refused.
- [ ] 5.4 Re-run the reel once when a label is first reported available, and verify it does not fire on subsequent keystrokes, while the field has focus mid-edit, or under reduced motion.
- [ ] 5.5 Prefill from the email local part, selected for replacement, and verify an unavailable prefill renders in its refused state with no substitute chosen.
- [ ] 5.6 Add the confirmation state showing the fully qualified name with no application label, plus a way back that preserves the typed value, and verify claiming requires the second action and never a retype.
- [ ] 5.7 Add the first-run dashboard state and verify it is dismissible, leaves the dashboard usable, remains reachable, and records nothing on dismissal.
- [ ] 5.8 Route the deploy action through the claim dialog for an account holding none, and verify the deploy flow continues after a successful claim and that no partially filled deploy form is ever discarded to ask.
- [ ] 5.9 Show the held address in account settings as a fact with no edit control, and verify a non-privileged user sees it.

## 6. CLI

- [ ] 6.1 Check the account's subdomain in deploy preflight before packing, for creates only, and verify no archive and no build are produced when it is missing.
- [ ] 6.2 Write the refusal — cause, the web address, and that nothing was built — and verify it is distinguishable from the terms refusal and from an authentication failure.
- [ ] 6.3 Verify login and every read-only command succeed for an account holding no subdomain, and that no command or flag claims one.

## 7. Documentation

- [ ] 7.1 Document the subdomain in `api/README.md` beside ToS acceptance as the second user-level precondition for deploying, and verify the described refusals match the implementation.
- [ ] 7.2 Add the claim and availability routes to oauth2-proxy's `skip_auth_routes` in `tf/app/login/main.tf` if a new public path was introduced, and verify against the change's own rule that the two public lists agree.
