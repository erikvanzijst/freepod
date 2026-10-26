# Design

## Context

`user.id` is an `integer` primary key backed by `user_id_seq`. Four columns reference it: `deployment.user_id`, `subscription.user_id`, `user_ssh_key.user_id` (`ON DELETE CASCADE`) and `var.created_by`. No other table stores a user id. Usage reports reach the owner through `deployment`, and builds through their deployment.

The id is also built into names and values outside the database:

- registry repository `u/{id}`, pull username `pull-{id}`, and the pull password `HMAC(key, "registry-pull:{version}:{id}")` (`registry_tokens.py`);
- build image references `{id}@{digest}`;
- artifact object keys `…/{int(user_id)}/…` (`artifacts.py`);
- the namespace label `caelus.dev/owner-id`, which feeds the Grafana dashboards;
- the Helm value `caelus.owner.id`. The `custom` chart's schema types it as `integer`, and its image-ownership assertion requires the repository half of `image` to match `^[0-9]+$` before comparing it with `toString .Values.caelus.owner.id`.

Clients: the `freepod` CLI reads `id` from `/api/me` and only interpolates it into paths. The UI types it as `number`. The Go daemons only join on `user_id` in SQL.

The in-flight `keycloak-subject-join-key` change edits `get_current_user` and adds a column to `user`. It doesn't touch the key, so the two changes are independent apart from Alembic ordering.

## Goals / Non-Goals

**Goals:**
- Every name derived from an existing account's id stays byte-identical, so no registry data, artifact objects, published pull secrets or dashboard series move.
- Released `freepod` CLI versions keep working against the new API.

**Non-Goals:**
- Hiding the ids existing accounts already have. Their numbers stay visible. Only accounts created after the cutover are unguessable.
- A `me` path alias or flatter, ownership-implied routes.
- Subscription ids, product and template ids, and every other integer key.

## Decisions

### D1. Change the key itself instead of adding a public-id column
`user.id` becomes `varchar(12)`. The alternative was a separate `public_id` column with the integer kept internally. That leaves two identities: every boundary has to translate, and any forgotten spot (a label, a log line, a Helm value) leaks the integer again. With only four referencing columns, converting the key is a small migration, and afterward there is only one identity to handle.

### D2. Existing ids become their decimal text
The migration converts the columns with `USING id::text`. There's no backfill and no reissue: `42` becomes `"42"`, and every derived name (`u/42`, `pull-42`, the HMAC message, artifact keys, `owner-id=42`) is unchanged byte for byte. That is what makes the registry, artifact store and dashboards a non-event.

### D3. Twelve characters of base36, never all digits
The id is drawn with `secrets.choice` over `0-9a-z`, reusing the `_BASE36` alphabet the namespace suffix already uses (`reconcile_naming.py`), and redrawn if it comes out all digits.

- **Size:** 12 characters give about 62 bits. The birthday bound makes a collision negligible at any realistic account count, and the primary key rejects one if it ever happens.
- **Alphabet:** lowercase only, because the id is embedded in registry repository names and namespace label values, which must be lowercase. That rules out base62 and nanoid's default alphabet.
- **Crockford base32 considered:** it was the alternative (unambiguous to read aloud), but matching the existing in-repo alphabet won, since nobody types these ids by hand.
- **Redrawing all-digit values:** this keeps the new id space disjoint from the legacy one by construction, so a new id can't collide with an old one, and anything that sees a digits-only id can rely on it being legacy (D6 does).

### D4. The application assigns the id; the database enforces it
`UserORM.id` becomes `str` with a `default_factory`, so both creation sites (`deps.get_current_user` and the operator CLI's `UserORM(email=…)`) get an id without code changes. The migration drops the column default and `user_id_seq`, and adds `CHECK (id ~ '^[0-9a-z]{1,12}$')`. Length is a range, not exactly 12, because legacy ids are shorter. An insert that omits the id fails on `NOT NULL`.

### D5. One migration rewrites the key and its four foreign keys
The migration runs in one transaction:

1. Drop the four FK constraints, looking up their names in `pg_constraint` rather than hardcoding them.
2. `ALTER COLUMN … TYPE varchar(12) USING …::text` on `user.id` and the four referencing columns. Postgres rebuilds the primary key and the `ix_*_user_id` indexes as part of the type change.
3. Drop the default and the sequence.
4. Add the CHECK.
5. Recreate the FKs with their original `ON DELETE` behavior.

The tables are small, so the `ACCESS EXCLUSIVE` locks last milliseconds. `downgrade()` raises `NotImplementedError`, as the earlier `deployment_id_to_uuid` migration does: once a non-numeric id exists, converting back would lose data.

### D6. `caelus.owner.id` stays an integer for legacy ids
Deployment releases can be re-applied, including rollbacks, against older `custom` chart versions whose schema requires an integer `owner.id`. If the reconciler started sending `"42"`, every existing custom deployment would fail to render on the old charts. So the reconciler projects `owner.id` as an `int` when the id is all digits, and as the string otherwise. Because of D3 the all-digit case is always a legacy account.

A new `custom` chart version:
- types `owner.id` as `["integer", "string"]`;
- relaxes the repository assertion from `^[0-9]+$` to `^[0-9a-z]{1,12}$`.

The `toString` comparison already in the template then works for both.

Accounts created after the cutover are only ever offered the new chart version, so they never hit an old one. The alternative was to always send a string and first move every custom deployment onto the new chart. It was rejected because it breaks rolling back to old releases, and it adds an operational step to the rollout.

### D7. Plain `str` at the API, with no numeric fallback
Path parameters, response fields and the usage filter become `str`. A value matches an id only if the strings are identical: `042` is not `42`. Today FastAPI's int coercion accepts `042`, but no client sends that, and exact matching is what the new id space needs. Older CLIs get a string in `id` and interpolate it exactly as before, so `client_version_gate` stays where it is.

## Risks / Trade-offs

- [An `int` annotation or `int()` call somewhere is missed and mishandles a non-numeric id] → Make the test suite's default user fixture get a random non-numeric id, so every API test exercises the new id space. Keep a small set of legacy-id fixtures for D2 and D6.
- [The UI sorts or compares ids numerically somewhere] → Changing `userId` to `string` in `types.ts` makes the compiler report every use. The admin users list has no `ORDER BY`. Give it `ORDER BY created_at` so the listing order doesn't come from the physical row order.
- [Dashboards that treat `caelus.dev/owner-id` as numeric] → Prometheus labels are already strings. Only panels that sort by owner id would change order, which is cosmetic.
- [Migration conflicts with `keycloak-subject-join-key`] → Whichever change merges second rebases its `down_revision`. Neither touches the other's columns.
- [A tenant pins an old `custom` chart version and is then rolled back to a release from before their account existed] → This can't happen: a new account has no release older than the account itself.

## Migration Plan

1. Publish the new `custom` chart version and point the catalog's `custom` template at it. Old templates stay in place for rollback. This is safe under the current API, which sends integers.
2. Deploy the API with the migration. The migration runs on startup. Existing accounts keep working unchanged, and accounts created from then on get opaque ids.
3. The UI ships in the same image set as the API. CLI users don't need to upgrade.

Rollback: up to the first sign-up after step 2, the migration can be reversed by hand (`ALTER … TYPE integer USING id::integer`, then recreate the sequence at `max(id)+1`). After that, rolling back means restoring from backup. That's why `downgrade()` refuses.
