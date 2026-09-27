# Verification on dev (2026-09-27)

Rolled out to dev: `tf/deps` (Keycloak clients), `tf/app` workspace `default`
(role bootstrap, app-auth 0.1.0, verifier URL), API `app-auth-dev-1`, chart
`custom:0.11.0` (template 150). Test apps, all copies of milk plus a `/whoami`
probe that echoes what the app received:

| Host | `auth` |
|---|---|
| milk-auth.fred.dev.freepod.eu | enabled, `public: ["^/whoami$"]` |
| milk-auth2.fred.dev.freepod.eu | enabled, `public: ["^/whoami$"]` |
| milk-noauth.fred.dev.freepod.eu | absent |

## 2.2 Role on dev

As `caelus_app_auth`, from a pod in `login-dev`: `app_auth_code` and
`deployment.hostname` readable; `UPDATE deployment`, `deployment.user_id` and
`deployment_var` all `permission denied`.

## 5.1 Broker and verifier exposure

`https://login.dev.freepod.eu/healthz` 200; `/verify` on the login host 404;
Service is ClusterIP. `/start` for `evil.example` renders the error page with no
redirect. `/start` for milk-auth redirects to Keycloak with `freepod-apps-dev`,
S256 PKCE, nonce, the single callback URI, and a sealed `__Host-freepod_flow_*`
cookie; Keycloak renders its sign-in form.

## 8.2 Spoofing through the edge

All seven identity headers (`X-Freepod-User/-Email/-Name/-Jwt`, `Remote-User`,
`X-Forwarded-User/-Email`) sent by the client:

- milk-noauth `/whoami`: none reached the app.
- milk-auth `/whoami` (public, no session): none reached the app.
- milk-auth `/whoami` with `Cookie: __Host-freepod_session=forged; theme=dark`:
  app received `cookie: theme=dark` only.
- milk-auth `/` navigation without session: 302 to the dev broker, with
  `__Host-freepod_login` set. `fetch` to `/api/items`: 401, app not reached.
