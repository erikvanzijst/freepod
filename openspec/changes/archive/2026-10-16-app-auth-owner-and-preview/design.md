# Design

## Context

App authentication has two halves (`daemons/app-auth/`): the **broker** on
`login.<domain>`, which talks to Keycloak and has the platform database, and the
**verifier**, Traefik's forward-auth target, which decides every request from a
sealed session cookie and the query string of its own address, with no database.
A chart declares per-deployment edge behavior by rendering that address:
today `?p=<base64url JSON>` carries the public paths.

A deployment release stores only the user's values (`deployment_release.values_json`).
The template's system values live on the template version and are merged in last
by the reconciler (`merge_values_scoped`), so what the edge enforces is the
system value when there is one. The broker's eligibility query reads only the
release's user values, and only for the `custom` product (`APP_AUTH_PRODUCT_SLUG`).

The reconciler already injects the verifier's address into every deployment, not
just `custom` ones; only the specs said otherwise.

## Goals / Non-Goals

**Goals:**
- The broker accepts any product and agrees with the edge on whether
  authentication is enabled.
- Preview hostnames sign in without the platform storing a second hostname.
- Owner-only access enforced per request, still without a database in the
  verifier.

**Non-Goals:**
- Allowed accounts for `custom` deployments (their schema does not expose a
  list; this change only makes it possible for platform-owned charts).
- Restricting who may *consent* or sign in at the broker. A non-owner can still
  complete Freepod sign-in on a studio host; the verifier then refuses them.
- Preview hostnames on custom domains (no certificate or DNS for them).

## Decisions

### D1. Eligibility reads the effective value, for any product

`auth.enabled` is read as `coalesce(template system value, release user value,
false)`, matching the reconciler's precedence, and the product join and
`APP_AUTH_PRODUCT_SLUG` go. The slug check only ever protected against a chart
that rendered the verifier without meaning to, and every chart is ours.
*Alternative:* a list of allowed slugs. Rejected: it needs configuration per
product, and non-curated products have no slug at all.

The daemon's database role trades its `product` grant for the template's
`system_values_json`. The store tests isolated themselves from the shared API
test database through a per-test slug; they isolate through unique hostnames
instead.

### D2. The preview alias is derived, not declared

For a host with no exact match whose first label starts with `preview-`, the
broker looks up the host with that prefix removed and requires the same
eligibility. It returns the base deployment's id, so consent (keyed by
deployment) is shared, while codes and sessions stay bound to the host the
browser actually used.

The alias follows `auth.enabled` alone, with no separate switch: for a
deployment whose chart renders no preview, completing sign-in on its
`preview-` name leads nowhere (no route serves that host), and the hostname
reservation keeps the name from belonging to anyone else.

*Alternative:* pass aliases in the verifier's address. Rejected: the broker
decides eligibility before any session exists, and the verifier's address never
reaches it; anything the browser forwards could name any host. *Alternative:* a
second claimed hostname per deployment. Rejected for now: schema, claiming and
UI changes for one product. Hostname validation already reserves `preview-`
application labels, so the derived name cannot belong to another deployment.

### D3. Allowed accounts travel like public paths

The verifier's address gains `a=<base64url JSON array of emails>`, decoded and
cached like `p`, and an optional `n=<application name>` for the refusal page.
After the session check, a request with a session whose lowercased email is not
in the list is refused: a navigation gets the no-access page, other requests a
`403`. The page reuses the look of the `custom` chart's placeholder page (a
centered column in the system font, light and dark), not the broker's
Freepod-branded card, because it is served on the app's own host in the app's
place. It names the application (`n`, else the host) and `https://<host>`, the
signed-in email, and a sign-out link (`/.freepod/auth/logout?rd=/`) to switch
accounts. The check also covers public paths, so a public page cannot be
used to see a signed-in identity the deployment did not allow. An undecodable
list admits nobody. Anonymous requests are unaffected: they hit the normal
sign-in flow, or the public path.

Email is the identity for now because the platform injects the owner's email
(`caelus.owner.email`). Keycloak's immutable subject is the better key, but the
user table does not hold it yet, so matching on it is a separate change; the
`a` list can then carry subjects instead.

### D4. App Studio is auth-only

The appstudio chart renders the identity-header strip and the forward-auth
middleware (ported from the `custom` chart) on both Ingresses, with
`a=[caelus.owner.email]` and `n=App Studio`, ahead of its own redirect and
preview-down middlewares. It fails to render without the verifier address or
the owner email, and when `auth.enabled` is not true, because the broker reads
that from the template's system values: a template that forgot it would serve a
studio nobody can sign in to. The basic-auth password values
and the preview's basic-auth middleware are removed.

## Risks / Trade-offs

- [A non-owner can consent to share their email with someone's studio before
  being refused] → The consent page names the app; nothing is disclosed to the
  app because the verifier refuses before it. Restricting at the broker is a
  later change if needed.
- [Owner changes their email] → The next release re-renders the list from the
  platform's current email; until then the old address is the allowed one.
- [The new grants and the new daemon land in one apply, but not at the same
  instant] → For the seconds between the worker's bootstrap and the new app-auth
  pods, the broker fails to start new sign-ins (the old query needs `product`,
  the new one `system_values_json`). Signed-in sessions are unaffected: the
  verifier has no database.
- [Shared `app_auth_image` variable for dev and prod] → Roll dev with an explicit
  `-var app_auth_image=…` override; bump the default only after dev is proven.
- [The alias rule applies to every auth-enabled deployment] → A `preview-`
  name of a deployment without a preview route serves nothing, and the
  reservation keeps it unclaimable.

## Migration Plan

1. Release the daemons image at a new version and roll dev's app-auth with a
   variable override; existing `custom` deployments keep working (their auth is
   a user value, which the new query still reads).
2. Publish the appstudio chart, create a new App Studio template version on dev
   with `auth.enabled: true` as a system value, and move the deployment to it.
3. Remove the hand-made password Secrets. Bump the Terraform default and apply
   prod once dev is verified.

Rollback: re-pin the previous daemons version. Existing `custom` deployments
are unaffected. The old broker only serves `custom` and reads user values, so it
refuses to start sign-in for App Studio: the studio fails closed (nobody gets
in) until the deployment is moved back to its password template.
