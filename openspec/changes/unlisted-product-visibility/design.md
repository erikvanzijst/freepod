## Context

`visibility` is a Postgres enum column (`productvisibility`) on `product`. The
only code that branches on it is the end-user product listing
(`list_products`), which keeps `public` products for anonymous and non-admin
callers and returns everything to administrators. Direct reads
(`GET /api/products/{id}`), templates, plans and deployment creation never
consult it. The product read schema already carries `visibility`, including
in the anonymous listing.

The storefront (landing showcase, hero constellation, pricing) is rendered for
signed-out visitors from that same anonymous listing, and today drops demo
products by name in the UI.

Every `alembic upgrade` runs in one transaction holding a transaction-scoped
advisory lock (`api/alembic/env.py`), so a revision cannot commit part-way.

## Goals / Non-Goals

**Goals:**
- One more value that the API treats exactly as `public` and the storefront
  treats as hidden.
- Remove the name-based storefront filter.

**Non-Goals:**
- Hiding unlisted products from the signed-in dashboard's product grid. That
  grid is not the storefront; it lists everything the API lists to the caller,
  as it does for administrators and `admin` products today.
- Any change to the catalog format or reconciler. Visibility stays out of
  catalog files, and products the reconciler creates still start `admin`.

## Decisions

### D1: A third enum value rather than a separate `listed` flag

`unlisted` is a point between `public` and `admin` on one axis: who is offered
the product. A boolean beside `visibility` would admit the meaningless
`admin` + unlisted combination and spread one operator decision over two
fields in the API, the CLI and the admin UI. The enum keeps a single control.

### D2: The API listing includes `unlisted`; the storefront filters

The product API has no notion of a storefront, and the `freepod` client
discovers `custom` through the listing, so the API must list unlisted products
to everyone. Hiding them is a presentation decision made where the storefront
is built.

The storefront keeps only `visibility === 'public'` rather than dropping
`unlisted`. For a signed-out visitor the two are identical, since the listing
never contains `admin` products. Keeping `public` only also holds if an
administrator's session ever reaches the storefront queries, and does not
depend on future values being added to the exclusion.

Alternative considered: a query parameter such as `?listed=true` on
`GET /api/products`. Rejected: it adds API surface for a filter the client
already has the data to apply, and a second listing contract to keep in
lockstep with the CLI.

### D3: Migration adds the value inside the upgrade transaction

`ALTER TYPE productvisibility ADD VALUE IF NOT EXISTS 'unlisted'` runs inside
the transaction (allowed since PostgreSQL 12). Alembic's `autocommit_block()`
is not used: it would commit the surrounding transaction and release the
advisory lock that serializes concurrent migration runners. The cost is that
no later revision in the same upgrade may write `'unlisted'`, since a new enum
value is unusable until its transaction commits. This revision writes no rows.

Downgrade cannot drop an enum value in place. It moves `unlisted` rows to
`public`, which keeps them reachable through the API and the client (the
behavior a rollback must not break), then rebuilds the type without the value.

## Risks / Trade-offs

- [Storefront shows Hello World and NaaS between rollout and the operator
  setting them `unlisted`] → The window is the gap between rollout and one
  `update-product` per product; the PR calls out the step.
- [A rolled-back API (pre-change code) reading an `unlisted` row fails to
  parse the enum] → Downgrade the migration as part of any rollback, which
  rewrites those rows to `public`.

## Migration Plan

1. Roll out: the migration adds the value; no rows change.
2. Per environment, an operator sets `unlisted` on Hello World, NaaS and
   `custom` (`caelus update-product <id> --visibility unlisted` or the admin
   UI).
3. Rollback: `alembic downgrade` to the previous revision before deploying the
   previous image.
