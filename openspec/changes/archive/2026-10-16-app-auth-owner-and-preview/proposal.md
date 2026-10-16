# Proposal

## Why

App Studio puts an AI agent with a shell, the owner's Freepod credentials and a
live preview of their app on a public hostname, so it must be reachable by its
owner and nobody else. "Sign in with Freepod" is the platform's way to put an app
behind a sign-in, but today it serves only the `custom` product, only proves who
a visitor is (any Freepod account may sign in), and knows nothing of a second
hostname such as the studio's preview. Until it does, the studio sits behind a
shared basic-auth password.

## What Changes

- **Any product may use app authentication.** The broker stops requiring the
  `custom` product. A deployment qualifies when the release it serves has
  `auth.enabled`, whether a user set it or the product's template sets it as a
  system value. Every chart is the platform's own, so the product check
  protected nothing.
- **Preview hostnames sign in as their deployment.** The broker treats
  `preview-<label>.<rest>` as the deployment at `<label>.<rest>` whenever that
  deployment is auth-enabled. It derives this from the name and the database
  alone; nothing the browser sends can name an alias. Consent stays per deployment, so one consent covers both hostnames;
  sessions stay bound to the host they were issued for. Hostname validation
  already reserves `preview-` application labels.
- **Owner-only access.** The verifier's forward-auth address can carry a list of
  allowed email addresses, the way it carries public paths today. A signed-in
  visitor whose email is not on the list is refused with a page that names the
  application and its address, in the look of the platform's placeholder page.
  The verifier keeps needing no database.
- **App Studio adopts it.** The `appstudio` chart routes its studio and preview
  hostnames through the platform's identity-header strip and verifier, always
  with authentication on and the deployment's owner as the only allowed
  account, and drops the basic-auth password.

## Capabilities

### New Capabilities
- `app-studio-access`: who may reach an App Studio deployment's studio and
  preview hostnames, and how its chart puts both behind owner-only sign-in.

### Modified Capabilities
- `app-auth-broker`: eligibility no longer depends on the product; it reads the
  effective `auth.enabled` (system value over user value); `preview-` hostnames
  resolve to their deployment.
- `app-auth-verifier`: an optional allowed-accounts list on the forward-auth
  address, enforced on every request, and the no-access page.
- `app-auth-chart-contract`: the contract applies to any chart that opts in, not
  only `custom`; authentication may be a template system value; a chart may
  restrict access with the allowed-accounts list rendered from platform-injected
  values.
- `app-auth-data-model`: the least-privilege role reads the template's system
  values instead of the product slug.

## Impact

- `daemons/app-auth/`: broker eligibility query and preview alias
  (`store.go`), allowed-accounts check and refusal page in the verifier
  (`verify.go`, `pages.go`), removal of the `APP_AUTH_PRODUCT_SLUG` setting, and
  tests. A new `daemons` image version.
- `tf/app/`: the app-auth daemon's pinned version, the removed setting, and the
  daemon role's grants (template system values instead of the product).
- `products/appstudio/chart/`: app-auth middlewares on both Ingresses, with
  authentication declared as a template system value; the basic-auth password
  and the preview's basic auth go.
- The App Studio product's template on dev: system values gain `auth.enabled`
  and lose the password Secret names.
- Unchanged: the `custom` chart and every existing auth-enabled deployment; the
  schema; the API.
