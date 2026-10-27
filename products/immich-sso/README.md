# Immich (SSO) — Freepod chart

A sandbox copy of the [Immich chart](../immich/README.md) for Sign in with
Freepod, served by the admin-only `immich-sso` product. With `sso.enabled` off
it renders what the Immich chart renders.

`sso.enabled: true` needs the values the Caelus reconciler injects for an
SSO-enabled deployment, and refuses to render without them:

- `caelus.oidc.issuer`, `caelus.oidc.clientId` and `caelus.oidc.secretName`
  (the Secret holding `OIDC_CLIENT_SECRET`), and
- `caelus.owner.email`, who becomes Immich's first admin.

The template declares `sso.redirectPaths: ["/auth/login"]` and
`sso.nativeRedirectUris: ["app.immich:///oauth-callback"]`.

Spec: [immich-sso](../../openspec/specs/immich-sso/spec.md),
[app-oidc-chart-contract](../../openspec/specs/app-oidc-chart-contract/spec.md).
Published to `oci://ghcr.io/erikvanzijst/freepod/charts/immich-sso` like every
product chart.
