# Tasks

## 1. Housekeeping

- [x] 1.1 Delete `openspec/changes/dns-cloudflare-to-hetzner/`, and verify `openspec list` no longer shows it

## 2. Platform certificate for the tenant domains (`tf/deps`)

- [x] 2.1 Adopt the deSEC webhook spike (`tf/deps/certmanager/desec.tf`, the per-zone solvers in `issuers.tf`, `desec_api_token` in both variable files and `main.tf`). Verify with `terraform plan` that it shows only the webhook release, the token Secret and the two issuer updates
- [x] 2.2 (Prerequisite, done by hand at deSEC: explicit `dev.freepod.app` and `*.dev.freepod.app` CNAMEs to `freepod.app`, so the DNS-01 challenge under `dev.freepod.app` cannot hide the `*.freepod.app` wildcard.) Add `freepod.app`, `*.freepod.app` and `*.dev.freepod.app` to `wildcard_dns_names` (not `dev.freepod.app`, which `*.freepod.app` covers and Let's Encrypt rejects as redundant) in `tf/deps/tls`, and update its comments and `freepod-cert-manager`-related docs to describe one certificate across two zones. Verify after apply that the `Certificate` is Ready and `openssl s_client -servername x-y.freepod.app` presents all six names

## 3. Configuration (`api/app/config.py`, `tf/app`)

- [x] 3.1 Replace `wildcard_domains` and `reserved_hostnames` with `tenant_domain`, `platform_domains` and `reserved_handles` in `CaelusSettings`. Verify with the settings tests updated per `pydantic-settings`
- [x] 3.2 In `tf/app`, derive `tenant_domain` (`freepod.app` / `dev.freepod.app`) per workspace, add one shared `reserved_handles` list (design D4) and `platform_domains = ["freepod.eu", "freepod.app"]`, drop the per-workspace `reserved_hostnames` map and its validation, and pass all three through the configmap. Verify with `terraform plan` in both workspaces

## 4. Account handle (API, operator CLI)

- [x] 4.1 Alembic migration renaming `user.subdomain` → `user.handle` and `uq_user_subdomain_active` → `uq_user_handle_active`, with a working downgrade. Verify by upgrading and downgrading against the test database
- [x] 4.2 Rename the ORM field and the read/claim models (`HandleRead` with `handle`, `suffix`, `domain`; `HandleClaim`). Replace `UserRead.wildcard_domain` with `handle`. Verify with the user-model tests
- [x] 4.3 Replace `/api/me/subdomain` with `GET`/`POST /api/me/handle`: the 2–20 `[a-z0-9]` format, reserved handles, the unfiltered held check, an idempotent re-claim (200), 409 `handle_already_claimed` for a different handle, and `?dry_run=1` running the same path without committing. Error codes are `handle_invalid`, `handle_reserved`, `handle_taken`, `handle_already_claimed`. Verify with tests covering every `account-handle` scenario
- [x] 4.4 Rename the operator command `caelus claim-subdomain` → `caelus claim-handle`, and the create precondition code `subdomain_required` → `handle_required`. Verify with the CLI and create-contract tests

## 5. Hostname validation and completion (API)

- [x] 5.1 Rewrite `app/services/hostnames.py` per design D1/D3: bare-label completion, the tenant pattern with the owner's handle (`claimed`), the `preview-` reservation, the platform-domain refusal, and the DNS check only for custom domains. Remove depth logic, `require_owned_subdomain` and `require_valid_subdomain`. Verify with tests covering every `hostname-validation` scenario
- [x] 5.2 In `app/services/deployments.py`, pass the owner's handle to validation and write the completed FQDN back into `user_values` and `deployment.hostname` on create and update. Verify with `deployment-create-contract` tests, including a bare label and another account's handle
- [x] 5.3 Make `GET /api/hostnames/{value}` complete bare labels for the caller and stop answering handle questions. Fix the response docs to its three fields. Verify with `hostname-check-endpoint` tests

## 6. Remove per-account DNS and TLS provisioning (API, `tf/app`)

- [x] 6.1 Remove the reconcile steps that create account DNS records, request and wait for account certificates, and write the TLS store's membership list. Delete `app/services/dns.py`, the Cloudflare settings, the certificate wait/defer settings and the `cloudflare` dependency. Delete their tests (`test_dns.py`, `test_reconcile_account_dns.py`, `test_account_certificate.py`, `test_reconcile_certificate_wait.py`, `test_certificate_store.py`) and adjust any others. Verify with `grep -ri cloudflare api/app` (no matches) and a green suite
- [x] 6.2 Classify `caelus.ingress.tls.wildcard` by `tenant_domain` in the reconciler. Verify with the app-tls-injection tests for a tenant hostname and a custom domain
- [x] 6.3 Remove the API's Cloudflare DNS token, zone and record-target wiring from `tf/app`. Verify with `terraform plan`
- [x] 6.4 Run the full `api/` suite (`-n 8`) and verify it is green

## 7. Client version gate (API)

- [x] 7.1 Add the `MIN_CLIENT_VERSION` constant (the CLI release from group 9) and middleware refusing `freepod/<older>` user agents with 426 `client_upgrade_required` on every route, before routing. Verify with tests covering every `client-version-gate` scenario, including a route that skips authentication

## 8. Web UI

- [x] 8.1 Rename `ui/src/components/subdomain/` to handle components and switch the API types and endpoints to `/api/me/handle`. The as-you-type check uses the dry-run claim and its `handle_*` codes. The address shows `<app>-` + handle + `.<domain>`. The confirmation shows `-<handle>.<domain>`. The prefill is reduced to `[a-z0-9]` and up to 20 characters. Verify with the component tests updated to every `account-handle-ui` scenario
- [x] 8.2 Make `HostnameField` render and emit the opaque `suffix`, split an initial tenant hostname back into its label, and allow `-` in the label. Verify with `HostnameField` tests per `hostname-field-ui`
- [x] 8.3 Show `handle` in `UsersPanel` and the account settings. Verify with their tests
- [x] 8.4 Update `ui/docs` (`apps/get-started.md`, `apps/how-freepod-works.md`, `apps/managing/hostname.md`, `apps/managing/custom-domain.mdx`, `developers/get-started.mdx`, `developers/hostnames-and-custom-domains.md`, `developers/runtime.mdx`) to describe handles and `<app>-<handle>.freepod.app` only. Verify with `grep -ri subdomain ui/docs` (no matches about accounts) and the docs build

## 9. End-user CLI (`cli/`)

- [x] 9.1 Replace `subdomain.py` with `handle.py` (`/api/me/handle`, `handle_required`). Verify with the preflight and refusal tests per `cli-handle-required`
- [x] 9.2 Send bare labels as-is. Compare against the deployment's hostname using the reported `suffix`. Write bare labels on `freepod init`. Verify with tests per `cli-deploy` and `cli-init`
- [x] 9.3 Rewrite old-format `.freepod.json` hostnames to their label on load and print one line. Verify with tests for the prod, dev and untouched cases
- [x] 9.4 Update `assets/SKILL.md` (the hostname format, `myapp.example.freepod.eu` → a bare label, the shared-site paragraph rewritten for `freepod.app` without history) and `cli/README.md`. Verify with `grep -n 'freepod\.eu' cli/src/freepod/assets/SKILL.md` showing only platform URLs
- [x] 9.5 Bump the CLI to the minor version named by `MIN_CLIENT_VERSION`, without publishing. Verify that `freepod --version` from `uv tool install ./cli` reports it and that requests carry `freepod/<that version>`

## 10. App authentication

- [x] 10.1 Add broker tests for flat preview hostnames (`preview-studio-alice.freepod.app` → `studio-alice.freepod.app`), and switch existing fixtures and comments from `<app>.<sub>.freepod.eu` examples to the flat form. Verify that `go test ./...` in `daemons/app-auth` passes with no code change to `previewBase`

## 11. Tenant domain edge (`tf/app`)

- [x] 11.1 Add the permanent apex redirects `freepod.app` → `https://freepod.eu` and `dev.freepod.app` → `https://dev.freepod.eu`, following the `freepod.dev` pattern. Verify with `curl -sI https://freepod.app/x` after apply
- [x] 11.2 Add the `legacy_tenant_redirects` variable (sensitive, from `secrets.auto.tfvars`, default empty) and the per-environment IngressRoute with explicit `Host` rules and a permanent `redirectRegex` (design D9). Verify with `terraform plan` that an empty list renders nothing and a one-entry list renders one route

## 12. Migration script

- [x] 12.1 Write `api/scripts/migrate_tenant_hostnames.py` (design D11): dry run by default, `--apply` to rewrite and queue reconciles, idempotent, and printing the `legacy_tenant_redirects` snippet. Verify with a test against the test database: a second run finds nothing to do

## 13. App Studio

- [x] 13.1 Update `products/appstudio/image/AGENTS.md` to describe only the current hostname format, and add that upgrading the CLI is fine when the API refuses it with an upgrade message, leaving how to the agent. Verify by reading it for any `subdomain` or `.freepod.eu` app hostnames
- [ ] 13.2 Bump the image (bundling the new CLI) and the chart version that references it, and publish both once the CLI is installable (design: dev first with the branch CLI if needed). Verify that the dev catalog points at the new chart and a studio deploys an app

## 14. Repository docs

- [x] 14.1 Update `AGENTS.md`, `README.md` and `api/README.md` to describe handles, tenant hostnames and the single platform certificate, linking the new and renamed specs. Remove the per-account DNS/TLS paragraphs. Verify that the links resolve once the specs are synced

## 15. Rollout (design: Migration Plan)

- [x] 15.1 Dev: apply `tf/deps` (group 2), then `tf/app`. Roll out the API and UI. Install the CLI from the branch. Run the script dry, then `--apply`. Verify that every dev deployment is ready on its new hostname
- [x] 15.2 Dev: apply the redirect list. Verify that an old dev hostname answers 301/308 to its new one, a preview signs in, and a CLI deploy with an old-format `.freepod.json` succeeds after the rewrite
- [ ] 15.3 Prod: `tf/app`, then the API and UI. Publish the CLI release. Run the script. Apply the redirect list. Point the prod catalog at the new App Studio, and move each live studio onto it (`caelus update-deployment --desired-template-id`). Verify as in 15.1–15.2, and that an older CLI gets the 426 message
- [ ] 15.4 Delete `api/scripts/migrate_tenant_hostnames.py` and its test. Verify that `git grep migrate_tenant_hostnames` is empty

## Workflow follow-up

- Archive the change, syncing the delta specs. Then delete the now-empty main specs of the removed capabilities (`account-subdomain-record`, `account-subdomain-ui`, `cli-subdomain-claim`, `account-dns-record`, `account-tls-certificate`) and fill in the `## Purpose` of each new one.
- A later change deletes the leftover per-account Cloudflare records, account `Certificate`s, the store's membership entries and the redirect routes.
- A later change submits `freepod.app` and `dev.freepod.app` to the Public Suffix List.
