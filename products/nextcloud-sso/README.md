# Nextcloud (SSO) — Freepod chart

A sandbox copy of the [Nextcloud chart](../nextcloud/README.md) for Sign in
with Freepod, served by an admin-only product. Unless its values set
`auth.enabled: true` with `auth.protocol: oidc`, it renders what the Nextcloud
chart renders.

With SSO on, it needs the values the Caelus reconciler injects for an
OIDC-enabled deployment, and refuses to render without them:

- `caelus.oidc.issuer`, `caelus.oidc.clientId` and `caelus.oidc.secretName`
  (the Secret holding `OIDC_CLIENT_SECRET`), and
- `caelus.owner.subject` and `caelus.owner.email`, the owner who becomes an
  administrator.

Sign-in goes through Nextcloud's own OpenID Connect app, `user_oidc`. A
`before-starting` hook, `00-sso.sh`, installs it from the app store if it is
missing and, on every start, pins its `freepod` provider and turns off
Nextcloud's login form, so Log in goes straight to Freepod. A start where any of
that fails stops before Apache, since the instance would have no way in.

Accounts are keyed by the Freepod subject, unhashed, and take their email and
display name from Freepod on every sign-in. That is what lets `owner.php`
provision the owner's account into the `admin` group before they first sign
in. The install's own `admin` account has a generated password in
`<release>-admin` that nobody is given, and the hook keeps it disabled.

Nextcloud creates an account for whoever the provider admits, as `user_oidc`
intends, so the chart refuses SSO without `auth.access: listed`: the owner
invites people from the deployment's Access dialog, not from Nextcloud's Users
page. Groups, quotas and sharing stay Nextcloud's; the provider sends no groups.
An account created under Users is a local one, with a password and outside the
access list. A Freepod sign-in never merges into it, even with the same email,
and gets an account of its own.

Back-channel logout goes to the chart's own Nextcloud app, `freepod`
(`chart/files/freepod`, mounted read-only into `custom_apps`). It hands every
token to `user_oidc`, which verifies it and ends the sessions it names. A token
that also carries `freepod_access: "revoked"`, which the platform sends only
when someone is removed from the access list, makes it remove all of that
person's auth tokens too: browser sessions, app passwords held by desktop and
mobile clients, and remembered logins. The account and its files stay, so adding
the person back is enough for them to sign in again. Signing out of Freepod
ends only the browser session.

Changing the app's version in `appinfo/info.xml` makes Nextcloud require an
upgrade, so `00-sso.sh` runs `occ upgrade` when one is pending. The app declares
the Nextcloud majors it supports, like `user_oidc`; a new major needs
`max-version` raised first.

An upgrade that switches sign-in fails the render, in either direction: SSO
accounts are named after Freepod subjects and have no passwords, and
Nextcloud's own accounts cannot sign in through Freepod. A release counts as
SSO while it holds `<release>-freepod-app`, so a release from the catalog chart
counts as having its own accounts. A fresh install takes either.

If sign-in ever breaks, the way in is `occ user:enable admin`, then
`/login?direct=1` with the password from `<release>-admin`. The next start
disables it again.

The template's system values carry the whole `auth` block, which tenants cannot
change:

```yaml
auth:
  enabled: true
  protocol: oidc
  access: listed
  oidc:
    redirectPaths: ["/apps/user_oidc/code"]
    backchannelLogoutPath: /apps/freepod/backchannel-logout
```

Spec: [app-oidc-chart-contract](../../openspec/specs/app-oidc-chart-contract/spec.md),
[app-access-list](../../openspec/specs/app-access-list/spec.md).
Published to `oci://ghcr.io/erikvanzijst/freepod/charts/nextcloud-sso` like every
product chart.

## Upstream references

Those of the [Nextcloud chart](../nextcloud/README.md#upstream-references),
plus these pitfalls:

- **`user_oidc` moves on its own.** The chart doesn't pin it: a new install gets
  the store's newest compatible release, a Nextcloud upgrade updates it, and the
  instance's admin can update it any time. The `freepod` app calls
  `LoginController::backChannelLogout(string $providerIdentifier, string $logout_token = '')`,
  which isn't public API. On every Nextcloud bump, check that method's signature
  in the `user_oidc` release that supports the new version, and that it still
  answers 200 only for a token it verified.
- **A new Nextcloud major** needs `max-version` in
  `chart/files/freepod/appinfo/info.xml` raised first: Nextcloud disables an
  app that doesn't declare its version, and `00-sso.sh` then fails the start.
