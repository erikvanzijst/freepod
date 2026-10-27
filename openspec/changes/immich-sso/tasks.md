# Tasks

## 1. The copy (D1)

- [x] 1.1 Copy `products/immich/chart` to `products/immich-sso/chart`, set `name: immich-sso`, `version: 0.1.0` and a description saying it is the SSO sandbox copy in its `Chart.yaml`, and rebuild its `ssh-sidecar` dependency. Verify `git diff master -- products/immich` is empty and `helm lint products/immich-sso/chart` passes.
- [x] 1.2 Add `api/tests/test_immich_sso_chart.py` (in conftest's `helm_charts` xdist group), rendering the copy with `helm template` the way `test_docmost_chart.py` does. Pin that with SSO off it renders the same resources as `products/immich/chart`, apart from chart-name labels. Verify it passes, and that `test_chart_release_label_contract.py` passes with the new chart included.
- [x] 1.3 Add `sso.enabled: false`, empty `caelus.oidc` and `caelus.owner` defaults to the copy's `values.yaml`, and their shapes to its `values.schema.json`. Verify the 1.2 test still passes and that `helm template` with `sso.enabled: true` but no `caelus.oidc` block, or no `caelus.owner.email`, fails with a message naming the missing value.

## 2. Immich's OAuth settings (D2, D3, D4, D6, D7, D8)

All edits are in `products/immich-sso/chart`.

- [x] 2.1 Render the ConfigMap's config as JSON. With SSO on, add the D3 `oauth` and `passwordLogin` blocks, with `clientSecret` left out, and `endSessionEndpoint` built as `<issuer>/oidc/logout?client_id=<clientId>&post_logout_redirect_uri=https://<host>/` (URL-encoded). Verify with tests: SSO off renders the same settings as the catalog chart (JSON instead of YAML), SSO on renders every D3 value, and no rendered resource contains a client secret.
- [x] 2.2 With SSO on, add an init container from the server image that runs `node` to merge `OIDC_CLIENT_SECRET` (a `secretKeyRef` on `caelus.oidc.secretName`, that key only) into the ConfigMap's JSON and write it to a memory-backed `emptyDir`. The server mounts that `emptyDir` at `/config` instead of the ConfigMap. Verify with tests that only the init container references the Secret, the server container's environment doesn't, and SSO off still mounts the ConfigMap.
- [x] 2.3 Run the 2.2 merge script with `node` against a sample ConfigMap JSON and a sample secret. Verify the output parses as JSON, holds the secret under `oauth.clientSecret`, and that the script fails without `OIDC_CLIENT_SECRET` instead of writing a config with no secret.

## 3. The owner's admin account (D5)

- [x] 3.1 In the copy, with SSO on, add a `postStart` hook on the server container, following the Docmost hook: wait for `/api/server/ping` on localhost, then `POST /api/auth/admin-sign-up` with `caelus.owner.email`, the part of the email before the `@` as the name, and a random password generated in the hook and never stored. Treat an answer that the instance already has an admin as success, and fail on anything else. Verify with a test that the hook is rendered only with SSO on, and with a comment in the template saying why probes waiting for it keep a fresh instance unclaimable.

- [x] 3.2 Add a `wait-for-postgres` init container to the server pod, first and with or without SSO, so Immich doesn't exit on a first install before Postgres accepts connections and take the 3.1 hook down with it. Publish as 0.1.1. Verify with a test, and on dev that a fresh deployment starts with no restarts.

## 4. Release

- [x] 4.1 Add a terse `products/immich-sso/README.md`: what the chart is for, what `sso.enabled` needs, and a link to the `immich-sso` spec. Verify `helm lint products/immich-sso/chart` passes with SSO off and on, the full `api/` suite passes with `-n 8`, and `git diff master -- products/immich` is still empty.

## 5. Product on dev

- [x] 5.1 After the chart is published, create the product on dev in the API pod with `caelus create-product` ("Immich (SSO)", `--visibility admin`), then `caelus create-template` with chart `oci://ghcr.io/erikvanzijst/freepod/charts/immich-sso` at `0.1.0`, the catalog Immich product's values schema (hostname only), and system values `{"image": {"tag": <catalog's tag>}, "smtp": <catalog's smtp>, "sso": {"enabled": true, "redirectPaths": ["/auth/login"], "nativeRedirectUris": ["app.immich:///oauth-callback"]}}`. Then create a plan and plan template matching the catalog Immich product's smallest plan. Verify `caelus get-product` shows `admin` visibility, and that `caelus create-deployment` with user values `{"host": …, "sso": {"enabled": false}}` is refused.
- [x] 5.2 Deploy it under a dev account. Verify that the pod becomes Ready only after the hook has run, the Immich admin is the owner's email, the rendered values and ConfigMap hold no client secret, and the provider lists the deployment as a client (discovery and an authorize request for its client ID answer without an error page).

## 6. Verify on dev

- [x] 6.1 Web: sign in as the owner. Verify the consent page names the instance's hostname, the owner lands in Immich as admin, the login page offers no password form, a password POST to `/api/auth/login` is refused, and the authentication settings are read-only in Immich's admin screens.
- [x] 6.2 Access: sign in with a second dev Freepod account the admin never created. Verify Immich refuses it and creates no user. Then create that user in Immich's administration with the account's email, sign in again, and verify it lands as a non-admin user with an unchanged quota.
- [x] 6.3 Mobile (Erik, on a phone with the Immich app): add the server, sign in with Freepod as a user who has not consented yet. Verify the consent page appears, the browser returns to the app after allowing, the app is signed in, and backup starts.
- [x] 6.4 Sign-out: sign out in the web UI. Verify Freepod's sign-out prompt appears, the Freepod session ends, and the browser lands on the instance's root, which sends it to sign in again.
- [x] 6.5 Rotation: restart the server pod. Verify the init container rewrites the config, sign-in still works, and no second admin was created.
- [x] 6.6 Catalog untouched: verify the catalog Immich product's template still points at `charts/immich` 0.2.7, and an existing catalog Immich deployment on dev still serves its password login.

## 7. Product on prod

- [ ] 7.1 Create the same product, template and plan on prod with `caelus` in the prod API pod, still `admin` visibility. Verify one prod deployment signs in on the web and in the mobile app, then keep or delete it.

## Workflow follow-up

- Archive the change and sync its spec.
- Next: promoting SSO to the catalog Immich product (its own change, which
  moves the SSO support into the catalog chart and retires the copy), and the
  allowlist change with back-channel logout.
