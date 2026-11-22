## MODIFIED Requirements

### Requirement: An HTTP-01 ClusterIssuer issues per-app certificates for custom domains
The system SHALL define a Let's Encrypt **HTTP-01** `ClusterIssuer` (solver via the `traefik`
ingress class) used to issue per-app certificates for user **custom domains**, for which DNS-01
is not possible (the user owns the domain's DNS). A **staging** variant SHALL exist. The solver
Ingress SHALL bind both the `web` and `websecure` entrypoints, because a proxy with an HTTPS
origin (Bunny.net) forwards the challenge to `:443`.

#### Scenario: Custom-domain certificate is issued via HTTP-01
- **WHEN** a deployment on a custom domain (e.g. `app.example.com`) is reconciled and its
  Ingress carries the `cert-manager.io/cluster-issuer` annotation for the HTTP-01 issuer
- **THEN** cert-manager creates a solver Ingress serving `/.well-known/acme-challenge/<token>`
  on `:80` and `:443`
- **AND** Let's Encrypt validates over `:80` (reachable via the homelab HAProxy edge) and issues
  the certificate into the deployment's namespace

#### Scenario: Challenge forwarded over HTTPS by a proxy
- **WHEN** a Bunny.net pull zone with origin `https://<cname target>` and Forward Host Header on
  forwards `GET /.well-known/acme-challenge/<token>` for `app.example.com` to `:443`
- **THEN** the solver answers it, not the app's own router
