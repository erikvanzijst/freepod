# Proposal

## Why

Tenant applications are addressed at `<app>.<subdomain>.freepod.eu`, which puts every tenant on
the same browser site as Freepod's own apex, API and identity provider. Even if `freepod.eu`
made it onto the Public Suffix List, all of an account's applications would still share one
site. The per-account layout also costs a DNS record and a DNS-01 wildcard certificate for every
account that deploys, and every first deployment waits for both. Moving tenants to a flat
namespace on a domain of their own, `<app>-<handle>.freepod.app`, separates tenants from the
platform today. It gives one site per application once `freepod.app` is listed on the PSL, and
it needs one static DNS record and one wildcard certificate per environment, however many
accounts there are.

## What Changes

- **BREAKING** Tenant hostnames become `<app>-<handle>.<tenant_domain>`: `freepod.app` in
  production and `dev.freepod.app` in development. The handle is always the last
  `-`-separated segment of the label. `freepod.eu` serves only Freepod's own names.
- **BREAKING** The account "subdomain" becomes the account **handle**: 2–20 characters of
  `[a-z0-9]`, so it can never contain `-`. The application part is 1–34 characters, with no
  leading or trailing `-` and no `--`. The reserved `preview-` prefix keeps a full name within
  63 characters. Everywhere the concept appears is renamed: the user column, the
  `/api/me/handle` endpoint (formerly `/api/me/subdomain`), the `handle_required` error code,
  the operator CLI, the UI, the end-user CLI and the docs.
- A claim is idempotent. Re-claiming the handle the account already holds succeeds without
  changing anything. `POST /api/me/handle?dry_run=1` answers exactly as a real claim would,
  without storing anything, and replaces checking a handle's availability through the hostname
  check.
- The server completes a bare application label (`photos`) beneath the owner's handle, both on
  deployment create/update and on the hostname check. A fully qualified name that matches the
  owner's own pattern is also accepted. A name with a dot that is outside the platform's domains
  is a custom domain, as before.
- `reserved_hostnames` is replaced by two lists that are the same in every environment:
  **reserved handles**, and **platform domains**. Nothing under a platform domain can be used
  as a custom domain.
- **BREAKING** The API refuses every request from a `freepod` CLI older than a minimum version
  that is fixed in code, with **426** and a message telling the user to upgrade. The new CLI
  release rewrites an old-format hostname in `.freepod.json` to its bare label.
- Per-account DNS records and per-account wildcard certificates are no longer created, and the
  code that created them, waited for them and listed them in the TLS store is removed. Records
  and certificates that already exist stay in place, untouched, to keep the old hostnames'
  redirects working.
- The platform's default certificate also covers `freepod.app`, `*.freepod.app` and
  `*.dev.freepod.app` (`dev.freepod.app` falls under `*.freepod.app`). These are issued by DNS-01 through deSEC, which
  hosts the `freepod.app` zone.
- Every live deployment on the old pattern is moved to its new hostname by a one-off script.
  Each old hostname then permanently redirects (**308**) to its new one, through a static list
  configured in Terraform. The `freepod.app` and `dev.freepod.app` apexes permanently redirect
  to `freepod.eu` and `dev.freepod.eu`.
- App Studio's image, chart and agent instructions, and the CLI's bundled `deploy-to-freepod`
  skill, describe only the new hostname format.
- The in-flight `dns-cloudflare-to-hetzner` change is dropped. Its only motivation was
  per-account DNS records.

Out of scope: submitting `freepod.app` to the Public Suffix List, and deleting the leftover
per-account records, certificates and redirects. Each is a later, separate change.

## Capabilities

### New Capabilities

- `account-handle`: the handle an account holds. Its format, how it is claimed (including the
  dry run), its permanence, reserved handles, and how it is read. Replaces
  `account-subdomain-record`.
- `account-handle-ui`: the one-time dialog in which a user chooses their handle. Replaces
  `account-subdomain-ui`.
- `cli-handle-required`: what the end-user CLI does when the account holds no handle. Replaces
  `cli-subdomain-claim`.
