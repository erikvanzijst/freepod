# Proposal

## Why

The platform now serves an OpenID Provider for tenant apps (`app-oidc-provider`),
but no chart uses it yet. Immich is the right first user. It supports a generic
OIDC provider with PKCE, it can refuse users its admin did not create, and its
mobile app signs in through a native redirect. One app exercises the
provider's web flow, the native-redirect flow and the "app decides" access
model together.

It ships as its own chart and its own admin-only product, so that SSO can be
tested and changed freely without ever touching the catalog Immich chart, its
product or its deployments.

## What Changes

- **A new chart, `products/immich-sso/chart`** (`immich-sso` 0.1.0), starts
  as a copy of the catalog Immich chart at 0.2.7. All SSO work happens in the
  copy. `products/immich`, the catalog Immich product and its deployments do
  not change.
- **The copy learns `sso.enabled`**, off by default as the chart contract
  requires. When it is on, the chart configures Immich's OAuth login against
  `caelus.oidc`: the issuer and client ID from the injected values, and the
  client secret read from the published Secret when the pod starts, never
  through Helm values.
- **Immich decides who gets in.** With SSO on, Immich's auto-registration and
  password login are off, so only accounts its admin created can sign in. The
  config file locks these settings, so they can't be turned back on from
  Immich's admin screens.
- **The owner's admin account is created by the chart** from
  `caelus.owner.email` on first start, so the owner signs straight in with
  Freepod and nobody else can claim the instance's admin account first.
- **The mobile app signs in with Freepod** through the native redirect
  `app.immich:///oauth-callback`, which the template declares.
- **Signing out of Immich signs out of Freepod** and returns to the Immich
  instance.
- **A new, admin-only product `immich-sso`** whose template points at the
  `immich-sso` chart and turns SSO on as a system value, with no way for a
  tenant to turn it off.

## Capabilities

### New Capabilities

- `immich-sso`: how an SSO-enabled Immich deployment signs users in through the
  platform's OpenID Provider, who may sign in, how the owner's account comes to
  exist, and how the mobile app and sign-out behave.

### Modified Capabilities

None. The chart obeys the existing `app-oidc-chart-contract`, and the provider
needs no changes.

## Impact

- New `products/immich-sso/`: the copied chart with a config file rendered at
  pod start, an owner-seeding hook, `sso` and `caelus.oidc`/`caelus.owner`
  values and schema, and a README. CI publishes it to `charts/immich-sso`
  like every product chart.
- New `api/tests/test_immich_sso_chart.py`, in the `helm_charts` test group.
  The chart-label contract test picks up the new chart by itself.
- A new product `immich-sso` created on dev with `caelus`, with `admin`
  visibility, then on prod once dev is verified. Its template's system values
  are in this change's tasks.
- Unchanged: `products/immich`, the catalog's `immich.yaml`, the catalog
  product and its deployments, the provider, the reconciler, the `freepod` CLI
  and the UI.
