# Design

## Context

See proposal.md for why. The current state this design changes:

- `app/services/hostnames.py` validates a deployment hostname by **depth** under any of
  `settings.wildcard_domains`. One label is an account subdomain and two labels are an
  application beneath one. `GET /api/hostnames/{fqdn}` answers both questions by depth, and
  the UI's subdomain claim uses it to check availability.
- Clients put the hostname together themselves. The CLI's `normalize_hostname` appends
  `.<subdomain>.<domain>` to a bare label, and the UI's `HostnameField` renders that suffix and
  emits the full name. `.freepod.json` stores the full name.
- On an account's first deployment, the reconciler creates a Cloudflare record
  `*.<subdomain>.freepod.eu` and a DNS-01 `Certificate` in `caelus-tls`, waits for the
  certificate (within a budget), and writes it into the Traefik `TLSStore`'s
  `spec.certificates`, which it owns field by field. Terraform owns the store's
  `defaultCertificate`. That certificate is the platform wildcard in `tf/deps/tls`, whose names
  come from `wildcard_dns_names`.
- `reserved_hostnames` is maintained per environment as a list of full names. It covers two
  things at once: which names can't be deployment hostnames, and (by taking the first label)
  which labels can't be subdomains.
- `freepod.app` is hosted on deSEC and already has `*.freepod.app` as a CNAME to the apex,
  which points at the platform edge. An uncommitted spike in `tf/deps/certmanager` adds a deSEC
  webhook solver to both DNS-01 ClusterIssuers, selected for the `freepod.app` zone.
- Every CLI release already sends `User-Agent: freepod/<version> (+https://freepod.eu)` on
  every request.
- Traefik is 3.7. A permanent `redirectRegex` answers GET with 301 and every other method with
  308.

## Goals / Non-Goals

**Goals:**

- Clients need no knowledge of the hostname format: they show an opaque suffix, and the server
  completes the name.
- The domain-specific configuration is one value per environment (`tenant_domain`). The lists
  are the same for both environments.
- Old tenant hostnames keep working, as redirects only, until a later change retires them.

**Non-Goals:**

- Migrating any app's internal state. A changed base URL is fixed on each app's own
  terms, accepted as collateral damage.
- Any compatibility path for released CLIs other than refusing them clearly.
- Deleting existing per-account Cloudflare records, `Certificate`s, or the store's membership
  list.

## Decisions

### D1. One label, handle last

A tenant hostname is exactly one label beneath `tenant_domain`: `<app>-<handle>`. A handle
contains no `-`, so the handle is the text after the last `-`, and the application part is
everything before it, dashes included. Limits: handle 2–20 characters of `[a-z0-9]`; application
part 1–34 characters of `[a-z0-9-]`, beginning and ending with an alphanumeric, with no `--`
anywhere. The reserved `preview-` prefix (8 characters) brings the worst case to
8 + 34 + 1 + 20 = 63, the DNS label limit.

`--` is banned outright rather than only at positions 3–4, where a label would read as a
reserved (R-LDH) or punycode label. A blanket rule is simpler to state and explain, and no live
name uses `--`.

*Alternative considered:* keeping `<app>.<handle>.freepod.app`. Rejected: one PSL entry would
then make each handle, not each app, the registrable domain, and the per-handle wildcard
certificate and DNS record would remain.

### D2. The server completes a bare label; the client treats the suffix as opaque

Wherever a hostname enters the platform (deployment create, update, and the hostname check), a
value with no dot is an application label and is completed to
`<label>-<owner handle>.<tenant_domain>`. A value with a dot is used as given. The completed
name is what is stored in `deployment.hostname` and written back into the hostname path of
`user_values`, so charts always receive a fully qualified name.

`GET /api/me/handle` reports `handle`, `suffix` (`-<handle>.<tenant_domain>`, null until a
handle is claimed) and `domain` (`tenant_domain`, always present). The UI shows `suffix` after
the input and emits `label + suffix`. The CLI sends a bare label unchanged, and puts
`label + suffix` together only to compare against the deployment's current hostname. Neither
client knows that `-` is the separator.

*Alternative considered:* clients assemble the name from the handle and the domain, as today.
Rejected: it is exactly what makes this change break every released client.

### D3. Validation order

```
 lowercase -> bare label? complete it (D2)
     |
 format (RFC 1123, 253/63)                         --> invalid
     |
 under tenant_domain?
   yes: exactly one label beneath it?              --> invalid
        app part / handle split valid (D1)?        --> invalid
        handle == owner's handle?                  --> claimed
        app part starts with "preview-"?           --> reserved
        held by a live deployment?                 --> in_use
        (no DNS check: the platform serves it)
   no:  under any platform_domains entry?          --> reserved
        held by a live deployment?                 --> in_use
        CNAME to tenant_domain, or A/AAAA on its addresses?  else --> not_resolving
```

