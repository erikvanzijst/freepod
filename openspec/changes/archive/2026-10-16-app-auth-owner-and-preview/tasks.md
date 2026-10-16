# Tasks

## 1. Broker: any product, effective values (D1)

- [x] 1.1 Rewrite the eligibility query in `daemons/app-auth/store.go` to drop the product join and read `auth.enabled` as template system value, then release user value, then false; remove `productSlug` from `pgStore`, `main.go` and its `APP_AUTH_PRODUCT_SLUG` setting; in `tf/app/caelus/app-auth-bootstrap.sql`, grant `product_template_version.system_values_json` in place of `product_id` and the `product` grant. Verify with `go build ./...` in `daemons/app-auth`.
- [x] 1.2 Rework `store_test.go` to isolate by unique hostnames instead of a per-test slug, and add cases for another product, a template-enabled deployment with no user `auth`, and a template value overriding a user `false`. Verify with `go test ./...` against `CAELUS_TEST_DATABASE_URL`.

## 2. Broker: preview alias (D2)

- [x] 2.1 In the broker's eligibility check (`broker.go`), when a host has no exact match and its first label starts with `preview-`, look up the host without the prefix through the same store check, and return that deployment's id; the store keeps matching hostnames exactly (a `store_test.go` case pins that). Verify with broker tests: preview of an auth-enabled deployment, of one without authentication, and of an unknown base host.
- [x] 2.2 Extend the broker tests (`broker_test.go`, `memstore_test.go`) to show a preview host completing sign-in with a code bound to the preview host, and consent given on the base host not being asked again on the preview host. Verify with `go test ./...`.

## 3. Verifier: allowed accounts (D3)

- [x] 3.1 Add the `a` and `n` parameters to the verifier in `verify.go`: decode and cache `a` like `p`, refuse a request with a session whose lowercased email is not listed (public paths included), and treat an undecodable list as admitting nobody. Verify with `go vet ./...`.
- [x] 3.2 Add the no-access page to `pages.go` in the look of `products/custom/placeholder/index.html` (navigation gets `403` with the page naming `n` or the host, `https://<host>`, the signed-in email and a sign-out link; other requests a plain `403`). Verify by rendering it for a named and an unnamed application and checking both in a browser, light and dark.
- [x] 3.3 Add `verify_test.go` cases: allowed account, case-insensitive match, other account (page and `403`), page with and without `n`, public path with another account's session, anonymous public path, corrupt list. Verify with `go test ./...`.
- [x] 3.4 Update `daemons/app-auth/README.md` (any auth-enabled deployment, not only `custom`; the allowed-accounts parameter; preview hostnames) and bump `daemons/VERSION`. Verify the README's spec links resolve.

## 4. App Studio chart (D4)

- [x] 4.1 Add `templates/app-auth.yaml` to `products/appstudio/chart` (identity-header strip and forward-auth with `a=[caelus.owner.email]` and `n=App Studio`), put both middlewares ahead of the existing ones on the studio and preview Ingresses, and fail rendering without `caelus.appAuth.verifyUrl` or `caelus.owner.email`, or when `auth.enabled` is not true. Remove `passwordSecret`, `preview.basicAuthSecret` and the basic-auth middleware. Bump the chart version. Verify with `helm lint` and `helm template` renders for the success and each failure case.
- [x] 4.2 Add `api/tests/test_appstudio_chart.py` (in the `helm_charts` xdist group) asserting every route passes the verifier, the allowed list is exactly the owner email, and the failure cases refuse to render. Verify with `uv run pytest tests/test_appstudio_chart.py`.
- [x] 4.3 Update `products/appstudio/README.md` (owner-only sign-in replaces the password) and the root `AGENTS.md` paragraph on Sign in with Freepod (any product; optional allowed accounts; preview hostnames), each as a terse pointer to the specs. Verify the links resolve.

## 5. Release and roll out on dev

- [x] 5.1 Build and push the daemons image at the new version and roll dev's app-auth with `terraform apply -var app_auth_image=…` in the default workspace, after checking `terraform workspace show`. Verify an existing auth-enabled `custom` app still signs in.
- [x] 5.2 Publish the appstudio chart, create a new App Studio template version on dev with `auth.enabled: true` as a system value, and move the dev deployment to it. Verify: the owner reaches the studio and preview after signing in; another account gets the no-access page; no password prompt remains.
- [x] 5.3 Delete the hand-made password Secrets from the deployment's namespace and verify the studio keeps serving.

## Workflow follow-up

- Bump the `app_auth_image` default in `tf/app/variables.tf` and apply prod once dev is verified.
- Archive the change and sync its specs.
