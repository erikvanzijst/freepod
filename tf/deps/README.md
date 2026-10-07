# Shared Dependencies

This Terraform project manages cluster-wide singleton services that are
shared across all Caelus environments (dev and prod). It has its own
independent state and does not use Terraform workspaces.

## What It Creates

- `keycloak` namespace, deployment, Postgres database, PVC, service, ingress.
  Keycloak runs a **custom image** (`var.keycloak_image`) with the Freepod
  login/account/email theme baked in — see [Keycloak theming](#keycloak-theming).
- The **`freepod` Keycloak realm** and its clients, client scopes and groups,
  declared as Terraform in `keycloak-config/` — see
  [Keycloak configuration](#keycloak-configuration).
- `echo` namespace, deployment, service, ingress
- `monitoring` namespace with the cluster-wide observability stack (Loki +
  Promtail, Prometheus + node-exporter + kube-state-metrics + Alertmanager,
  Grafana) — see [Monitoring stack](#monitoring-stack).
- `caelus-tls` namespace (`tls/`) holding the platform wildcard certificate and
  the `TLSStore/default` Traefik serves from. The store is platform-owned rather
  than rendered by the Traefik release, and Traefik is pinned to this namespace
  with `providers.kubernetesCRD.defaultTLSResourcesNamespace` — a `default` store
  anywhere else is then ignored instead of making Traefik honour none of them.
  Terraform owns the default certificate; the reconciler owns the membership
  list. Spec:
  [platform-tls-store](../../openspec/specs/platform-tls-store/spec.md),
  [freepod-tls-termination](../../openspec/specs/freepod-tls-termination/spec.md)
  · Rationale:
  [per-user-tls-certificates](../../openspec/changes/per-user-tls-certificates/design.md)

## Prerequisites

- Terraform `>= 1.0`
- Access to the Kubernetes cluster via `../../k8s/kubeconfigs/dev-k3s.yaml`

## Configuration

Create `secrets.auto.tfvars` (gitignored):

```hcl
keycloak_admin_password = "replace-with-actual-password"

# Sign in with Google: the OAuth web client in the Google Cloud console
# (see "Sign in with Google" under Keycloak configuration)
google_client_id     = "....apps.googleusercontent.com"
google_client_secret = "GOCSPX-..."

# Mailer relay's upstream SMTP account (purelymail)
smtp_host     = "smtp.example.com"
smtp_port     = "587"
smtp_username = "relay@example.com"
smtp_password = "replace-with-actual-password"

# TLS: DNS-01 wildcard issuance through Cloudflare
cloudflare_api_token = "replace-with-actual-token"
letsencrypt_email    = "ops@example.com"

# Monitoring stack
grafana_admin_password = "replace-with-actual-password" # break-glass local admin
alert_email_to         = "ops@example.com"              # Alertmanager recipient
```

Grafana's OIDC client ID and secret are **not** configured here. The `grafana`
client is Terraform-managed (see [Keycloak configuration](#keycloak-configuration)),
so `module.prometheus` reads them straight from `module.keycloak_config`.

The monitoring stack needs no external SMTP credentials: Alertmanager relays
email through the in-cluster `mailer` service.

## Deploy

```bash
cd tf/deps
terraform init
terraform apply
```

## Monitoring stack

A **cluster-wide** observability stack in the `monitoring` namespace, shared by
all Caelus environments (it is *not* duplicated per env). Modules:

- `loki/` — Loki (SingleBinary, filesystem-backed, ~10Gi PVC) + a Promtail
  DaemonSet that ships every pod's logs to Loki, including parsed Traefik
  access logs. **Retention is enforced** — see below.

  > **The `namespace`, `instance` and `release_id` stream labels are a contract,
  > not operator convenience.** The Caelus API builds every LogQL selector for
  > `freepod log` out of exactly those three: `namespace` is the per-user
  > namespace, `instance` is `deployment.name` (the Helm release name), and
  > `release_id` comes from the `caelus.dev/release-id` pod label that every
  > product chart renders on its application pods. Renaming or dropping any of
  > them breaks a user-facing feature, not a dashboard. A pod without the
  > release label collects exactly as before, with no `release_id` and no
  > error, which is how every platform pod and every product datastore behaves.
  >
  > Retention is `limits_config.retention_period` plus
  > `compactor.retention_enabled`. Note that `compactor.replicas` at the top
  > level is **inert** in SingleBinary mode — the chart only renders that
  > StatefulSet when `deploymentMode` is `Distributed`, and the compactor
  > already runs in-process under `-target=all`. Raising it would start a
  > second compactor competing over the same filesystem store. Enabling
  > retention without `compactor.delete_request_store` is a hard startup
  > `CONFIG ERROR`.
  >
  > Promtail's rendered config lives in a **Secret**, not a ConfigMap:
  > `kubectl -n monitoring get secret promtail -o jsonpath='{.data.promtail\.yaml}' | base64 -d`.
- `prometheus/` — the `prometheus-community/prometheus` chart (bundles
  node-exporter for node CPU/mem/net/disk, kube-state-metrics for workload
  state, and Alertmanager), plus **Grafana** (mirrors the homelab layout). A
  forked `prometheus/scrape_configs.yaml` drops high-cardinality control-plane
  histogram buckets for the single node — **reconcile it when bumping the chart
  version**.

Runtime dependencies on other `tf/deps` singletons:

- **`keycloak`** — Grafana authenticates via OIDC and whitelists users by
  Keycloak group (see bootstrap below).
- **`mailer`** — Alertmanager delivers alert email through
  `smtp.mailer.svc.cluster.local:25` (no external SMTP secrets here).

### Access

Only **Grafana** is exposed, at `https://grafana.freepod.eu` (bare Traefik
ingress, no forward-auth — Grafana runs its own Keycloak login).

Prometheus and Alertmanager are **ClusterIP only** — reach them with
`kubectl port-forward`:

```bash
kubectl -n monitoring port-forward svc/prometheus-server 9090:80        # Prometheus UI → http://localhost:9090
kubectl -n monitoring port-forward svc/prometheus-alertmanager 9093:9093 # Alertmanager  → http://localhost:9093
```

### Grafana OIDC (Terraform-managed)

Nothing to bootstrap by hand. The `grafana` client, the
`freepod-observability` group and the `groups` client scope with its
group-membership mapper are all declared in `keycloak-config/` — see
[Keycloak configuration](#keycloak-configuration). `module.prometheus` reads
the client ID and generated secret directly from `module.keycloak_config`, so
no Grafana OIDC secret is maintained by hand.

Granting Grafana access is pure group membership: add the user to
`freepod-observability` in the Keycloak admin console. No Terraform apply.

Two settings that look optional but are not, both in
`prometheus/grafana.tf`:

- `groups_attribute_path = "groups"` — Grafana's `extractGroups()` returns an
  empty list without it, so the `groups` claim is never read and every login
  is rejected as "not a member of one of the required groups".
- **No `use_pkce`**, matched by no `pkce_code_challenge_method` on the
  `grafana` client. Grafana only sends a code challenge when `use_pkce` is
  true; setting the client attribute alone makes PKCE mandatory at Keycloak
  and fails every Grafana login. Enable both together or neither. (The
  oauth2-proxy clients *do* require PKCE and set the matching flag.)

## Keycloak configuration

The `freepod` realm — the realm Freepod end users authenticate against — is
declared as Terraform in `keycloak-config/`, using the `keycloak/keycloak`
provider. This is separate from the `keycloak/` module, which deploys the
Keycloak *server*; `keycloak-config/` configures what runs inside it.

What it manages:

- The `freepod` realm: registration open, email verification required,
  self-service password reset, the `freepod` login/email/account themes, and
  SMTP pointed at the in-cluster mailer relay.
- Clients `freepod-prod`, `freepod-dev` (per-environment, PKCE `S256`, direct
  access grants off) and `grafana`.
- Public clients `freepod-cli-prod` and `freepod-cli-dev` for external API
  clients: no secret, PKCE `S256` required, device authorization grant on,
  loopback redirect URIs.
- The `groups` client scope and its group-membership mapper.
- The `freepod-api-prod` / `freepod-api-dev` audience scopes, which put the
  environment's oauth2-proxy client ID into the access token's `aud` claim.
- Groups `freepod-dev` and `freepod-observability`.
- The `google` identity provider (Sign in with Google), below.

**Apply `tf/deps` before `tf/app`.** oauth2-proxy fails its readiness probe if
OIDC discovery does not resolve, so the realm, clients and scopes must exist
before the edge is configured to use them.

**Admin-console edits to any managed attribute are reverted on the next
`terraform apply`.** Change these in code.

Deliberately *not* managed, and safe to change by hand:

- **End-user accounts.** There is no `keycloak_user` resource. Users live in
  Keycloak's own Postgres, and self-registration causes no drift.
- **Group membership.** Terraform owns the groups, not who is in them.

### Sign in with Google

`keycloak-config/identity-providers.tf` registers Google on the realm, so every
client (both environments, the CLI, app-auth, Grafana) offers it on the login
page. The Google side is not in Terraform:

- **Where:** Google Cloud console, project `freepod`, Google Auth Platform.
  *Clients* holds the web client `Keycloak freepod realm`; *Branding* holds the
  consent screen (published and brand-verified, with the privacy policy and
  terms links pointing at `https://freepod.eu/legal/{privacy,terms}.md`, which
  Google's checker can read without running the SPA).
- **Credentials:** `google_client_id` / `google_client_secret` in
  `secrets.auto.tfvars`. Google shows a secret only once, at creation; to
  rotate, add a new secret to the client, update the tfvars, apply, then delete
  the old one.
- **Redirect URI:** `https://keycloak.freepod.eu/realms/freepod/broker/google/endpoint`,
  registered on the Google client. It is derived from the provider alias
  `google`, so renaming the alias breaks sign-in until the client is updated.

Behavior that is deliberate (openspec `keycloak-google-identity-provider`):

- `trust_email = true`: a first Google sign-in creates an account whose email
  is already verified.
- The stock `first broker login` flow: an email that already has an account
  must confirm the link and prove ownership (emailed link or password). Never
  switch to an auto-link flow; it lets a squatter's unverified account capture
  the real owner.
- `sync_mode = "IMPORT"`: Google attributes are copied once. `FORCE` would
  rewrite the email whenever the Google address changes, which moves the person
  to a new, empty Freepod account while the API resolves callers by email.

### Things that will bite you

- **`groups` is not a Keycloak built-in client scope.** Keycloak 24.0.5 ships
  ten default scopes and `groups` is not among them, so the scope and its
  mapper are declared here rather than merely attached. The mapper sets
  `full_path = false`, so the claim carries bare names (`freepod-dev`), which
  is what `allowed_groups` compares against.
- **The provider is pinned `~> 5.7.0`.** From 5.8.0 it unconditionally sends
  `bruteForceStrategy`, a field added in Keycloak 26; Keycloak 24.0.5 rejects
  the whole request with `400 unable to read contents from stream` and realm
  creation fails. Raise the cap only together with a Keycloak upgrade.
- **The realm carries two destroy guards.** `prevent_destroy` guards the plan
  but only while the resource block exists in the configuration;
  `terraform_deletion_protection` is enforced by the provider at the delete
  call and survives the block being removed. Deleting the realm on purpose
  means clearing both.
- **The `freepod-api-*` audience scopes are load-bearing for authentication.**
  A Keycloak access token otherwise carries `aud: ["account"]` and names the
  requesting client only in `azp`, which oauth2-proxy's audience check rejects.
  They are also what stops a dev token working on prod: both CLI clients
  register identical loopback redirect URIs, so `aud` is the only thing
  separating the environments. Never assign one environment's audience scope to
  the other's client, and never add them to `local.default_client_scopes` —
  that local is applied to every client, which would hand each one both
  audiences.
- **`kubectl rollout restart` is safe on the Keycloak deployment.** The
  `kubectl.kubernetes.io/restartedAt` annotation it writes is in
  `ignore_changes` (as on every deployment here), so the next apply does not
  restart the pod again. Keycloak does return `502 Bad Gateway` at the edge for
  roughly 25 seconds after the rollout reports Ready, so wait for
  `/realms/freepod/.well-known/openid-configuration` to answer before applying
  Keycloak provider resources.

### Reading client secrets

Secrets are generated by Keycloak and surfaced as outputs:

```bash
terraform output -raw freepod_dev_client_secret   # -> tf/app "default" key
terraform output -raw freepod_prod_client_secret  # -> tf/app "prod" key
```

The two root modules are deliberately not coupled with
`terraform_remote_state`; paste these into `tf/app/secrets.auto.tfvars`.


## Keycloak theming

Keycloak's login, account console and transactional emails are themed to match
the freepod.eu landing page (dark "digital sovereignty" look, Fraunces/Schibsted
Grotesk type, gradient CTAs).

### Where the theme lives

```
keycloak/theme/freepod/
  login/     # FreeMarker + CSS: sign-in, register, reset, OTP, errors
  account/   # PatternFly-v4 SPA skin: profile / "Personal info" pages
  email/     # FreeMarker: password reset, verify email, admin actions
```

Each type has its own `resources/` (the fonts are self-hosted per type, copied
from the UI's `@fontsource` packages — no Google Fonts calls). One stylesheet
per type rebrands every screen of that type, because all screens share the
type's `template.ftl`.

### How it's deployed (production)

The theme is **baked into the Keycloak image** rather than mounted (it's ~22
files / ~400KB — too much for a ConfigMap). `keycloak/Dockerfile` copies
`theme/freepod` onto `quay.io/keycloak/keycloak:24.0`, after a small build stage
that appends `?v=<content hash>` to each stylesheet in its theme's `styles`
line. Keycloak serves theme resources with a 30-day `max-age` under a path that
changes only with the Keycloak version, so without that hash browsers keep the
old CSS for a month after a theme change. Fonts and images referenced from the
CSS are not hashed: give a changed asset a new file name. Build, push and roll
out:

```bash
./scripts/build-images.sh --keycloak     # build + push ghcr.io/<owner>/caelus/keycloak
cd tf/deps && terraform apply            # if var.keycloak_image / digest changed
kubectl rollout restart deployment/keycloak -n keycloak
```

The deployment references `var.keycloak_image`
(default `ghcr.io/erikvanzijst/freepod/keycloak:latest`).

### Assigning the theme to the realm

Baking the theme into the image only makes it *available*; the realm must
select it. For the `freepod` realm this is **Terraform-managed** — see
`keycloak-config/realm.tf`:

```hcl
login_theme   = "freepod"
email_theme   = "freepod"
account_theme = "freepod"
```

Setting it by hand in the admin console (Realm settings → Themes) works, but
is reverted on the next `terraform apply`. For an unmanaged realm such as
`master`, set it manually:

```bash
kcadm.sh update realms/master -s loginTheme=freepod -s accountTheme=freepod -s emailTheme=freepod
```

### Local theme development

There is no Keycloak in the local dev stack, so iterate against a **throwaway
Keycloak container**. Two quirks of running Docker from inside the dev container
(sibling containers via the mounted Docker socket) shape the commands below:

- **Bind-mount sources are *host* paths**, not dev-container paths — so we mount
  the host directory backing `/workspace/src`.
- **Port publishing happens on the host**, where the dev container already owns
  the forwarded ports (`8501`, `8000`). So instead of `-p`, the throwaway
  containers **share the dev container's network namespace**
  (`--network container:<devcontainer>`) and listen on those ports directly.

```bash
DEVCTR=caelus-app-1   # this dev container, as the Docker host sees it
HOST_WS=$(docker inspect "$DEVCTR" --format \
  '{{range .Mounts}}{{if eq .Destination "/workspace/src"}}{{.Source}}{{end}}{{end}}')

docker run -d --name freepod-kc \
  --network "container:$DEVCTR" \
  -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=admin \
  -v "$HOST_WS/tf/deps/keycloak/theme/freepod:/opt/keycloak/themes/freepod:ro" \
  quay.io/keycloak/keycloak:24.0 \
  start-dev --http-port=8501 \
    --spi-theme-cache-themes=false --spi-theme-cache-templates=false \
    --spi-theme-static-max-age=-1
```

Then point the `master` realm at the theme and add a permissive client so the
login/account pages can be opened directly (`start-dev` uses an **in-memory DB**,
so this must be re-applied after every restart):

```bash
K="docker exec freepod-kc /opt/keycloak/bin/kcadm.sh"
$K config credentials --server http://localhost:8501 --realm master --user admin --password admin
$K update realms/master -s loginTheme=freepod -s accountTheme=freepod -s emailTheme=freepod \
    -s registrationAllowed=true -s resetPasswordAllowed=true
$K create clients -r master -s clientId=theme-preview -s enabled=true -s publicClient=true \
    -s standardFlowEnabled=true -s 'redirectUris=["*"]' -s 'webOrigins=["*"]'
```

Preview from the host (forwarded on `8501`):

- **Login** (and register / forgot-password): `http://localhost:8501/realms/master/protocol/openid-connect/auth?client_id=theme-preview&response_type=code&scope=openid&redirect_uri=http://localhost:8501/`
- **Account**: `http://localhost:8501/realms/master/account/` (sign in as `admin`/`admin`)

> **Caching gotcha.** Keycloak caches theme *resources* in memory even with
> `--spi-theme-cache-themes=false`. Login-CSS edits show on a normal reload, but
> account/email resource changes may keep serving stale bytes — recreate the
> container (`docker rm -f freepod-kc` + the `run` above) to flush, and add a
> `?cb=1` query to the URL so the browser refetches the new resource-version URL.

#### Previewing emails (Mailpit)

Emails are only produced by sending over SMTP — there's no in-browser preview.
Run [Mailpit](https://mailpit.axllent.org/) as a local SMTP sink (web inbox on
the forwarded `8000`):

```bash
docker run -d --name freepod-mailpit --network "container:$DEVCTR" \
  -e MP_SMTP_BIND_ADDR=0.0.0.0:1025 -e MP_UI_BIND_ADDR=0.0.0.0:8000 \
  axllent/mailpit
```

Point the realm's SMTP at it and give the test user an email address (kcadm
can't set the SMTP map, so use the REST API for that part):

```bash
TOKEN=$(curl -s -d client_id=admin-cli -d username=admin -d password=admin \
  -d grant_type=password \
  http://localhost:8501/realms/master/protocol/openid-connect/token | \
  python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -X PUT http://localhost:8501/admin/realms/master \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"smtpServer":{"host":"localhost","port":"1025","from":"no-reply@freepod.eu","fromDisplayName":"Freepod","ssl":"false","starttls":"false","auth":"false"}}'

AID=$($K get users -r master -q username=admin --fields id --format csv --noquotes | head -1)
$K update users/$AID -r master -s email=admin@freepod.eu -s emailVerified=true
```

Trigger sends, then read the rendered HTML at `http://localhost:8000`:

```bash
# password reset: use "Forgot Password?" on the login page, OR trigger admin emails:
curl -s -X PUT "http://localhost:8501/admin/realms/master/users/$AID/send-verify-email" \
  -H "Authorization: Bearer $TOKEN"
curl -s -X PUT "http://localhost:8501/admin/realms/master/users/$AID/execute-actions-email" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '["UPDATE_PASSWORD"]'
```

#### Cleanup

```bash
docker rm -f freepod-kc freepod-mailpit
```

## Notes

- Keycloak always uses the production domain (`keycloak.freepod.eu`).
- Echo uses `echo.freepod.eu`.
- This project must be deployed before `tf/app/`, since the app's
  OAuth2-proxy depends on a running Keycloak instance.
- Do NOT run `terraform destroy` here without understanding that it will
  take down Keycloak for all environments.
- A cluster-wide HSTS middleware (`headers-hsts`, `traefik.io/v1alpha1`) is
  defined in `system/hsts.tf` and attached as a default middleware on the
  `websecure` entrypoint only — see `system/helm/traefik/values.yaml.tftpl`.
  The `web` (:80) entrypoint is deliberately left untouched so ACME HTTP-01
  and the HTTP->HTTPS redirect are unaffected.
