# app-auth-verifier Specification

## Purpose

The edge-side half of app authentication: decides, per request to an auth-enabled deployment, whether the request reaches the app and what identity it carries, and serves the reserved `/.freepod/auth/` paths on the app's own host.

## Requirements

### Requirement: Identity headers

For a request that carries a valid session, the verifier SHALL let the request through with exactly these identity headers set:

| Header | Value |
|---|---|
| `X-Freepod-User` | the user's Keycloak subject identifier |
| `Remote-User` | the user's Keycloak subject identifier |
| `X-Forwarded-User` | the user's Keycloak subject identifier |
| `X-Freepod-Email` | the user's verified email address |
| `X-Forwarded-Email` | the user's verified email address |
| `X-Freepod-Name` | the user's display name, percent-encoded UTF-8 |

The subject identifier MUST be stable for the lifetime of the user's Freepod account, including across email changes. The verifier MUST NOT pass any Keycloak token, or any other credential, to the app.

#### Scenario: Signed-in request

- **WHEN** a request with a valid session for Alice (subject `3f2a…`, email `alice@example.com`, name `Alice Ångström`) reaches an auth-enabled app
- **THEN** the app receives `X-Freepod-User: 3f2a…`, `Remote-User: 3f2a…`, `X-Forwarded-User: 3f2a…`, `X-Freepod-Email: alice@example.com`, `X-Forwarded-Email: alice@example.com` and `X-Freepod-Name: Alice%20%C3%85ngstr%C3%B6m`

#### Scenario: Email change keeps the user identifier

- **WHEN** Alice changes her Freepod email address and signs in to the same app again
- **THEN** `X-Freepod-User` carries the same value as before
- **AND** `X-Freepod-Email` carries the new address

### Requirement: Client-supplied identity headers never reach the app

Every identity header in the table above, and `X-Freepod-Jwt`, SHALL be removed from the incoming request before it reaches an auth-enabled app. The only values the app sees are the ones the verifier set. This SHALL hold on public paths and on requests without a session, where the app receives none of these headers.

#### Scenario: Spoofed header on a request without a session

- **WHEN** a request without a session sends `X-Freepod-Email: admin@example.com` to a public path of an auth-enabled app
- **THEN** the app receives no `X-Freepod-Email` header

#### Scenario: Spoofed header alongside a valid session

- **WHEN** a request with Alice's valid session also sends `X-Forwarded-User: bob`
- **THEN** the app receives `X-Forwarded-User` carrying only Alice's subject identifier

### Requirement: Platform cookies never reach the app

The verifier SHALL remove every cookie whose name starts with `__Host-freepod_` from the request before it reaches the app. It SHALL keep all other cookies unchanged, whether the session is valid, invalid, expired or absent. When no other cookies remain, the app SHALL receive no `Cookie` header. This SHALL hold however many `Cookie` header lines the request carries.

#### Scenario: Session cookie among app cookies

- **WHEN** a request carries `Cookie: __Host-freepod_session=…; theme=dark`
- **THEN** the app receives `Cookie: theme=dark`

#### Scenario: Only the session cookie

- **WHEN** a request carries only the session cookie
- **THEN** the app receives no `Cookie` header

#### Scenario: Cookies split across header lines

- **WHEN** a request carries `Cookie: theme=dark` and a second line `Cookie: __Host-freepod_session=…`
- **THEN** the app receives `Cookie: theme=dark` and nothing else

### Requirement: Session validity

A session SHALL be valid only when all of the following hold:
- the `__Host-freepod_session` cookie was issued by this environment's app authentication and has not been altered;
- it was issued for the exact host the request is addressed to;
- it has not expired.

A session SHALL expire no later than 7 days after issue. A session issued for one host SHALL NOT be accepted on any other host, including another host of the same owner. A session issued in one environment SHALL NOT be accepted in the other.

#### Scenario: Cookie replayed on another app

- **WHEN** a valid session cookie issued for `milk.erik.freepod.eu` is sent to `notes.erik.freepod.eu`
- **THEN** the verifier treats the request as having no session

#### Scenario: Expired session

- **WHEN** a session cookie issued 7 days and one minute ago is presented
- **THEN** the verifier treats the request as having no session

#### Scenario: Tampered cookie

- **WHEN** any byte of a session cookie's value is altered
- **THEN** the verifier treats the request as having no session

### Requirement: Public paths

