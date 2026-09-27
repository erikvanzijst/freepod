## Context

See proposal.md for why. The facts this design rests on:

- **Freepod already runs the identity provider.** Keycloak realm `freepod` has open registration, `verify_email = true` and `duplicate_emails_allowed = false` (`tf/deps/keycloak-config/realm.tf`). A verified email identifies exactly one account.
- **The platform's own login is oauth2-proxy behind Traefik forward-auth** (`tf/app/login`). Its cookie is deliberately host-only on the apex so it never reaches tenant subdomains, which run untrusted code. The Caelus API trusts `X-Auth-Request-Email`, and oauth2-proxy also accepts bearer tokens for the `freepod-*` clients.
- **`custom` apps are served by a plain `networking.k8s.io/v1` Ingress** in the tenant namespace, driven by the reconciler-injected `caelus.ingress` block (`products/custom/chart/templates/ingress.yaml`, `reconcile.py:_build_ingress_overrides`). Each deployment has exactly one hostname (`deployment.hostname`): either `<app>.<sub>.<domain>` under the wildcard domain, or a custom domain with its own cert-manager certificate.
- **`user_values` flows from `.freepod.json` into chart values**, validated against the template's closed `values_schema`. That makes an opt-in there free of any API or CLI change.
- **Tenant namespaces deny all ingress except from Traefik, sshpiper (sidecar port only) and the namespace itself** (`network_policy.py`). The one known gap is the NetworkPolicy startup window on freshly started pods.
- **`login.freepod.eu` and `login.dev.freepod.eu` are already reserved hostnames** (`tf/app/variables.tf`), and the `login` / `login-dev` namespaces exist.
- **Traefik forward-auth behavior, verified against a local Traefik v3.5.3 and its source:**
  1. Every header listed in `authResponseHeaders` is deleted from the request, then copied from the auth response only if present there. Listing `Cookie` therefore lets the auth server rewrite the cookies the app receives, and removes all `Cookie` lines when it returns none.
  2. A non-2xx auth response is returned to the client, with its body, `Location` and every `Set-Cookie`.
  3. Without `preserveLocationHeader`, a relative `Location` is resolved against the auth server's address. `/list` came back as `http://127.0.0.1:9001/list`.
  4. With `trustForwardHeader` unset, `X-Forwarded-Host` / `-Uri` / `-Proto` are always set from the actual request, never copied from the client.
- **Keycloak cannot express the redirect URIs per-app OIDC would need.** Its subdomain wildcard matches exactly one DNS label, so it cannot cover `<app>.<sub>.freepod.eu`, and it cannot cover custom domains at all.
- **The SSH auth resolver sets the precedent** for a small Go service that answers an edge's per-request question from the platform's own rows under a dedicated least-privilege role (`ssh-auth/`, `tf/app/caelus/ssh-resolver-role.tf`).

## Goals / Non-Goals

**Goals:**

- Adding one `auth` block to `.freepod.json` gives an app verified identity headers. The developer needs no library, no client registration and no secrets.
- Nothing in Keycloak or the cluster grows per deployment beyond the deployment's own Ingress middlewares.
- An app operator can never obtain a credential usable anywhere except on their own app.
- The per-request path touches no database.

**Non-Goals:**

- **Authorization of any kind:** allowlists, owner-only mode, roles. Specs make "any verified Freepod account" the v1 gate; a gate can be added as its own change.
- **The signed identity JWT (`X-Freepod-Jwt`).** D9 designs it so the header contract doesn't need to change later. This change only reserves and strips the header.
- **Non-browser clients**, meaning bearer tokens for apps' APIs. They get `401`.
- **Revoking consent from the UI.** Revoking consent can't recall data the app already received. It only stops future disclosure, which account deletion already does. A consent list in account settings is a natural follow-up.
- **Single logout across apps and Keycloak.**
- **Products other than `custom`.** Curated products bring their own authentication.

## Decisions

### D1: An identity-aware proxy, not OIDC clients handed to apps

