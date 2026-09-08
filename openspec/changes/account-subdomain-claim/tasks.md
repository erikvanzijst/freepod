## 1. Schema

> Implemented ahead of this change by `per-user-tls-certificates`, which needs the column
> to have a name to issue a certificate for. 1.1 and 1.2 are done there; confirm rather
> than rebuild them.

- [x] 1.1 Confirm the nullable `subdomain` column on `UserORM` (`api/app/models/core.py`) and its partial unique index over `lower(subdomain)` where `deleted_at IS NULL`, and verify a second non-deleted row with the same label — in any case — is refused by the database.
- [x] 1.2 Confirm the Alembic migration, and verify `uv run alembic upgrade head` then `downgrade -1` runs clean against the test database.
- [x] 1.3 Verify a deleted user's row keeps its subdomain and that the label stays unclaimable, by attempting a claim for a soft-deleted account's label.

## 2. Claim service and API

- [x] 2.1 Add the candidate format check (single lowercase DNS label, no dots, 2–63 characters) in `api/app/services/users.py`, and verify a dotted value, a leading/trailing hyphen, a single character and a 64-character label are each refused.
- [x] 2.2 Refuse a candidate whose `<label>.<wildcard domain>` appears in `reserved_hostnames`, and verify adding a hostname to that one list immediately makes its label unclaimable with no second list touched.
- [x] 2.3 Implement `POST /api/me/subdomain`, normalizing to lowercase, and verify a first claim stores it and a second claim — including one submitting the identical label — returns **409** with the held value unchanged.
- [x] 2.4 Implement `GET /api/me/subdomain` reporting the held label and `<label>.<settings.domain>`, and verify an account holding none gets a **200** naming that absence rather than a 404.
- [x] 2.5 Verify no endpoint, CLI command or admin panel action changes, clears or transfers a subdomain, by reviewing the route table and the admin users panel.

## 3. The hostname namespace splits by depth

- [x] 3.1 Invert `_check_wildcard_depth` (`api/app/services/hostnames.py`) to require exactly two labels beneath a configured wildcard domain, retire the `nested_subdomain` reason, and verify a one-label, three-label and bare-domain name are each refused as `invalid` while `photos.alice.freepod.eu` passes.
- [x] 3.2 Add the subdomain validation path — a single label under a wildcard domain checked against `reserved_hostnames` and the accounts that hold labels, never against the deployments table — raising `claimed` for a held label, and verify a soft-deleted account's label still refuses.
- [x] 3.3 Require authentication on `GET /api/hostnames/{fqdn}`, dispatch it by depth, and refuse a deployment hostname beneath another account's subdomain with `claimed`; verify an anonymous request is refused and that the caller's own namespace still answers normally.
- [x] 3.4 Remove `GET=^/api/hostnames/[^/]+/?$` from `skip_auth_routes` in `tf/app/login/main.tf`, and verify `/api/cname-target` remains public.
- [x] 3.5 Delete `GET /api/domains` and its `skip_auth_routes` entry, and verify `settings.wildcard_domains` still drives the depth rule and that `GET /api/cname-target` is untouched.

## 4. Deployment preconditions

- [ ] 4.1 Require a claimed subdomain in `create_deployment` (`api/app/services/deployments.py`), beside the ToS check, raising with code `subdomain_required`, and verify a create for an account holding none is refused with **400** and creates nothing.
- [ ] 4.2 Verify the refusal distinguishes itself from the ToS refusal by its code for a user who has settled neither, and that updating an existing deployment does not apply the check.
- [ ] 4.3 Enforce that a hostname under a configured wildcard domain sits beneath the owning user's own subdomain, and verify a create naming another account's subdomain is refused, that the owner's own passes, and that a custom domain is unaffected.

## 5. Web UI — the claim dialog

- [ ] 5.1 Build the address widget — reel, editable label, static domain suffix, status adornment — and verify it renders the full hostname with only the user's part editable. Reference: <https://claude.ai/code/artifact/359c879f-7851-47a2-b869-dc25448cc756>
- [ ] 5.2 Implement the reel: cubic ease-out over ~2.6s landing on the `your app` placeholder set in the UI face and italic, and verify it never comes to rest on a real name, that the last names before rest are readable, and that `prefers-reduced-motion` skips the animation entirely.
- [ ] 5.3 Wire live validation against the hostname checker with the same 400 ms debounce `HostnameField` uses, and verify `invalid`, `reserved` and `claimed` each render their own message and that the claim action is unavailable while checking or refused.
- [ ] 5.4 Re-run the reel once when a label is first reported available, and verify it does not fire on subsequent keystrokes, while the field has focus mid-edit, or under reduced motion.
- [ ] 5.5 Prefill from the email local part, selected for replacement, and verify an unavailable prefill renders in its refused state with no substitute chosen.
- [ ] 5.6 Add the confirmation state showing the fully qualified name with no application label, plus a way back that preserves the typed value, and verify claiming requires the second action and never a retype.
- [ ] 5.7 Add the first-run dashboard state and verify it is dismissible, leaves the dashboard usable, remains reachable, and that dismissal reaches neither the server nor browser storage — the invitation returns on reload.
- [ ] 5.8 Route the deploy action through the claim dialog for an account holding none, and verify the deploy flow continues after a successful claim and that no partially filled deploy form is ever discarded to ask.
- [ ] 5.9 Add a read-only address panel to account settings showing the held address as a fact with no edit control, and verify a non-privileged user sees it.

## 6. Web UI — the deploy dialog

- [ ] 6.1 Replace `HostnameField`'s wildcard domain dropdown with the account's own address as a static suffix, read from `GET /api/me/subdomain`, and verify only the application label accepts input and that custom domain mode is unchanged.
- [ ] 6.2 Delete `listDomains` and the `wildcardDomains` prop, including the mode-splitting that matched a stored hostname against the domain list, and verify an existing Freepod-address deployment still opens in the right mode.
- [ ] 6.3 Retire the `nested_subdomain` message and cover `in_use` and `claimed`, and verify each reason the checker can now return renders its own text.

## 7. CLI

- [ ] 7.1 Check the account's subdomain in deploy preflight before packing, for creates only, and verify no archive and no build are produced when it is missing.
- [ ] 7.2 Write the refusal — cause, the platform origin, and that nothing was built — and verify it is distinguishable from the terms refusal and from an authentication failure, and that the platform's own `subdomain_required` code is recognized rather than its prose.
- [ ] 7.3 Verify login and every read-only command succeed for an account holding no subdomain, and that no command or flag claims one.
- [ ] 7.4 Complete a bare hostname in the project file under `<subdomain>.<domain>` rather than a platform wildcard domain, reading it from `GET /api/me/subdomain`, and verify a value already containing a dot is submitted unchanged.
- [ ] 7.5 Delete `ApiClient.domains` and `_domains`, and verify no command reads `GET /api/domains`.

## 8. Rollout and documentation

- [ ] 8.1 Assign subdomains to the accounts on dev and move their deployments' hostnames beneath them, and verify each deployment reconciles and serves on its new name.
- [ ] 8.2 Document the subdomain in `api/README.md` beside ToS acceptance as the second user-level precondition for deploying, and verify the described refusals match the implementation.
- [ ] 8.3 Verify the FastAPI public routes and oauth2-proxy's `skip_auth_routes` agree after the hostname check leaves both.