The owner is now an input to validation. Previously, ownership was a separate check run by the
deployment service, because the validator had no notion of an owner. With the handle encoded in
the label, ownership is part of the format question, so the validator takes the owner's handle.
The reason codes are unchanged.

Custom domains point at the tenant domain (`GET /api/cname-target`), which always resolves to
the platform's edge. A CNAME to `settings.domain` is refused like any other: the few custom
domains that point there are re-pointed by their owners.

`platform_domains` is `["freepod.eu", "freepod.app"]` in both environments. A name equal to an
entry or beneath it is never a custom domain. This covers Freepod's own hosts, every retired
`<app>.<subdomain>.freepod.eu`, and the other environment's tenant names (`x-erik.freepod.app`
sent to dev). An old-pattern name therefore gets `reserved`, with no dedicated code. Released
CLIs are stopped before they could send one (D5), and the UI ships together with the API.

### D4. Two lists replace `reserved_hostnames`

- `reserved_handles`: a single list for both environments, in `tf/app`. Initial content is
  `www login smtp imap ssh grafana prometheus loki alerts alertmanager cr kube blob keycloak
  account auth dev freepod admin support security billing official`, which is the first labels
  of today's list plus the names that would read as Freepod staff in `<app>-<handle>`.
- `platform_domains`: D3.

Platform hosts beneath `tenant_domain` need no reservation, because a tenant label always
contains a `-`. `tenant_domain`'s own apex and dashless names such as `www.freepod.app` can't
be expressed by the tenant pattern.

### D5. Minimum client version, enforced on every endpoint

A middleware parses `User-Agent` for `freepod/<version>`. When the version (compared with PEP
440 ordering) is below `MIN_CLIENT_VERSION`, it answers **426** with
`{"detail": "...Upgrade `freepod` to continue (uv tool update freepod || brew upgrade freepod ||
pip install --upgrade freepod).", "code": "client_upgrade_required"}`
before routing. Requests without a `freepod/` agent, or with an unparseable version, pass
through: the gate concerns the platform's own client, not the general HTTP surface.
`MIN_CLIENT_VERSION` is a constant in the API code. It is raised in the same commit as any
backend change that a released client can't survive, so it can't drift from the change that
needed it.

A released client surfaces the 426's `detail` through its generic error path, so the message
reaches the user without any client-side support.

*Alternative considered:* detecting the old hostname pattern. Rejected: a released client
fails earlier, in deploy preflight, on `GET /api/me/subdomain`, which no longer exists, and
would report a bare 404.

### D6. The claim is idempotent, and its dry run is the availability check

`POST /api/me/handle` with the handle already held returns 200 and writes nothing. A different
handle while one is held is 409. `?dry_run=1` runs the identical path and skips the write and
commit. The UI's as-you-type check calls the dry run. `GET /api/hostnames/{x}` no longer
answers handle questions at all.

### D7. Tenant TLS through the default certificate

The `wildcard_dns_names` of the platform certificate in `tf/deps/tls` gains `freepod.app`,
`*.freepod.app` and `*.dev.freepod.app`. `dev.freepod.app` is covered by `*.freepod.app`, and
listing it as well makes Let's Encrypt refuse the order as redundant. The DNS-01 issuer picks the solver
per zone, using the Cloudflare selector for `freepod.eu` and the deSEC selector for
`freepod.app`, so one order covers both zones. The certificate is already the store's
`defaultCertificate`, so every tenant hostname is served without touching the store's
membership, which Terraform can't declare without taking ownership of it.

`caelus.ingress.tls.wildcard` keeps its name in the chart contract. It now means "under
`tenant_domain`". Renaming the key would force a version bump on every product chart for no
behavior change.

*Alternative considered:* a separate `Certificate` per tenant domain added to the store's
membership. Rejected: membership is the reconciler's field, which this change stops writing
(D8).

### D8. Per-account provisioning code goes; its state stays

The reconcile path stops creating DNS records, stops requesting and waiting for account
certificates, and stops writing the store's membership list. `app/services/dns.py`, the
Cloudflare client, its settings, and the certificate wait budget are deleted. Records,
`Certificate`s and the last membership list written all stay where they are. cert-manager keeps
renewing those certificates through the Cloudflare solver for `freepod.eu`, which stays in place
for the platform certificate. They exist only so the old hostnames' redirects (D9) still
complete a TLS handshake.

### D9. Old hostnames redirect through a static list

`tf/app` takes a `legacy_tenant_redirects` variable: a list of old hostnames per environment,
supplied from the uncommitted `secrets.auto.tfvars` because it names tenants' applications.
Each environment renders one IngressRoute with a `Host(...) || Host(...)` rule on `websecure`
and one `redirectRegex` middleware:
`^https://([^.]+)\.([^.]+)\.<old domain>(.*)` → `https://${1}-${2}.<tenant_domain>${3}`,
`permanent: true`. On Traefik 3.7 that answers GET with 301 and every other method with 308,
so the method and body are preserved where it matters. The certificate for each name comes
from the account certificates already in the store.

