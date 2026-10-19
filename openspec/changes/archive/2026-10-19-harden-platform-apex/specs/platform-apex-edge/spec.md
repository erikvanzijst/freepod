## ADDED Requirements

### Requirement: The apex is served over HTTPS only
The platform apex (`${var.domain}`) and the login host (`login.${var.domain}`)
SHALL be routed on the `websecure` entrypoint only. A plain-HTTP request to
either SHALL receive the cluster's HTTP→HTTPS redirect and SHALL NOT be served.

#### Scenario: Plain HTTP to the apex
- **WHEN** a client requests `http://${var.domain}/` or `http://login.${var.domain}/`
- **THEN** it receives a `301` to the same host over `https://`
- **AND** no platform content is served over plain HTTP

### Requirement: The apex refuses to be framed by other origins
Every route on the apex SHALL answer with `X-Frame-Options: SAMEORIGIN` and
`Content-Security-Policy: frame-ancestors 'self'`, set by a Traefik Middleware
rather than by the upstream, so the UI, the API and the `/oauth2` endpoints are
covered alike.

#### Scenario: Another origin frames the apex
- **WHEN** a page on any origin other than `https://${var.domain}` embeds `https://${var.domain}/` in an iframe
- **THEN** the browser refuses to render the frame

#### Scenario: Every apex route carries the headers
- **WHEN** a response from the UI, `/api` or `/oauth2` on `${var.domain}` is inspected
- **THEN** it carries `X-Frame-Options: SAMEORIGIN` and `frame-ancestors 'self'`

### Requirement: The UI receives no cookies
The UI route on the apex SHALL remove the `Cookie` request header before the
request reaches the UI server, which reads none.

#### Scenario: A UI request arrives with cookies
- **WHEN** a browser sends a UI request that carries a `Cookie` header
- **THEN** the UI server receives the request without a `Cookie` header

### Requirement: The API parses JSON bodies only when declared
The API SHALL parse a request body as JSON only when the request carries a JSON
`Content-Type`. A body with no `Content-Type` SHALL be refused rather than
parsed.

#### Scenario: A JSON body without Content-Type
- **WHEN** a request to a JSON-body endpoint carries a JSON body and no `Content-Type`
- **THEN** the API responds `422` and the endpoint does not run

### Requirement: The API refuses state-changing requests other origins' pages start
The API SHALL answer `403`, before routing and authentication, to a request
whose method is not `GET`, `HEAD` or `OPTIONS` when a browser started it from a
page on another origin, unless that origin is one of its CORS origins.
`Sec-Fetch-Site` decides when present, and `Origin` otherwise.

#### Scenario: A request from another origin's page
- **WHEN** a `POST` to any API route carries `Sec-Fetch-Site: same-site`
- **THEN** the API responds `403` and the route does not run

#### Scenario: The UI's own request
- **WHEN** a `POST` carries `Sec-Fetch-Site: same-origin`
- **THEN** it is handled as usual

#### Scenario: Only Origin is present
- **WHEN** a `PUT` carries no `Sec-Fetch-Site` and an `Origin` whose host differs from the request's `Host`
- **THEN** the API responds `403`

#### Scenario: A trusted CORS origin
- **WHEN** a `POST` carries `Origin: http://localhost:5173` and `Sec-Fetch-Site: same-site`
- **THEN** it is handled as usual

#### Scenario: A non-browser client
- **WHEN** a `POST` carries neither `Sec-Fetch-Site` nor `Origin`, as the CLI, webhooks and the registry's token exchange do
- **THEN** it is handled as usual
