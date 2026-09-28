## Context

See proposal.md for why. Today's logout lives entirely in the verifier (`app-auth/verify.go`, the `reservedPrefix + "logout"` case): it clears `__Host-freepod_session` and redirects absolutely to `https://<host><rd>`. The broker is the only component that talks OIDC to Keycloak (design D2/D3 of the archived `app-authentication` change), through `freepod-apps-{prod,dev}`. It discovers the provider lazily with go-oidc and keeps no tokens.

Facts checked against production Keycloak 24.0 (`https://keycloak.freepod.eu/realms/freepod`) while writing this:
- Discovery publishes `end_session_endpoint` = `…/protocol/openid-connect/logout`.
- With `client_id` + a registered `post_logout_redirect_uri` + `state`, and no Keycloak session cookie, the endpoint answers `302` straight to `<post_logout_redirect_uri>?state=<state>`.
- With an unregistered `post_logout_redirect_uri` (today's `freepod-apps-prod`), it renders an "Invalid redirect uri" error page.
- Per Keycloak's documented behavior since 18, a request *with* a live session but without `id_token_hint` shows a "Do you want to log out?" confirmation before redirecting. We haven't observed this on prod (it needs a signed-in browser). Task 5.2 checks it.

The console already does a full Keycloak logout through oauth2-proxy (`logout-infrastructure` spec), so ending the Keycloak session from an app isn't a new kind of event for users.

## Goals / Non-Goals

**Goals:**
- Logout on an app gives the user a real chance to authenticate again, as any account.
- Keep the verifier free of OIDC and free of database access on its hot path.
- No open redirect through either new broker route.

**Non-Goals:**
- Ending other apps' sessions (single logout across apps). Their host-bound cookies stay valid. The verifier never consults Keycloak, and propagating logout would need a session store we deliberately don't have.
- Front- or back-channel logout notifications from Keycloak to the broker.
- A way to switch accounts *without* ending the Keycloak session (`prompt=login`). It was considered below and isn't needed once logout works.
- Ending the console's oauth2-proxy session. Keycloak ends only its own SSO session. The console's cookie is untouched, as other apps' cookies are.

## Decisions

### D1: The verifier hands off to the broker; the broker talks to Keycloak

`/.freepod/auth/logout?rd=<path>` clears the host session exactly as today, then redirects to `https://login.<domain>/logout?host=<host>&rd=<safe rd>`. The verifier builds this from `loginURL`, as it already does for `/start`.

*Alternative: the verifier redirects to Keycloak itself.* That would put the Keycloak issuer, client ID and discovery into the verifier, which today knows nothing about OIDC. It would also need the post-logout redirect URI to be per app host, which means one registered URI per deployment (forbidden by `keycloak-terraform-config`: the client count and its URIs must not grow with deployments). Keeping OIDC in the broker keeps one fixed URI.

### D2: Host and return target travel in a sealed `state`, not a cookie

`/logout` checks eligibility with the same `eligible()` call sign-in uses, and answers any other host with the existing error page and no redirect. It then seals `{host, rd}` with the keyring under a new purpose, `"logout"`, with a 10-minute TTL. It redirects to the discovered `end_session_endpoint` with `client_id`, `post_logout_redirect_uri=https://login.<domain>/signed-out` and `state=<sealed>`. `/signed-out` opens `state` and redirects to `https://<host><safeReturnPath(rd)>`.

*Why `state` and not a login-host cookie like the sign-in flow cookie?* Keycloak hands `state` back verbatim (verified above), and sealing makes it unforgeable. The per-purpose key derivation means a sealed flow, session or consent value can't be replayed as a logout state. No cookie also means nothing to clean up, and no collision between tabs.

*Why re-check `safeReturnPath` on the way out?* The value was sanitized before sealing, but the check is cheap. It keeps `/signed-out` safe on its own, even if a future change seals something else.

`/signed-out` doesn't re-check eligibility. The host was eligible within the last 10 minutes and the redirect goes to that exact host, which Freepod served moments ago. If the deployment has since been deleted, the browser gets a DNS or edge 404, not an attacker's page.

An absent, invalid or expired `state` renders a `done`-kind page: "You're signed out of Freepod". It has no link, because without a trusted host there's nowhere safe to link to.

### D3: Accept Keycloak's confirmation page instead of keeping ID tokens

Skipping the confirmation needs `id_token_hint`, so the broker would have to keep each user's ID token. The session cookie can't carry it: `__Host-freepod_session` is per app host and the broker never sees it, and adding a JWT would bloat every app request. A broker-side store would contradict the "tokens are not persisted" requirement. The confirmation page is themed (`login_theme = "freepod"`), costs one click, and makes signing out of Freepod an explicit act. It also blunts logout CSRF: a cross-site link can end the app session but can't silently end the Keycloak one.

### D4: End-session URL from discovery, behind the `authenticator` interface

`authenticator` gains `endSessionURL(state, postLogoutRedirect string) (string, error)`. `oidcAuth` reads `end_session_endpoint` from the provider's discovery claims (go-oidc exposes them through `Provider.Claims`) and appends `client_id`, `post_logout_redirect_uri` and `state`. If discovery fails or the endpoint is absent, the broker shows the existing "temporarily unavailable" page. The app session is already gone at that point, which is acceptable: the user retries.

### Alternative considered: `prompt=login` instead of ending the Keycloak session

Logout could land on a signed-out page whose "sign in again" link forces Keycloak's credential form with `prompt=login`, leaving the Keycloak session alone. That's a new flag threaded through `/login`, `/start` and the flow cookie, plus a new page in the verifier. Logout would still be a no-op for anyone who just wants to be signed out, since the next visit silently signs them in. Ending the Keycloak session fixes both cases with less surface. It costs one extra credential prompt on the next sign-in to any app, and after that the Keycloak session is back.

## Risks / Trade-offs

- [Image rolls out before the Keycloak client has the post-logout URI] → Every logout hits Keycloak's "Invalid redirect uri" page. Mitigation: the `tf/deps` apply is a separate, earlier task. The redirect URI is fixed, so it can be registered well before the image ships.
- [Logout CSRF: any site can link to `/.freepod/auth/logout`] → The app session ends, as it can today. The Keycloak session survives unless the user clicks "Log out" on Keycloak's confirmation. Same exposure as before for the app. No new exposure for Keycloak.
- [User signs back in as Bob while other apps still hold Alice's session] → Expected, and stated in the verifier spec. Each app keeps its own session until it expires or the user logs out there.
- [`state` in a URL can end up in logs and history] → It's sealed (AES-GCM) and holds only a hostname and a path, both already in the app URL. It expires after 10 minutes.
- [Keycloak omits `state` on some path, e.g. an error] → `/signed-out` shows the plain signed-out page. The user is signed out and can navigate back themselves.

## Migration Plan

1. Apply `tf/deps` with `valid_post_logout_redirect_uris` on both app clients. This is harmless on its own: the current image never calls end-session.
2. Build and push a new `app-auth` version (`VERSION` bump, never overwrite a tag), repoint `tf/app`, and apply dev, then prod.
3. Verify on dev with a signed-in browser: logout → Keycloak confirmation → login form → sign in as another account → back on the app as that account.
4. Ship the SKILL.md wording with the next CLI release.

Rollback: repoint `tf/app` to the previous `app-auth` version. The extra post-logout URI on the Keycloak client is inert without the new image and can stay.
