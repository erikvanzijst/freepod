## 1. Keycloak client

- [x] 1.1 Add `valid_post_logout_redirect_uris = ["https://login.${var.<env>_domain}/signed-out"]` to `freepod_apps_prod` and `freepod_apps_dev` in `tf/deps/keycloak-config/clients.tf`; verify `terraform plan` in `tf/deps` shows only those two in-place attribute changes
- [x] 1.2 Apply `tf/deps`, then verify with `curl -sD- -o/dev/null "https://keycloak.freepod.eu/realms/freepod/protocol/openid-connect/logout?client_id=freepod-apps-prod&post_logout_redirect_uri=https%3A%2F%2Flogin.freepod.eu%2Fsigned-out&state=x"` that it answers `302` to `https://login.freepod.eu/signed-out?state=x` (today: "Invalid redirect uri"), and the same for dev

## 2. Broker

- [x] 2.1 Add `endSessionURL(state, postLogoutRedirect)` to the `authenticator` interface; implement it on `oidcAuth` from the discovered `end_session_endpoint` with `client_id`, `post_logout_redirect_uri` and `state`; extend the stub provider in `oidc_test.go` to publish `end_session_endpoint`, and verify a test asserts the built URL's query
- [x] 2.2 Add `GET /logout`: validate `host`, run `eligible()` (error page, no redirect, no Keycloak call for an ineligible host), seal `{host, rd}` under purpose `"logout"` with a 10-minute TTL, redirect to the end-session URL with `post_logout_redirect_uri = loginURL + "/signed-out"`; verify broker tests for an eligible host, an arbitrary host, and a sanitized `rd`
- [x] 2.3 Add `GET /signed-out`: open `state` as `"logout"`, redirect absolutely to `https://<host><safeReturnPath(rd)>`, otherwise render a `done`-kind "You're signed out of Freepod" page without a link; verify tests for valid, missing, tampered, expired, and wrong-purpose (e.g. a sealed `flow`) state
- [x] 2.4 Verify `go test ./...` in `app-auth/` passes, including `preview_test.go` if it renders every page (add the signed-out page to it if so)

## 3. Verifier

- [x] 3.1 Change the `logout` case in `verify.go` to clear the session cookie and redirect to `loginURL + "/logout?" + {host, rd: safeReturnPath(rd)}`; update the existing "logout clears only the session and redirects absolutely" test in `verify_test.go` to assert the new absolute broker `Location`, the cleared cookie, and a sanitized `rd` for `//evil.example/`
- [x] 3.2 Verify `traefik_test.go` still passes (the logout response is a `302` with `Set-Cookie`, relayed through Traefik); add a logout case there if none exists
- [x] 3.3 Update `app-auth/README.md`'s description of `/.freepod/auth/logout`, and check it against the verifier and broker specs

## 4. Docs

- [x] 4.1 Update "Signing in and out are links, not code" in `cli/src/freepod/assets/SKILL.md`: logout also ends the Freepod sign-in (the user confirms on Freepod's page, then signs in again on the next visit and may pick another account), other apps stay signed in, and it's the link to offer for "sign in as someone else". Verify the CLI's skill-asset test, if any, still passes

## 5. Release and verify

- [x] 5.1 Bump `app-auth/VERSION` (0.1.2 → 0.2.0), build and push with `scripts/build-images.sh`, repoint `app_auth_image` in `tf/app/variables.tf`, and apply to dev; verify with `kubectl` that the app-auth pods run the new tag
- [x] 5.2 On dev, with a signed-in browser on an auth-enabled app with no public `/`: open `/.freepod/auth/logout?rd=/`, confirm Keycloak's "Do you want to log out?" page (themed) appears, log out, land on the Keycloak sign-in form, sign in as a second account, and land back on the app as that account; also confirm a second app's session survived
- [x] 5.3 Apply to prod and repeat 5.2 against the upgrader (`upgrader.prutser.freepod.eu`): the 403 page's "Sign in with another account" reaches the Keycloak sign-in form instead of looping
