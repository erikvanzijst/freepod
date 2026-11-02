# keycloak-deployment Specification

## Purpose
Deploy Keycloak identity provider on Kubernetes for user authentication.

## Requirements

### Requirement: Keycloak runs on Kubernetes
The system SHALL deploy Keycloak as a Kubernetes Deployment backed by an external PostgreSQL database.

#### Scenario: Keycloak deployment exists
- **WHEN** `kubectl get deployment -n keycloak keycloak` is executed
- **THEN** a deployment named `keycloak` exists in the `keycloak` namespace

#### Scenario: Keycloak pod is running
- **WHEN** `kubectl get pods -n keycloak -l app=keycloak` is executed
- **THEN** at least one pod shows status `Running`

#### Scenario: Keycloak service is exposed
- **WHEN** `kubectl get svc -n keycloak keycloak` is executed
- **THEN** a ClusterIP service exposes port 80 forwarding to container port 8080

### Requirement: Keycloak data persists across restarts
Keycloak SHALL store all realm, client, and user state in the PostgreSQL database, whose storage is backed by a PersistentVolumeClaim. The Keycloak pod itself is stateless and mounts no persistent volume.

#### Scenario: PVC exists for PostgreSQL
- **WHEN** `kubectl get pvc -n keycloak postgres-pvc` is executed
- **THEN** a PVC exists with a `1Gi` `ReadWriteOnce` request

### Requirement: Keycloak is reachable via Ingress
The system SHALL expose Keycloak via Kubernetes Ingress for external access.

#### Scenario: Keycloak Ingress exists
- **WHEN** `kubectl get ingress -n keycloak keycloak` is executed
- **THEN** an Ingress resource exists pointing to keycloak service

### Requirement: Keycloak is configured via environment variables
The system SHALL configure Keycloak with required environment variables including hostname, realm, and OIDC settings.

#### Scenario: Keycloak environment variables are set
- **WHEN** Keycloak pod spec is inspected
- **THEN** environment variables include `KC_HOSTNAME_URL`, `KC_PROXY`, and `KC_DB`

### Requirement: Keycloak has health checks
The system SHALL configure readiness and liveness probes for Keycloak.

#### Scenario: Keycloak probes are configured
- **WHEN** Keycloak deployment spec is inspected
- **THEN** both readinessProbe and livenessProbe are defined

### Requirement: Keycloak resources are managed by Terraform
The system SHALL provision all Kubernetes resources via Terraform in the `./tf/` directory.

#### Scenario: Terraform applies Keycloak resources
- **WHEN** `terraform plan` is run in `./tf/`
- **THEN** resources for keycloak namespace, deployment, service, pvc, and ingress are planned
