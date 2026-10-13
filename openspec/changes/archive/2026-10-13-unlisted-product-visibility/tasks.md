## 1. Backend

- [x] 1.1 Add `ProductVisibility.UNLISTED` in `api/app/models/core.py`, and verify `caelus create-product` / `update-product --visibility unlisted` accept it and an invalid value is still refused (CLI tests in `tests/test_product_visibility.py`)
- [x] 1.2 Add the Alembic revision extending the `productvisibility` enum in the upgrade transaction, with a downgrade that rewrites `unlisted` to `public` and rebuilds the type (design D3), and verify migration tests for upgrade leaving rows unchanged, accepting `unlisted`, keeping the `admin` default, and downgrade
- [x] 1.3 Include `unlisted` in the end-user listing in `list_products`, and verify listing tests for anonymous and non-admin callers that assert the product and its reported `visibility`
- [x] 1.4 Verify by test that an unlisted product's plans read anonymously and that a non-admin user can deploy it
- [x] 1.5 Verify by test that the catalog reconciler leaves an `unlisted` curated product's visibility unchanged and that `catalog curate` writes no visibility for it
- [x] 1.6 Update the visibility wording in the `caelus` option help and the `GET`/`PUT /api/products` endpoint docs

## 2. Frontend

- [x] 2.1 Add `unlisted` to `ProductVisibility` in `ui/src/api/types.ts`
- [x] 2.2 Offer `Unlisted` in `ProductVisibilityControl` with helper text saying it is available through the API and CLI and hidden from the storefront, and verify component tests for display and persisting the change
- [x] 2.3 Replace the name list in `loadVisibleProducts` with a `public`-only filter (design D2), and verify tests that unlisted and admin products are dropped and a public "Hello World" is kept

## 3. Integration

- [x] 3.1 Run the full `api/` pytest suite, `npx tsc -b`, eslint on touched UI files, and vitest
- [x] 3.2 Validate the change with `openspec validate unlisted-product-visibility --strict`

## Workflow follow-up

- After rollout, set `unlisted` on Hello World, NaaS and `custom` in each
  environment.
- Archive the change after merge, syncing the delta into
  `openspec/specs/product-visibility/spec.md`.
