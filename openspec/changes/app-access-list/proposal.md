# Proposal

## Why

Sign in with Freepod lets any Freepod account into an app, so the only apps it suits are those that decide access themselves. Apps like Nextcloud, BookStack, PhotoPrism and Immich create an account for whoever signs in, as their OIDC integrations intend, and custom apps often have no access control of their own. Owners need to say who may sign in, and to take that back, without redeploying anything. This change adds that list, and folds the two ways of signing in to apps, headers and OpenID Connect, into one set of values every chart declares.

## What Changes

- One `auth` contract for every chart that offers Sign in with Freepod:
  - `auth.enabled` (default `false`).
  - `auth.protocol`, either `header` or `oidc` (default `header`).
  - `auth.access`, either `anyone` or `listed` (default `anyone`).
  - `auth.public` (header only).
  - `auth.oidc.redirectPaths`, `auth.oidc.nativeRedirectUris`, `auth.oidc.pkce` and the new `auth.oidc.backchannelLogoutPath`, read only from template system values.
- **BREAKING (internal)**: the provider, the reconciler and the `immich-sso` chart and product move from `sso.*` to `auth.*`. `immich-sso` is admin-only and has no backward compatibility. Custom deployments keep their `auth` values unchanged.
- A per-deployment access list of up to 500 email addresses, kept in the platform database and edited through the API. The owner is always admitted and is never an entry. An entry is tied to the person's Freepod subject the first time they sign in, and from then on matches by subject.
- For `listed` deployments, the broker admits only the owner and the people on the list. It checks at sign-in for both protocols, before consent, and the provider checks again at the token and userinfo endpoints.
- The verifier checks every request to a `listed` header app against the list. It reads the list from the database and keeps it in memory for 30 seconds, re-reading when it is about to refuse someone. That replaces the `a=` allowed-accounts parameter, which is removed.
- Removing someone from an OIDC app sends that app an OpenID Connect Back-Channel Logout token for their subject, synchronously, from the API. If the app does not accept it, the removal fails and the entry stays.
- Adding someone sends them a fixed invitation email, with a per-owner daily limit.
- A product-blind Access dialog on the dashboard, shown when the serving release has `auth.enabled` and `auth.access: listed`, and a read-only Access section in the admin deployment dialog.
- App Studio moves from the owner-only `a=` list to `auth.access: listed`. With an empty list it admits the owner alone, as before.

## Capabilities

### New Capabilities

- `app-access-list`: the per-deployment list of people who may sign in to a `listed` app. Covers who is admitted, binding entries to subjects, the API, the limits, invitations, and revoking access.
- `app-access-dialog`: how the dashboard and the admin deployment dialog show and edit a deployment's access, without knowing its product.

### Modified Capabilities

- `app-auth-chart-contract`: `auth.protocol` and `auth.access` join `auth.enabled` and `auth.public`; edge authentication applies only to `header`; access lists no longer come from chart values.
- `app-oidc-chart-contract`: SSO is declared with `auth.enabled` and `auth.protocol: oidc` instead of `sso.*`; the callback keys move under `auth.oidc`; templates may declare a back-channel logout path.
- `app-oidc-provider`: a client is an `oidc` deployment; redirect, PKCE and native keys move under `auth.oidc`; `listed` deployments are enforced; the provider sends back-channel logout tokens.
- `app-auth-broker`: header sign-in requires `auth.protocol: header`; a `listed` deployment admits only its owner and its list.
- `app-auth-verifier`: allowed accounts come from the access list instead of the edge configuration, read from a cache that tolerates a database outage.
- `app-auth-data-model`: the access list and the invitation log; the app authentication role's new grants.
- `app-studio-access`: the studio admits its owner and anyone the owner lists, through `auth.access: listed`.
- `immich-sso`: the sandbox product's values move from `sso.*` to `auth.*`, and it becomes `listed` with Immich's auto-registration on.

## Impact

- **app-auth daemon** (`daemons/app-auth/`):
  - eligibility queries that read `auth.*`;
  - the matching function shared by the broker, the provider and the verifier;
  - the verifier's access cache, with `allowCache` and `a=` removed;
  - binding entries to subjects at sign-in;
  - back-channel logout advertised in discovery.
- **Database**: new tables `app_access_entry` and `app_access_invitation`, plus new grants for the app authentication role on `deployment.user_id` and `user.email` (`tf/app/caelus/app-auth-bootstrap.sql`).
- **API**:
  - access endpoints under `/users/{user_id}/deployments/{deployment_id}/access`;
  - an `auth` summary on the deployment read model;
  - invitation emails through `app/services/mailer.py`;
  - logout tokens signed with the provider's ID token key and POSTed to the app in the removal request;
  - `app_auth_oidc.sso_enabled` reading `auth.*`.
- **Infrastructure**: the provider's signing keys reach the API pod, as its client keyring already reaches the worker.
- **Charts**:
  - `custom`: adds `auth.access`; forward-auth only for `header`; passes the listed flag to the verifier.
  - `appstudio`: `auth.access: listed`, no `a=`.
  - `immich-sso`: `auth.*`, `auth.access: listed` and `autoRegister: true`, with a new chart version and template version.
  - Catalog templates for custom and App Studio.
  - A catalog test that every template enabling auth states `auth.access`.
- **UI**: the Access button, the "Who can sign in" fact, the Access dialog, and the admin Access section.
- **Docs**: the custom app sign-in docs and the `deploy-to-freepod` skill gain `auth.access`. No CLI change, since `.freepod.json` user values pass through unchanged.
- **Follows**: `nextcloud-sso`, the first catalog-style product that uses `listed`.