A request whose path matches at least one of the deployment's declared public patterns SHALL reach the app without a session. When such a request carries a valid session, it SHALL carry the identity headers. Patterns SHALL use RE2 syntax, SHALL be matched against the URL path only (never the query string), and SHALL be unanchored unless the pattern anchors itself.

A pattern the verifier cannot compile SHALL make no path public; the remaining valid patterns still apply. Matching SHALL take time linear in the path length for any pattern.

#### Scenario: Anonymous landing page

- **WHEN** the deployment declares `public: ["^/$"]` and a request without a session asks for `/`
- **THEN** the request reaches the app with no identity headers

#### Scenario: Landing page for a signed-in user

- **WHEN** the same deployment receives a request for `/` with Alice's valid session
- **THEN** the request reaches the app with Alice's identity headers

#### Scenario: Query string cannot make a path public

- **WHEN** the deployment declares `public: ["^/static/"]` and a request without a session asks for `/admin?x=/static/`
- **THEN** the request is treated as a request to a protected path

#### Scenario: Invalid pattern fails closed

- **WHEN** the deployment declares `public: ["(?=x)", "^/$"]`
- **THEN** `/` is public and every other path requires a session

### Requirement: Unauthenticated requests to protected paths

When a request without a valid session addresses a path that is not public:
- A `GET` or `HEAD` request that is a top-level browser navigation SHALL receive a `302` redirect that starts sign-in. The original path and query SHALL be carried as the return target.
- Every other request SHALL receive `401` and SHALL NOT reach the app.

A browser navigation is a request with `Sec-Fetch-Mode: navigate`. When `Sec-Fetch-Mode` is absent, a request whose `Accept` header includes `text/html` counts as one.

#### Scenario: Browser opens a protected page

- **WHEN** a browser without a session navigates to `https://milk.erik.freepod.eu/lists/7?sort=name`
- **THEN** it receives a `302` that starts sign-in with return target `/lists/7?sort=name`

#### Scenario: Background request without a session

- **WHEN** a `fetch` from a page (`Sec-Fetch-Mode: cors`) without a session requests `/api/items`
- **THEN** it receives `401` and the app sees no request

#### Scenario: Form post after the session expired

- **WHEN** a browser submits a `POST` form navigation to a protected path with an expired session
- **THEN** it receives `401` and the app sees no request

### Requirement: Reserved sign-in paths