Explicit `Host` rules avoid regex host matching and the priority tricks it needs: a regex over
`*.*.freepod.eu` also matches platform hosts such as `cr.dev.freepod.eu`.

The routes are applied only after the migration's reconciles have moved each app's own
Ingress off its old host. Before that, two routes with the same `Host` rule would compete.

### D10. The apexes redirect to the platform

`freepod.app` → `https://freepod.eu` and `dev.freepod.app` → `https://dev.freepod.eu`, both
permanent, following the existing `freepod.dev` pattern in `tf/deps/system`. The certificate
comes from D7.

### D11. A one-off migration script, then deleted

`api/scripts/migrate_tenant_hostnames.py` imports `app.*` and is copied into the API pod and
run there. It is a dry run unless `--apply` is given. For each live deployment whose hostname
is `<app>.<subdomain>.<old domain>`:

1. It computes `<app>-<subdomain>.<tenant_domain>` and checks it against D1, without the DNS
   check.
2. It rewrites `deployment.hostname` and every hostname-titled path in `user_values`, found by
   the same schema walk the deployment service uses.
3. It queues a reconcile.

Running it again finds nothing left to do. It prints the `legacy_tenant_redirects` snippet for
D9. The column rename `user.subdomain` → `user.handle`, including its partial unique index, is
an ordinary Alembic migration. The script isn't added to the `caelus` CLI and is deleted once
both environments are migrated.

### D12. CLI project-file rewrite

On load, a `.freepod.json` hostname matching `<label>.<x>.<old domain>` for `freepod.eu` or
`dev.freepod.eu` is rewritten to `<label>` and saved, with one line telling the user. The rule
is a fixed pattern in the client, deliberately not learned from the platform: it exists to
clean up that client's own earlier output. The bare label lands beneath the current account's
handle, which is also what a cloned project should do.

## Risks / Trade-offs

- **One certificate spans two DNS providers** → a failed DNS-01 order in either zone blocks
  renewal for both. cert-manager starts renewing 30 days before expiry, which leaves time to
  act, and the issuer's status shows which solver failed.
- **The store's membership is now unmanaged** → if the store is recreated, the old hostnames
  lose their certificates and their redirects fail TLS. This is accepted until the retirement
  change. New tenant hostnames are unaffected because they use the default certificate.
- **Apps that store their own URL** (Nextcloud `trusted_domains`/`overwrite.cli.url`,
  BookStack's absolute links, Immich's external domain, Vaultwarden's WebAuthn RP ID, Lemmy's
  federation identity) break or degrade after the move → accepted. They are fixed by hand where
  possible, or the app is recreated.
- **A window in which unmigrated deployments fail validation**, between the API rollout and the
  script → no edit to such a deployment succeeds (`reserved`). The script runs immediately after
  the rollout.
- **Released CLIs stop working on rollout** → that's the intent. The 426 names the fix. The new
  CLI is published at the production cut-over, not before, because it can't talk to an API that
  hasn't been upgraded.
- **App Studio workspaces carry old-format `.freepod.json` files** → rewritten by the new CLI
  on the next deploy (D12). The new studio image bundles that CLI.
  The studio's CLI is installed from a path, so the generic `uv tool upgrade freepod` does not
  work there; a live studio is moved onto the new chart instead.

## Migration Plan

Dev first, end to end, then prod.

1. `tf/deps`: the deSEC webhook and solver (the spike), then the extra certificate names.
   `dev.freepod.app` and `*.dev.freepod.app` carry their own CNAMEs to `freepod.app`: without
   them, the challenge record `_acme-challenge.dev.freepod.app` would make `dev.freepod.app` an
   empty non-terminal and stop `*.freepod.app` from answering beneath it during every order.
   Wait for the `Certificate` to be Ready, and confirm it serves `*.freepod.app` and
   `*.dev.freepod.app`.
2. `tf/app` (dev): `tenant_domain`, `reserved_handles`, `platform_domains`, the
   `freepod.app`/`dev.freepod.app` apex redirect, and removal of the API's Cloudflare DNS
   settings.
3. Roll out the API and UI to dev, which runs the Alembic rename. Install the CLI from the
   branch (`uv tool install ./cli`).
4. Run the script in the dev API pod: a dry run, then `--apply`. Wait for the reconciles.
5. Put the printed list into `secrets.auto.tfvars` and apply the dev redirect routes.
6. Publish the App Studio image and chart, and point the dev catalog at them. Verify deploys,
   previews, Sign in with Freepod, and the redirects.
7. Prod: repeat steps 2–5. Publish the CLI release to PyPI right after the API rollout.
   Point the prod catalog at the new App Studio.
8. Delete the script.

Rollback, before step 4: revert the API and UI images; the Alembic downgrade restores the
column name. After step 4, roll forward only: the old hostnames' Ingresses are gone and the
redirects are the way back.
