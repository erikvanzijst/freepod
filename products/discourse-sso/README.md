# Discourse (SSO) — Freepod chart

A sandbox copy of the [Discourse chart](../discourse/README.md) for Sign in
with Freepod, served by an admin-only product. Unless its values set
`auth.enabled: true` with `auth.protocol: oidc`, it renders what the Discourse
chart renders.

With SSO on, it needs the values the Caelus reconciler injects for an
OIDC-enabled deployment, and refuses to render without them:

- `caelus.oidc.issuer`, `caelus.oidc.clientId` and `caelus.oidc.secretName`
  (the Secret holding `OIDC_CLIENT_SECRET`), and
- `caelus.owner.email`, who becomes Discourse's first admin. The seed creates
  that account without a password.

Sign-in goes through the provider: the chart pins Discourse's OpenID Connect
settings and turns off password, email-link and passkey login, and
DiscourseConnect, which would replace Sign in with Freepod altogether. With no
other method left, Discourse's Log in and Sign up go straight to Freepod. An admin
can still add login methods of their own, which appear beside it; those affect
only that forum, and accounts link by email across all of them.

Nothing fronts the deployment, so the forum stays readable anonymously, and
`login_required` remains the tenant's.

Discourse manages its own members behind SSO, so the template fixes
`auth.access: anyone` and offers tenants no way to change it: a Freepod access
list would be a second gate the forum knows nothing about. Any Freepod account
gets as far as Discourse allows, and the forum decides who joins through
`allow_new_registrations`, `invite_only` and `must_approve_users`. People are
removed in Discourse: Suspend blocks them everywhere, including their API keys.

Accounts link to Freepod accounts by email on first sign-in, which is what lets
a forum restored from a backup made elsewhere keep its members. Discourse then
re-links an account to whichever Freepod account next presents that email.

It offers no SSH or SFTP access: Discourse's own backup and restore is how data
moves in and out, so the chart renders no sidecar and no `-ssh` Service.

Discourse has no back-channel logout, so the template declares no
`auth.oidc.backchannelLogoutPath`. Signing out of the forum ends the Freepod
session, but signing out elsewhere leaves the forum session in place until it
expires. If Discourse's sign-in ever breaks,
the only way in is `rails runner`: `/u/admin-login` needs the email login that
SSO turns off.

The template's system values carry the OIDC settings, which tenants cannot
change:

```yaml
auth:
  enabled: true
  protocol: oidc
  access: anyone
  oidc:
    redirectPaths: ["/auth/oidc/callback"]
```

Spec: [app-oidc-chart-contract](../../openspec/specs/app-oidc-chart-contract/spec.md).
Published to `oci://ghcr.io/erikvanzijst/freepod/charts/discourse-sso` like every
product chart.
