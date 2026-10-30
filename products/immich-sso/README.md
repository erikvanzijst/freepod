# Immich (SSO) — Freepod chart

A sandbox copy of the [Immich chart](../immich/README.md) for Sign in with
Freepod, served by the admin-only `immich-sso` product. Unless its values set
`auth.enabled: true` with `auth.protocol: oidc`, it renders what the Immich
chart renders.

With SSO on, it needs the values the Caelus reconciler injects for an
OIDC-enabled deployment, and refuses to render without them:

- `caelus.oidc.issuer`, `caelus.oidc.clientId` and `caelus.oidc.secretName`
  (the Secret holding `OIDC_CLIENT_SECRET`), and
- `caelus.owner.email`, who becomes Immich's first admin.

Immich registers whoever the provider admits, as its OAuth docs intend, so the
chart refuses SSO without `auth.access: listed`: the owner invites people from
the deployment's Access dialog, not from Immich's Create user.

The template's system values carry the whole `auth` block, which tenants
cannot change:

```yaml
auth:
  enabled: true
  protocol: oidc
  access: listed
  oidc:
    redirectPaths: ["/auth/login"]
    nativeRedirectUris: ["app.immich:///oauth-callback"]
    backchannelLogoutPath: /api/oauth/backchannel-logout
```

Spec: [immich-sso](../../openspec/specs/immich-sso/spec.md),
[app-oidc-chart-contract](../../openspec/specs/app-oidc-chart-contract/spec.md),
[app-access-list](../../openspec/specs/app-access-list/spec.md).
Published to `oci://ghcr.io/erikvanzijst/freepod/charts/immich-sso` like every
product chart.
