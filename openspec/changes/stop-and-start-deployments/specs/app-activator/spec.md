## Purpose

The activator: the platform daemon that answers requests for the hostnames of deployments that are not running, what each kind of client receives, and how it is deployed per environment.

## ADDED Requirements

### Requirement: Every request for a stopped app gets a 503

The activator SHALL answer every request it receives with `503`, whatever the method or path, and SHALL NOT proxy, hold or forward any request. The response SHALL carry `Cache-Control: no-store`, so that no cache keeps serving it after the app is started.

#### Scenario: A browser visits a stopped app

- **WHEN** a browser navigates to a stopped deployment's hostname
- **THEN** the response is `503` with `Cache-Control: no-store`

#### Scenario: A POST to a stopped app

- **WHEN** a client sends `POST` to any path of a stopped deployment's hostname
- **THEN** the response is `503` and the request body is not forwarded anywhere

### Requirement: Browsers get a branded page

A request whose `Accept` header admits `text/html` SHALL receive an HTML page in the layout and design of the `custom` product's placeholder page, stating that the app at the requested hostname is stopped. Any other request SHALL receive `text/plain` with the same sentence.

#### Scenario: A browser

- **WHEN** the request accepts `text/html`
- **THEN** the body is the branded "stopped" page naming the requested hostname

#### Scenario: A sync client

- **WHEN** the request accepts only `application/json`
- **THEN** the body is `text/plain` stating that the app is stopped

### Requirement: The requested hostname cannot inject markup

The hostname shown on the page SHALL be taken from the request's `Host` header without its port, and SHALL be escaped for HTML. A `Host` header that is not a valid hostname SHALL be answered with the page without a hostname in it.

#### Scenario: A forged Host header

- **WHEN** a request carries a `Host` header containing markup
- **THEN** the page contains no markup from it

### Requirement: WebSocket upgrades are refused

A WebSocket upgrade request SHALL be answered with `503` and SHALL NOT be upgraded.

#### Scenario: A WebSocket client

- **WHEN** a client requests a WebSocket upgrade on a stopped deployment's hostname
- **THEN** the response is `503`

### Requirement: Health checks do not share the tenant's paths

The activator's health endpoint SHALL be served on a port that receives no tenant traffic, so that no path of a tenant hostname is reserved by the platform.

#### Scenario: A tenant path that looks like a health check

- **WHEN** a visitor requests `/healthz` on a stopped deployment's hostname
- **THEN** the response is the "stopped" response, not a health report

### Requirement: One activator per environment, reachable only from the edge

Each environment SHALL run its own activator, as two replicas, from the platform daemons image at a pinned version. Its network policy SHALL admit traffic on its serving port only from the shared ingress controller. Each environment's stopped deployments SHALL resolve to that environment's activator.

#### Scenario: A stopped dev deployment

- **WHEN** a deployment in the development environment is stopped
- **THEN** its hostname is answered by the development environment's activator

#### Scenario: A tenant pod calls the activator

- **WHEN** a pod in a tenant namespace connects to the activator directly
- **THEN** the connection is refused by network policy
