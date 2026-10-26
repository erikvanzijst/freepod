## ADDED Requirements

### Requirement: The starter refuses data changes from other origins' pages

An app made from the starter SHALL answer `403` to a `POST`, `PUT`, `PATCH` or `DELETE` request whose `Sec-Fetch-Site` is present and neither `same-origin` nor `none`, or, without `Sec-Fetch-Site`, whose `Origin` names a host other than the request's `Host`. A request with neither header SHALL pass, as SHALL every `GET`, `HEAD` and `OPTIONS`. This SHALL hold in production and in the preview.

#### Scenario: The app's own page changes data

- **WHEN** a page of the app sends a `POST` to its API
- **THEN** the request reaches the route

#### Scenario: Another site's page posts to the app

- **WHEN** a page on another origin makes the browser send a `POST` or `DELETE` to the app
- **THEN** the app answers `403` and the route does not run

#### Scenario: A request from outside a browser

- **WHEN** a request with neither `Sec-Fetch-Site` nor `Origin` arrives, such as the agent's `curl` or a webhook
- **THEN** the request reaches the route

### Requirement: Only the app's own origin may frame it

Every response of an app made from the starter, pages and API alike, SHALL carry `Content-Security-Policy: frame-ancestors 'self'`, `X-Frame-Options: SAMEORIGIN` and `X-Content-Type-Options: nosniff`, unless the app sets that header itself.

#### Scenario: Another site frames the app

- **WHEN** a page on another origin loads the app in an iframe
- **THEN** the browser refuses to render it

#### Scenario: The app sets its own policy

- **WHEN** a route sets its own `Content-Security-Policy`
- **THEN** the response carries the route's value

### Requirement: The agent's instructions keep data changes on the app's own pages

The agent's instructions SHALL require that only `POST`, `PUT`, `PATCH` and `DELETE` routes change data, that the app keeps the starter's origin check, and that it adds no CORS. They SHALL tell the agent how an app without the origin check gets it from the starter.

#### Scenario: An older app is changed

- **WHEN** the agent works on an app that has no `server/same-origin.ts`
- **THEN** its instructions point it to the starter's copy and how to use it

#### Scenario: A delete link

- **WHEN** the agent builds a way to delete a record
- **THEN** its instructions have it use a `DELETE` or `POST` route, not a `GET`

### Requirement: The agent's instructions keep identity, cookies and user content safe

The agent's instructions SHALL require that the user's identity comes only from Sign in with Freepod and is never kept in a cookie; that any cookie of the app's own is a `__Host-` cookie with `Secure`, `HttpOnly`, `SameSite=Lax` and `Path=/`; that uploads go back as downloads unless they are PNG, JPEG, GIF or WebP images; and that text users enter is rendered as text.

#### Scenario: The app shows uploads

- **WHEN** the agent serves a file a user uploaded
- **THEN** its instructions have it send the file as a download unless it is a PNG, JPEG, GIF or WebP image
