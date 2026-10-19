## ADDED Requirements

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