- `client-version-gate`: the API refuses requests from end-user CLI releases older than the
  minimum version the backend supports.
- `tenant-domain-edge`: what the edge serves on the tenant domain's own names (the apex
  redirects) and on hostnames tenants no longer use (the static 308 redirects).

### Modified Capabilities

- `hostname-validation`: a single tenant pattern under `tenant_domain`, with the owner's
  handle, label limits and the `preview-` reservation. Platform domains are refused as custom
  domains. Validation by subdomain depth is removed.
- `hostname-check-endpoint`: completes a bare label, answers only about deployment hostnames,
  and no longer answers handle availability. The response shape is corrected to its three
  actual fields.
- `deployment-create-contract`: bare labels are completed on the server. The create
  precondition becomes `handle_required`. A tenant hostname must carry its owner's handle.
- `app-tls-injection`: a hostname counts as platform-served when it is under `tenant_domain`
  rather than under a configured wildcard domain.
- `platform-tls-store`: the reconciler no longer writes the store's membership list. Only the
  default certificate is managed.
- `freepod-tls-termination`: the default certificate covers the tenant domains as well as
  `freepod.eu`.
- `freepod-cert-manager`: the DNS-01 issuer solves `freepod.app` through deSEC alongside
  `freepod.eu` through Cloudflare, and the platform certificate covers both.
- `app-auth-broker`: preview hostnames are `preview-<app>-<handle>.<tenant_domain>`.
- `cli-deploy`: a bare label is sent as-is for the server to complete. An old-format hostname
  in the project file is rewritten to its bare label.
- `cli-init`: a bare label is written to the project file as entered.
- `hostname-field-ui`: the Freepod address suffix is `-<handle>.<tenant_domain>`, taken as
  the opaque `suffix` the platform reports.
- `admin-users-panel`: the users table shows the handle.
- `pydantic-settings`: `wildcard_domains` and `reserved_hostnames` give way to
  `tenant_domain`, `platform_domains` and the reserved-handle list.
- `app-listing-page`: install asks for a handle rather than a subdomain.

### Removed Capabilities

- `account-subdomain-record`, `account-subdomain-ui`, `cli-subdomain-claim`: replaced by the
  renamed capabilities above.
- `account-dns-record`, `account-tls-certificate`: the platform no longer provisions anything
  per account.

## Impact

- **API**: `app/services/hostnames.py`, `app/services/deployments.py`, `app/services/users.py`,
  `app/api/users.py` (the `/api/me/handle` routes), `app/api/hostnames.py`,
  `app/models/core.py`, `app/config.py` and `app/cli.py`. The reconciler drops account
  DNS/certificate provisioning and its TLS store writes. `app/services/dns.py` and the
  Cloudflare SDK dependency are deleted. There is new middleware for the client version gate.
  An Alembic migration renames `user.subdomain` → `user.handle` and its unique index.
- **UI**: the `ui/src/components/subdomain/` claim components (renamed), `HostnameField`,
  `UsersPanel`, the API types and endpoints, and `ui/docs` pages that describe addresses.
- **End-user CLI (`cli/`)**: hostname handling, `subdomain.py` → `handle.py`, the project-file
  rewrite, the bundled `assets/SKILL.md`, and a minor version release.
- **Terraform**: in `tf/deps`, the deSEC webhook and issuer solver (the existing uncommitted
  spike) and extra names on the default certificate. In `tf/app`, `tenant_domain`, the
  reserved-handle and platform-domain lists, the apex redirects for `freepod.app` and
  `dev.freepod.app`, the static redirect routes for old hostnames fed from
  `secrets.auto.tfvars`, and removal of the API's Cloudflare DNS settings.
- **Products**: the App Studio image (bundled CLI), its chart version and agent `AGENTS.md`.
- **Data**: every live deployment under `*.freepod.eu` / `*.dev.freepod.eu` is rewritten in
  place. Apps that store their own URL (Nextcloud, BookStack, Immich,
  Vaultwarden, Lemmy) may need manual follow-up, which has been accepted.
- **Removed change**: `openspec/changes/dns-cloudflare-to-hetzner/`.
