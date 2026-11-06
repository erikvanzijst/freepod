# parking-page Specification

## Purpose

The parking page: what the platform serves for the hostname of a deployment that is stopped, and the host guard that lets the API serve it without exposing any API route on a tenant hostname.

## Requirements

### Requirement: Tenant hostnames never reach an API route

The API SHALL answer every HTTP request whose `Host`, without its port and compared case-insensitively, is not the platform's own domain with the parking response. It SHALL NOT pass that request to any API route or API middleware, for any path or method, and regardless of the identity headers the request carries.

#### Scenario: Forged identity headers on a stopped app's hostname

- **WHEN** a visitor sends `GET /api/users/me` with an `X-Auth-Request-Email` header to a stopped deployment's hostname
- **THEN** the response is the parking response, and no API route runs

#### Scenario: The platform's own domain

- **WHEN** a request for the platform's own domain reaches the API
- **THEN** it is handled by the API as before

### Requirement: Loopback peers are exempt

A request whose connection comes from a loopback address (`127.0.0.1` or `::1`) SHALL be handled by the API whatever its `Host`, so that operators can reach the API through a port-forward or from inside its pod. The peer address SHALL be the connection's own, never one taken from a forwarding header.

#### Scenario: An operator's port-forward

- **WHEN** an operator port-forwards to the API and requests `http://localhost:8000/api/...`
- **THEN** the request is handled by the API

#### Scenario: A forwarding header claiming loopback

- **WHEN** a visitor sends a request with `X-Forwarded-For: 127.0.0.1` to a stopped deployment's hostname
- **THEN** the response is the parking response

### Requirement: The guard is off without a configured domain

When the platform's own domain is not configured, as in local development, the API SHALL handle every request whatever its `Host`.

#### Scenario: Local development

- **WHEN** the API runs with no platform domain configured and receives a request for `localhost:5173`
- **THEN** the request is handled by the API

### Requirement: Every request for a stopped app gets a 503

The parking response SHALL be `503`, whatever the method or path. It SHALL carry `Cache-Control: no-store`, so that no cache keeps serving it after the app is started. No request SHALL be proxied, held or forwarded.

#### Scenario: A browser visits a stopped app

- **WHEN** a browser navigates to a stopped deployment's hostname
- **THEN** the response is `503` with `Cache-Control: no-store`

#### Scenario: A POST to a stopped app

- **WHEN** a client sends `POST` to any path of a stopped deployment's hostname
- **THEN** the response is `503` and the request body is not forwarded anywhere

### Requirement: Browser navigations get a branded page

A request whose method is `GET`, whose `Accept` header contains `text/html` and which has no `Upgrade` header SHALL receive an HTML page. The page SHALL use the layout and design of the `custom` product's placeholder page, and SHALL state that the app at the requested hostname is stopped. Any other request SHALL receive `text/plain; charset=utf-8` with the same sentence.

#### Scenario: A browser

- **WHEN** a `GET` request accepts `text/html`
- **THEN** the body is the branded "stopped" page naming the requested hostname

#### Scenario: A sync client

- **WHEN** the request accepts only `application/json`
- **THEN** the body is `text/plain` stating that the app is stopped

### Requirement: The requested hostname cannot inject markup

The hostname shown on the page SHALL be taken from the request's `Host` header without its port, and SHALL be escaped for HTML.

#### Scenario: A forged Host header

- **WHEN** a request carries a `Host` header containing markup
- **THEN** the page contains no markup from it

### Requirement: WebSocket requests are refused

A WebSocket request for a hostname that is not the platform's own domain SHALL be refused before it is accepted, and SHALL NOT be upgraded.

#### Scenario: A WebSocket client

- **WHEN** a client opens a WebSocket to a stopped deployment's hostname
- **THEN** the handshake is refused

### Requirement: No tenant path is reserved

The parking response SHALL be the same for every path, including paths that look like platform endpoints, so that no path of a tenant hostname is reserved by the platform.

#### Scenario: A tenant path that looks like a health check

- **WHEN** a visitor requests `/healthz` or `/api/openapi.json` on a stopped deployment's hostname
- **THEN** the response is the parking response

### Requirement: Each environment parks its own stopped apps

A stopped deployment's hostname SHALL be answered by the API of the environment the deployment belongs to. No additional service SHALL be deployed for it: the parking page is served by that environment's API, reachable only from the shared ingress controller.

#### Scenario: A stopped dev deployment

- **WHEN** a deployment in the development environment is stopped
- **THEN** its hostname is answered by the development environment's API

#### Scenario: A tenant pod calls the parking page directly

- **WHEN** a pod in a tenant namespace connects to the API directly
- **THEN** the connection is refused by network policy