The alternative, provisioning a Keycloak client per deployment and injecting `OIDC_*` vars like database credentials, is portable and standard. But every app would need an OIDC library, a callback route, session handling and secret storage. That is exactly the work this feature exists to remove. Header-based identity has proven itself as a platform feature: Google IAP, Cloudflare Access, Azure Easy Auth, Tailscale Serve and Sandstorm all offer it, and to an app it is reading one header. Per-app OIDC clients stay possible later for apps that want them. They don't conflict with this design.

### D2: One central broker with a code handoff, not oauth2-proxy

Rejected alternatives:

- **One shared oauth2-proxy with a redirect URI derived from the request host.** It needs per-host redirect URIs in Keycloak, which the Context section shows Keycloak can't express. Worse, oauth2-proxy sessions aren't tied to a host: all apps would share one cookie secret, so a session cookie taken from one app would be valid on every other app.
- **One oauth2-proxy per deployment.** That fixes the replay problem, but costs thousands of pods and still needs a Keycloak client or redirect URI per host.
- **Pomerium.** It is the reference design for this flow (central authenticate service, per-route sessions, cookie stripping, custom claim header names via `jwt_claims_headers`, RE2 path routes). It was rejected on fit, not quality:
  - it removed forward-auth in v0.21, and its ingress controller cannot run behind another ingress controller (pomerium/ingress-controller#132 is open), so it would either become a second edge beside Traefik (per-host routing in the homelab HAProxy) or run as Pomerium Core behind Traefik with routes we generate from the database, a cross-namespace hop and a NetworkPolicy change admitting a second proxy into every tenant namespace;
  - it has no per-app consent, so the consent service and its table would exist anyway;
  - "public, but identified when signed in" is undocumented for its public-access routes;
  - it adds Envoy to the data path and a session store that needs Postgres once replicated.

  What it would replace is the flow glue on top of `go-oidc`, `x/oauth2` and the standard library's HMAC. Revisit if the edge moves off Traefik, or when rich per-app policy (allowlists, groups) is wanted.

Chosen: the flow Cloudflare Access and Pomerium use. A central broker on the login host holds the only Keycloak client (per environment) with a single redirect URI. It hands the app's host a single-use code, and the app's host exchanges that code for its own host-only cookie. Custom domains need no special handling, because the cookie is always set by the host it belongs to.

```
browser                 Traefik+verifier (app host)           broker (login host)        Keycloak
  │ GET /lists ───────────▶ no session, navigation
  │ ◀── 302 login.freepod.eu/start?host&rd&state, Set-Cookie __Host-freepod_login
  │ GET /start ───────────────────────────────────────────────▶ host eligible? (DB)
  │ ◀──────────────────────────────────────────────────────────  302 authorize (PKCE)
  │ ────────────────────────────────────────────────────────────────────────────────▶ SSO / login / register
  │ ◀──────────────────────────────────────────────────────────────────────────────── 302 /callback?code
  │ GET /callback ────────────────────────────────────────────▶ token exchange, email_verified,
  │                                                              eligible again?, consent? (DB)
  │ ◀── 302 https://<host>/.freepod/auth/callback?code=<one-time> ── code row (DB)
  │ GET /.freepod/auth/callback ─▶ verifier redeems code (DB), checks login cookie
  │ ◀── 302 https://<host>/lists, Set-Cookie __Host-freepod_session
  │ GET /lists ───────────▶ session ok → app gets X-Freepod-* headers
```

### D3: One Go service, `app-auth`, with two roles

The verifier and the broker share the session format, the code table and the signing key. Splitting them would split a single security boundary across two deployables. Both roles run in one Go binary deployed in the `login` / `login-dev` namespace, with separate HTTP listeners:
- one reachable only in-cluster by Traefik (`/verify`);
- one exposed on the login host through an IngressRoute (the broker).

Why Go:
- It is the hot path for every auth-enabled request.
- RE2 is Go's native regexp engine, which gives user-supplied patterns linear-time matching (D6).
- `ssh-auth/` is already the model to copy.

Why not the Caelus API: its security model is "trust `X-Auth-Request-Email`". Hosting a second, independent authentication path inside that process, with its broad database role, puts two trust models in one process for no benefit.

### D4: Sessions are signed, host-bound cookies. The per-request path is stateless.

- **Cookie:** `__Host-freepod_session` holds `{sub, email, name, host, iat, exp}`, sealed with AES-256-GCM under a per-environment key, with the key derived per purpose (session, broker flow, pending consent) so a value sealed for one purpose never opens as another. Authenticated encryption rather than a bare HMAC because the broker's in-flight state, sealed the same way, carries a PKCE verifier that must stay secret; one primitive serves both. `/verify` checks the MAC, `host == X-Forwarded-Host` and `exp`, and needs no database.
- **Key rotation:** the key is a small keyring (current key plus optionally the previous one), verified by key id. Rotating invalidates at most one 12-hour generation of sessions.
- **No sliding refresh inside the cookie.** A new session always comes from a new pass through the broker, so account deletion and disabling take effect within 12 hours at worst.

The host check relies on context fact 4: with `trustForwardHeader` unset, `X-Forwarded-Host` is the request's real `Host`, which the Ingress rule already matched to the deployment. **`trustForwardHeader` must stay unset;** a comment in the chart says so.

### D5: The verifier rewrites `Cookie` through `authResponseHeaders`

The middleware lists these in `authResponseHeaders`:
- `Cookie`;
- all seven identity headers (the six from the verifier spec plus `X-Freepod-Jwt`).

`/verify` parses every `Cookie` line, drops names prefixed `__Host-freepod_`, and returns the rest as one `Cookie` header, or nothing when nothing is left. Because Traefik deletes before it copies (context fact 1), the app sees only what the verifier chose. An app never receiving the session cookie is stronger than the host binding alone. We keep both, because the binding also protects against a route that loses its middleware through misconfiguration.

### D6: Deployment config travels in the middleware's forward-auth URL

The chart renders the forward-auth address as `<verifyUrl>?p=<base64url(JSON public patterns)>`. `/verify` compiles and caches patterns keyed by that string. So the per-request decision needs no database lookup and no config-sync machinery.

This is safe to trust because only the reconciler (`verifyUrl`) and the schema-validated values (`public`) shape it. Tenants have no Kubernetes API access. Patterns are RE2, so no pattern can make matching slower than linear. A pattern that fails to compile is logged and ignored (fail closed, per spec). The broker, which is not per-request, reads eligibility from the database, from the **applied** release (`deployment.applied_release_id → deployment_release.values_json->'auth'->>'enabled'`, joined to the product slug) rather than the desired `deployment.user_values_json`: the edge enforces what the applied release rendered, and the broker must agree with it while a release is rolling out.

### D7: Reserved paths live inside forward-auth

`/.freepod/auth/login`, `/callback` and `/logout` need no separate route or Service in the tenant namespace. The verifier recognizes them from `X-Forwarded-Uri` and answers with a non-2xx response (302/404), which Traefik relays with its `Set-Cookie` headers (context fact 2). Every `Location` is built as `https://<X-Forwarded-Host>/…` (context fact 3) rather than relying on `preserveLocationHeader`, so correctness doesn't depend on a middleware flag.

Login CSRF is prevented with the `__Host-freepod_login` cookie. It holds a random nonce the verifier sets when it redirects to the broker. The broker binds the code to the nonce's hash, and redemption requires the matching cookie.

### D8: Codes and consent live in the platform database

- **Codes:** the broker inserts `app_auth_code(code_hash, host, subject, email, name, return_path, nonce_hash, expires_at)`. The verifier redeems with `DELETE … WHERE code_hash = $1 AND expires_at > now() RETURNING …`, which is atomic single use without locks.
- **Consent:** `app_auth_consent(subject, deployment_id, claims text[], granted_at)`; the broker asks again when it would disclose a claim outside `claims` with a primary key on `(subject, deployment_id)`, inserted `ON CONFLICT DO NOTHING`.
- **Keys:** consent is keyed by Keycloak `sub`, with no foreign key to `user`. App users are Keycloak accounts that may never have a platform user row. `sub` is also the identifier the `keycloak-subject-join-key` change is moving the platform toward.
- **Migrations and role:** the Alembic migration lives in `api/`, as all migrations do. The role `caelus_app_auth` mirrors `caelus_ssh_resolver`: column-level `SELECT` on exactly the eligibility query's columns (`deployment`, `deployment_release`, `product_template_version`, `product`) plus `SELECT, INSERT, DELETE` on the two tables. A bootstrap SQL script re-applied on every rollout after `alembic upgrade head` creates it.
- **Cleanup:** expired codes are deleted by the service itself on a timer. A dedicated worker isn't worth it.

### D9: The deferred JWT is designed now

When shipped, `X-Freepod-Jwt` is:
- an ES256 JWS with claims `{iss: https://login.<domain>, aud: <deployment id>, sub, email, email_verified, name, iat, exp: iat+300}`;
- verifiable against keys published at `https://login.<domain>/.well-known/jwks.json`.

`aud` is the deployment ID, injected into the pod as `FREEPOD_DEPLOYMENT_ID`, not the host. An app comparing `aud` against the request's `Host` would accept a token from another app sent straight to its pod with a matching `Host`. This change only reserves and strips the header, so shipping the JWT later is purely additive.

### D10: Conventional header aliases

`Remote-User` and `X-Forwarded-User` carry the Keycloak subject, and `X-Forwarded-Email` the email. There is no single standard for trusted-header auth: Grafana and Gitea default to `X-WEBAUTH-USER`, and most such apps let the header name be configured. These aliases cover the common defaults. Every "user" header carries the stable subject, never the email, so apps that create accounts keyed on the user header survive email changes.

## Risks / Trade-offs

- **[The verifier is on every auth-enabled request]** Two replicas, a PodDisruptionBudget, and a pure-CPU `/verify` (one HMAC plus a cached regex). Failure is closed for opted-in apps and invisible to everyone else.
- **[A route that forwards to the app without the middleware]** Header stripping (always on) and the host-bound cookie limit what leaks. The chart has a single Ingress, and a chart unit test asserts every rendered route carries both middlewares. The deferred JWT is the full answer for apps that want to verify identity themselves.
- **[Deployments created before chart 0.11.0 have no strip middleware]** A new catalog template does not re-render existing deployments; each moves to it on its next `freepod deploy`. Opting in requires a deploy, so every auth-enabled app is on the new chart, and an app that predates the feature has no reason to read the headers. Observed on dev: `paste.fred.dev.freepod.eu` (untouched) renders no middleware; freshly deployed copies with and without `auth` both strip.
- **[NetworkPolicy startup window]** A freshly started app pod may briefly accept in-cluster traffic that bypasses Traefik, and with it spoofed headers. The exposure is about 20 seconds per rollout, and the fix belongs to the separate NetPol change already pending. The JWT covers it for apps that care.
- **[Form POST after expiry gets a 401 and loses the body]** This is inherent to redirect-based login. 12-hour sessions make it rare, and apps can link to `/.freepod/auth/login`.
- **[Owner reads users' emails]** That is the purpose of the feature. It is gated by explicit per-app consent and disclosed in the privacy policy.
- **[Deleted-account sessions live up to 12 h]** This is accepted. The alternative is a revocation check on the hot path.
- **[Invalid public regex gives the developer no feedback]** It fails closed. The `freepod` CLI validates patterns with an RE2-compatible check before deploying, as a courtesy; the verifier stays the authority.

## Migration Plan

Purely additive: no existing deployment changes behavior until its owner opts in.

1. Keycloak clients (`tf/deps`), then paste the secrets into `tf/app/secrets.auto.tfvars`.
2. Migration plus role bootstrap. `app-auth` Deployment, Service and IngressRoute for the login host (`tf/app`). Session key Secret.
3. Reconciler injects `caelus.appAuth.verifyUrl`, and API settings gain `app_auth_verify_url`.
4. New `custom` chart version and catalog `values_schema`. Existing deployments pick up the strip middleware on their next reconcile.
5. Deploy skill and privacy policy updates. Enable on milk as the first user.

Rollback: set `auth.enabled: false` (per app), or revert the catalog to the previous chart version (fleet-wide). The broker and verifier can then be removed without affecting anything else.

## Open Questions

- The consent page's copy and whether it carries Freepod branding beyond the Keycloak theme. This is presentation only.
- The session-key rotation cadence, which is an operational choice.