On every auth-enabled app host, the verifier SHALL answer every path under `/.freepod/auth/` itself, and none of them SHALL reach the app. At least these SHALL exist:
- `/.freepod/auth/login?rd=<path>`: starts sign-in and returns to `<path>` afterwards.
- `/.freepod/auth/callback`: completes sign-in (see *Sign-in completes on the app's own host*).
- `/.freepod/auth/logout?rd=<path>`: signs out (see *Logout ends the Freepod sign-in*) and returns to `<path>` afterwards.

Unknown paths under the prefix SHALL receive `404`. A return target SHALL be accepted only if it is a path on the same host: it starts with a single `/`, and is neither protocol-relative (`//`) nor a backslash variant. Otherwise the return target SHALL be `/`.

Every redirect the verifier issues SHALL use an absolute `https://` URL. Relative locations are not safe to use, because the edge resolves them against the verifier's own in-cluster address.

#### Scenario: App links to sign-in

- **WHEN** a page's "Sign in" link points at `/.freepod/auth/login?rd=/lists`
- **THEN** the browser starts sign-in and, once it completes, lands on `https://<host>/lists`

#### Scenario: Open-redirect attempt

- **WHEN** a request asks for `/.freepod/auth/login?rd=//evil.example/`
- **THEN** the return target becomes `/`

#### Scenario: Open-redirect attempt on logout

- **WHEN** a request asks for `/.freepod/auth/logout?rd=//evil.example/`
- **THEN** the return target carried through sign-out is `/`

#### Scenario: App cannot shadow reserved paths

- **WHEN** the app itself serves a route at `/.freepod/auth/login`
- **THEN** requests to that path never reach the app

### Requirement: Sign-in completes on the app's own host

A browser SHALL only be able to finish sign-in if it started it. When the verifier starts sign-in, it SHALL set a short-lived `__Host-freepod_login` cookie on the app's host. The code later redeemed at `/.freepod/auth/callback` SHALL be accepted only when all of the following hold:
- it was issued for this host;
- it has not been used before;
- it is no more than 60 seconds old;
- it matches that cookie.

A successful redemption SHALL set `__Host-freepod_session` with attributes `Secure; HttpOnly; SameSite=Lax; Path=/` and no `Domain`. It SHALL then clear `__Host-freepod_login` and redirect to the return target. A failed redemption SHALL NOT set a session.

#### Scenario: Normal completion

- **WHEN** the browser that started sign-in on `milk.erik.freepod.eu` arrives at the callback with a fresh code issued for that host
- **THEN** it receives a session cookie scoped to `milk.erik.freepod.eu` and is redirected to its return target

#### Scenario: Code replayed

- **WHEN** a code that has already been redeemed is presented again
- **THEN** no session is set

#### Scenario: Login CSRF

- **WHEN** an attacker gets a victim's browser to open a callback URL carrying a code the attacker obtained for their own account
- **THEN** no session is set, because the victim's browser does not hold the matching login cookie

#### Scenario: Code for another host

- **WHEN** a code issued for `milk.erik.freepod.eu` is presented at `notes.erik.freepod.eu/.freepod/auth/callback`
- **THEN** no session is set

### Requirement: Fail closed

If the verifier is unreachable or errors, requests to auth-enabled apps SHALL NOT reach the app. Deployments without authentication SHALL be unaffected by the verifier's availability.

#### Scenario: Verifier down

- **WHEN** the verifier is unavailable
- **THEN** requests to auth-enabled apps receive an error from the edge and the apps see no requests
- **AND** deployments without authentication keep serving normally

### Requirement: Logout ends the Freepod sign-in

`/.freepod/auth/logout` SHALL expire `__Host-freepod_session` on the requesting host. It SHALL then redirect the browser to the broker's sign-out for that host, carrying the return target, so that the user's Freepod sign-in at the identity provider ends as well (see the broker's *Signing out at the identity provider*). Once sign-out completes, the browser SHALL land on the return target on the same host.

Logout SHALL NOT expire sessions on other hosts. A user signed in to other apps SHALL stay signed in to them until those sessions expire or the user logs out of them.

After logout, the next sign-in on any app SHALL ask the user to authenticate at the identity provider, where they MAY choose a different account. Sign-ins after that one SHALL again need no interaction, as long as the new identity-provider sign-in lasts.

#### Scenario: Log out and sign in as someone else

- **WHEN** Alice, signed in to `milk.erik.freepod.eu`, opens `/.freepod/auth/logout?rd=/` and confirms signing out, and `/` is protected
- **THEN** she lands on the identity provider's sign-in form rather than back in the app as Alice
- **AND** signing in there as Bob returns her to `https://milk.erik.freepod.eu/` as Bob

#### Scenario: Other apps keep their session

- **WHEN** Alice, signed in to both `milk.erik.freepod.eu` and `notes.erik.freepod.eu`, logs out of `milk`
- **THEN** her session on `notes` still works

#### Scenario: One sign-in after logout

- **WHEN** Alice logs out of `milk`, signs in again, and later opens `docs.erik.freepod.eu`, an app she has no session for but has consented to
- **THEN** she reaches `docs` without entering credentials

#### Scenario: Logout with a public return target

- **WHEN** a deployment declares `public: ["^/$"]` and Alice opens `/.freepod/auth/logout?rd=/`
- **THEN** after signing out she lands on `https://<host>/` with no identity headers reaching the app

### Requirement: Allowed accounts

A deployment's edge configuration MAY say that the deployment's access list applies. When it does, a request carrying a valid session SHALL reach the app only when the session belongs to the deployment's owner or to an account the access list admits, on any path, public paths included. The owner SHALL be recognized by email, case-insensitively. Without that setting, every signed-in account is allowed, as before.

#### Scenario: Allowed account

- **WHEN** the access list applies, Alice is on it, and a request carries Alice's valid session
- **THEN** the request reaches the app with Alice's identity headers

#### Scenario: Owner

- **WHEN** the access list applies and is empty, and a request carries the owner's valid session
- **THEN** the request reaches the app with the owner's identity headers

#### Scenario: Other account

- **WHEN** the access list applies and a request carries the valid session of Bob, who is neither the owner nor listed
- **THEN** the request does not reach the app; a navigation receives the no-access page (see *The no-access page*), and any other request receives `403`

#### Scenario: Public path under an allow list

- **WHEN** the access list applies, `/` is public, and Bob's valid session asks for `/`
- **THEN** the request does not reach the app

#### Scenario: Anonymous request under an allow list

- **WHEN** the access list applies and a request without a session asks for a public path
- **THEN** the request reaches the app with no identity headers

#### Scenario: Preview hostname

- **WHEN** the access list of `studio-alice.freepod.app` applies and Bob's valid session asks for `preview-studio-alice.freepod.app`
- **THEN** the request does not reach the preview

### Requirement: An unreadable allow list admits no one

If the verifier cannot read a deployment's access list, it SHALL keep using the last copy it read, however old. If it has never read one since it started, it SHALL admit no signed-in account to that deployment until it can.

#### Scenario: Database outage

- **WHEN** the database becomes unreachable while the verifier holds a copy of a deployment's list
- **THEN** it keeps admitting and refusing by that copy

#### Scenario: Corrupt list

- **WHEN** the edge configuration's setting for the access list has a value the verifier does not recognize
- **THEN** signed-in requests are refused as for an account not on the list

#### Scenario: Started during an outage

- **WHEN** the verifier starts while the database is unreachable, and a signed-in request arrives for a deployment whose access list applies
- **THEN** the request is refused as for an account not on the list

### Requirement: The no-access page

A refused navigation SHALL receive `403` with a page in the look of the platform's placeholder page for a deployment without an app. It SHALL name the application and its address (`https://<host>`), say that it is open only to the people its owner has added and that the signed-in account (by email) is not among them, suggest asking whoever shared the link to add that address, and offer signing out to switch accounts. The application's name SHALL come from the edge configuration when present, and otherwise be the host. The broker SHALL show the same page, with the application named by its host, when it refuses someone at sign-in; there its sign-out link SHALL end the identity provider's session.

#### Scenario: Named application

- **WHEN** the edge configuration names the application "App Studio" and Bob is refused on `studio.alice.freepod.eu`
- **THEN** the page names "App Studio" and `https://studio.alice.freepod.eu`, says `bob@example.com` has no access, and links to sign out

#### Scenario: Unnamed application

- **WHEN** the edge configuration gives no name and Bob is refused on `notes.alice.freepod.eu`
- **THEN** the page names the application as `notes.alice.freepod.eu`

### Requirement: Requests other origins' pages start are not identified
The verifier SHALL treat a state-changing request (a method other than `GET`,
`HEAD` or `OPTIONS`, or a WebSocket handshake) as carrying no session when a
browser started it from a page on another origin. `Sec-Fetch-Site` decides when
present, and `Origin` otherwise; a request with neither is judged by its
session alone.

#### Scenario: A state-changing request from another origin's page
- **WHEN** a request with a valid session for `<host>` has method `POST` and `Sec-Fetch-Site: same-site`
- **THEN** the verifier answers `401` and sets no identity header

#### Scenario: The same request from the app's own page
- **WHEN** the request instead carries `Sec-Fetch-Site: same-origin`
- **THEN** the verifier answers `200` with the session's identity headers

#### Scenario: Only Origin is present
- **WHEN** a `PUT` with a valid session carries no `Sec-Fetch-Site` and an `Origin` other than `https://<host>`
- **THEN** the verifier answers `401` and sets no identity header

#### Scenario: A WebSocket handshake from another origin
- **WHEN** a handshake with a valid session carries `Sec-WebSocket-Key` and an `Origin` other than `https://<host>`
- **THEN** the verifier answers `401` and sets no identity header
- **AND** a handshake is recognized by `Sec-WebSocket-Key` or `Sec-Fetch-Mode: websocket`, since Traefik removes `Upgrade` before forward-auth

#### Scenario: A non-browser client
- **WHEN** a state-changing request with a valid session carries neither `Sec-Fetch-Site` nor `Origin`
- **THEN** the verifier answers `200` with the session's identity headers

#### Scenario: A public path
- **WHEN** a state-changing request from another origin's page targets a public path
- **THEN** it passes with no identity header, as an unauthenticated request would

#### Scenario: Reads are unaffected
- **WHEN** a `GET` that is not a WebSocket handshake carries `Sec-Fetch-Site: same-site`
- **THEN** the session is honored as for any other request

### Requirement: List changes reach the verifier within 30 seconds

The verifier SHALL apply an access list no older than 30 seconds. When it is about to refuse a signed-in request and its copy of the list is more than 5 seconds old, it SHALL read the list again before deciding. Neither SHALL need a reconcile or a restart.

#### Scenario: Removal

- **WHEN** the owner removes Ana from a `listed` header app while Ana has a valid session
- **THEN** within 30 seconds Ana's requests are refused

#### Scenario: Addition just before signing in

- **WHEN** the owner adds Noor, and Noor signs in and opens the app within the next few seconds
- **THEN** Noor's requests reach the app
