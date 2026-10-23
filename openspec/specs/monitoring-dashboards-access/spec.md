# monitoring-dashboards-access Specification

## Purpose

Provide Grafana with pre-wired Prometheus and Loki datasources and Terraform-managed dashboards, exposed at grafana.freepod.eu and gated by a Keycloak-OIDC group whitelist.
## Requirements
### Requirement: Grafana with pre-wired datasources

The system SHALL run Grafana in the `monitoring` namespace with the Prometheus
and Loki datasources provisioned automatically, so metrics and logs are
queryable without manual datasource setup.

#### Scenario: Datasources are available on first login

- **WHEN** an authorized user opens Grafana after deployment
- **THEN** the Prometheus datasource (metrics) and Loki datasource (logs) are
  already present and usable

### Requirement: Terraform-managed dashboards

The system SHALL provision dashboards through the Grafana Helm chart so they
exist automatically on deploy, including Node Exporter Full (gnetId `1860`) and
Kubernetes Traefik Ingress NextGen (gnetId `25330`).

#### Scenario: Dashboards exist after a fresh deploy

- **WHEN** the monitoring stack is applied to a cluster with no prior Grafana
  state
- **THEN** the Node Exporter Full and Traefik Ingress NextGen dashboards are
  present without any manual import

#### Scenario: Traefik dashboard renders data

- **WHEN** an operator opens the Traefik Ingress NextGen dashboard
- **THEN** it displays live ingress data, because Traefik's Prometheus metrics
  are enabled and scraped

### Requirement: Keycloak-authenticated access with a user whitelist

The system SHALL expose Grafana at `grafana.freepod.eu` and authenticate users
via native Keycloak OIDC against the `freepod` realm, restricting access to
members of a designated Keycloak group (the whitelist). Users outside the group
SHALL be denied. Because Grafana authenticates against the same realm as
Freepod, an operator needs only one account.

#### Scenario: Whitelisted user signs in

- **WHEN** a user who is a member of the `freepod-observability` Keycloak group
  authenticates through Grafana's OIDC login
- **THEN** they are granted access with a mapped Grafana role

#### Scenario: Non-whitelisted user is denied

- **WHEN** a user who is not a member of the group attempts to sign in
- **THEN** Grafana refuses the login (strict role/group enforcement), granting
  no default access

#### Scenario: Whitelist is managed in Keycloak

- **WHEN** an operator needs to grant or revoke a user's Grafana access
- **THEN** it is done by adding/removing that user from the Keycloak group, with
  no Terraform apply or Grafana user-list change required

#### Scenario: Grafana targets the Freepod realm

- **WHEN** Grafana's generic OAuth configuration is inspected
- **THEN** its authorization, token and userinfo URLs all reference
  `https://keycloak.freepod.eu/realms/freepod`
- **AND** none of them reference the `master` realm

#### Scenario: One account serves Grafana and Freepod

- **WHEN** a user with an account in the `freepod` realm is added to
  `freepod-observability`
- **THEN** they sign in to Grafana with that same account
- **AND** no separate Grafana-only Keycloak account is required

#### Scenario: Group claim reaches Grafana

- **WHEN** the Grafana Keycloak client is inspected
- **THEN** the `groups` scope is assigned as a default client scope
- **AND** Grafana is configured to read the `groups` claim, without which its
  group extraction returns an empty list and every login is rejected

### Requirement: Grafana ingress without edge forward-auth

The system SHALL route `grafana.freepod.eu` through Traefik with HTTPS/HSTS
consistent with other freepod ingresses, and SHALL NOT place a forward-auth
middleware in front of Grafana, since Grafana performs its own OIDC login.

#### Scenario: Grafana handles its own login

- **WHEN** an unauthenticated request reaches `grafana.freepod.eu`
- **THEN** Traefik forwards it to Grafana (no edge forward-auth), and Grafana
  initiates the Keycloak OIDC sign-in flow itself

### Requirement: Deployment namespaces carry the deployment's identity

The reconciler SHALL label each deployment namespace with
`caelus.dev/deployment-id` set to the deployment's ID, alongside its owner,
product and environment, and kube-state-metrics SHALL publish that label on
`kube_namespace_labels`. The fleet-wide network policy sync SHALL re-apply it.

#### Scenario: A reconciled namespace names its deployment

- **WHEN** the reconciler applies tenant isolation to a deployment's namespace
- **THEN** the namespace carries `caelus.dev/deployment-id` with the
  deployment's ID
- **AND** `kube_namespace_labels` for that namespace carries
  `label_caelus_dev_deployment_id`

#### Scenario: Storage series join to their namespace

- **WHEN** a dashboard needs a deployment's database or bucket size by
  namespace
- **THEN** it matches the `datname` and `dep-<id>` bucket name to the
  namespace's deployment ID label, with no platform database lookup

### Requirement: Fleet deployments dashboard

The system SHALL provision a dashboard listing every deployment of an
environment, one row each, with its hostname, CPU, memory, pod network, HTTP
request rate, database size, bucket size and provisioned PVC size, each row
linking to that deployment's dashboard. It SHALL read only collected metrics.

#### Scenario: Comparing deployments

- **WHEN** an operator opens the fleet dashboard for an environment
- **THEN** each deployment of that environment is one row showing its
  resource use and storage

#### Scenario: Unmeasurable values are not presented as usage

- **WHEN** a dashboard shows PVC storage
- **THEN** it shows provisioned size and labels it as such, since local-path
  volumes report no usage

### Requirement: Single deployment dashboard

The system SHALL provision a dashboard for one deployment, selected by
hostname, deployment ID or namespace, showing its resource use, its HTTP
traffic as Traefik saw it, its database statistics and storage, and its pod
logs alongside its Traefik access lines over one time range.

#### Scenario: Finding a deployment by hostname

- **WHEN** an operator types part of a deployment's hostname, ID or namespace
  into the deployment picker
- **THEN** the matching deployment is offered

#### Scenario: Investigating one deployment

- **WHEN** an operator opens a deployment from the fleet dashboard
- **THEN** the deployment dashboard shows that deployment's pod logs and its
  Traefik access lines for the same time range
- **AND** pod creations are marked on its graphs
