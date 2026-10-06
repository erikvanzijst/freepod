## MODIFIED Requirements

### Requirement: Every page requires an allowed Freepod account
The deployment MUST opt in to Sign in with Freepod, with `GET /healthz` as its only public
path. Every other dashboard page and action MUST be served only when the platform's
`X-Freepod-Email` header names an address listed in `ALLOWED_EMAILS`, compared without
regard to case.

A request without the header MUST be refused with 401. A signed-in account whose address
is not listed MUST be refused with 403 and a link to sign out. When `ALLOWED_EMAILS` is
unset or empty, every request except `GET /healthz` MUST be refused.

The header is trusted only because the platform strips it from requests that arrive
through the ingress. A request that does not arrive that way MUST be refused with 403,
whatever headers it carries. This covers any request whose peer address belongs to the
deployment's own pod, such as one from an agent session to `localhost`.

#### Scenario: Not signed in
- **WHEN** a run page is requested without an `X-Freepod-Email` header
- **THEN** the response has status 401

#### Scenario: An account that is not allowed
- **WHEN** a run page is requested by a signed-in account whose email is not in `ALLOWED_EMAILS`
- **THEN** the response has status 403

#### Scenario: The allow-list was never set
- **WHEN** `ALLOWED_EMAILS` is unset and any page other than `/healthz` is requested, by any account
- **THEN** the response has status 403

#### Scenario: A request from inside the pod
- **WHEN** a process in the pod sends `POST /runs` to `localhost:8080`, or to the pod's own address, with an `X-Freepod-Email` header naming an allowed address
- **THEN** the response has status 403, and no run starts

#### Scenario: Health from inside the pod
- **WHEN** a process in the pod requests `GET /healthz`
- **THEN** the response has status 200
