## Why

`custom` deployments get object storage, a database and a hostname for free, but not users: every app that needs to know who is calling (milk, the shopping list app, is the first) has to build signup, login, password reset and email verification itself, and every end user needs a new account per app. Freepod already runs an identity provider with open registration and verified emails. Offering it to `custom` apps as an opt-in edge feature gives developers authentication for one line of configuration, and brings every app's users onto Freepod accounts.

## What Changes

- A new platform service, **`app-auth`** (Go, `app-auth/`), with two roles:
  - **Verifier**: the Traefik forward-auth endpoint for auth-enabled deployments. It validates a per-app session cookie and answers with identity headers, a redirect to login, or a 401.
  - **Broker**: served on the environment's login host (`login.freepod.eu` / `login.dev.freepod.eu`, both already reserved). It is the only party that talks OIDC to Keycloak. It checks that the requesting host is an auth-enabled deployment, shows a per-app consent screen on first use, and hands the app's host a single-use code that the app's host redeems for its own session cookie.
- **Opt-in through `.freepod.json`**: the `custom` template's values schema gains an `auth` block (`{"enabled": true, "public": ["^/$", "^/static/"]}`) carried in `user_values` like `hostname`. There is no new API, CLI flag or UI.
- **Identity headers**: `X-Freepod-User` (the Keycloak subject), `X-Freepod-Email`, `X-Freepod-Name`, and the conventional `Remote-User` / `X-Forwarded-User` (subject) and `X-Forwarded-Email` (email). The edge removes client-supplied copies of all of them on **every** `custom` deployment, including ones that have not opted in.
- **The session cookie never reaches the app**: the verifier strips it from the request before it is forwarded to the app.
- **Public paths**: requests matching an RE2 regex in `auth.public` pass without a session, and still carry identity when a session exists.
- **Access gate v1 = any Freepod account.** Authorization is the app's job.
- The `custom` chart renders the forward-auth middleware when `auth` is set, and the header-stripping middleware always. The reconciler injects the verifier's address.
- **Keycloak** gains one client per environment (`freepod-apps-prod`, `freepod-apps-dev`) with a single redirect URI on the login host. There are no per-deployment clients.
- A signed identity JWT (`X-Freepod-Jwt`) is designed but **not shipped** in this change.
- The privacy policy (and DPA where relevant) in `legal/` gain disclosure that Freepod shares a user's identity with the operator of an app the user signs in to. The deploy skill documents the feature.

## Capabilities

### New Capabilities

- `app-auth-verifier`: the forward-auth contract: session validation, the identity header set, cookie stripping, public paths, redirect vs 401, and the reserved `/.freepod/auth/` paths served on every auth-enabled app host.
- `app-auth-broker`: the login host: OIDC with Keycloak, host eligibility, consent, single-use code handoff, session lifetime and silent renewal, and logout.
- `app-auth-chart-contract`: what the `custom` chart and the reconciler must render and inject for authentication: the `auth` values schema, the forward-auth middleware, and unconditional stripping of identity headers.
- `app-auth-data-model`: the consent and one-time code tables, and the narrowly scoped database role `app-auth` connects as.

### Modified Capabilities

- `keycloak-terraform-config`: declares the per-environment `freepod-apps-*` clients used by the broker.

## Impact

- **New code**: `app-auth/` (Go service, container image, CI), Alembic migration for the new tables, a bootstrap SQL + Terraform for its database role (the same shape as `ssh-resolver-role.tf`), and Terraform for its Deployment, Service, secrets and the login host's IngressRoute (`tf/app`).
- **Keycloak**: two new clients in `tf/deps/keycloak-config/clients.tf`; the secrets are surfaced through outputs like the existing clients.
- **`custom` product**: new chart version (middlewares + ingress annotation) and a new values schema in `products/catalog/custom.yaml`.
- **API**: `reconcile.py` injects `caelus.appAuth` into chart values. The Caelus API's own authentication (oauth2-proxy, `X-Auth-Request-Email`) is unchanged.
- **Docs**: `cli/src/freepod/assets/SKILL.md` (deploy skill) and `AGENTS.md` architecture notes.
- **Legal**: the privacy policy, the DPA (new clause 2.5) and the Terms (new section 8.5) under `legal/`, all at 2026-09-27. The DPA is versioned alongside the Terms, so `current_tos_version` moves too, and **every user re-accepts the Terms before their next deploy**.
- **Operations**: every request to an auth-enabled app takes one extra in-cluster hop through the verifier. If the verifier is unavailable, auth-enabled apps fail closed, and apps that have not opted in are unaffected.
