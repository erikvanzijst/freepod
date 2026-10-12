## Why

A product's `visibility` is either `public` (listed for everyone) or `admin`
(listed for administrators only). Neither fits a product that end users must
be able to reach through the API and the `freepod` client but that does not
belong in the storefront: the developer product `custom`, which `freepod
deploy` finds by slug in the product listing and which has its own `/dev`
page, and demo products such as Hello World. Today the landing page keeps the
demos out with a hardcoded list of product names in the UI, which breaks the
moment a product is renamed and cannot cover `custom` without also hiding it
from the client.

## What Changes

- Add a third visibility value, `unlisted`: listed by the product API to every
  caller exactly like `public`, and deployable like `public`, but not shown in
  the storefront.
- The storefront (landing page showcase, hero, pricing) shows only `public`
  products, filtering on `visibility` from the product listing. The hardcoded
  name list it uses today is removed.
- The admin visibility control and the `caelus create-product` /
  `update-product --visibility` options offer `unlisted`, with wording that
  says where an unlisted product does and does not appear.
- An Alembic migration adds `unlisted` to the `productvisibility` Postgres
  enum. No row changes; the operator sets `unlisted` on the products that
  need it after rollout.

Not changed: visibility stays database-owned runtime state that the catalog
does not declare and the reconciler never writes after creation; deployment
creation, plans and templates do not branch on visibility; the `freepod`
client has no visibility handling and needs no release.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `product-visibility`: the set of values, which values the end-user listing
  includes, the storefront filter, the admin control's choices, and the
  migration that adds the value.

## Impact

- `api/app/models/core.py`: `ProductVisibility.UNLISTED`.
- `api/app/services/products.py`: the end-user listing includes `unlisted`.
- `api/app/cli.py`, `api/app/api/products.py`: help and endpoint docs.
- `api/alembic/versions/`: one migration extending the enum type.
- `ui/src/api/types.ts`, `ui/src/components/ProductVisibilityControl.tsx`,
  `ui/src/components/landing/useLandingProducts.ts`.
- Rollout: after deploying, an operator sets `visibility = unlisted` on
  Hello World, NaaS and `custom` per environment. Until then Hello World and
  NaaS appear on the landing page, since the name list is gone.
