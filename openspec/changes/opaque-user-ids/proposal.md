# Proposal

## Why

`user.id` is a Postgres sequence, and it is exposed everywhere: in every `/api/users/{user_id}/…` path, on `/api/me`, on deployment and usage responses, in `freepod whoami`, and inside build image references (`{user_id}@sha256:…`). Anyone with an account can read off how many accounts exist, watch growth by signing up twice, and guess other accounts' ids.

## What Changes

- **BREAKING (schema):** `user.id` becomes a short string primary key that the application assigns when it creates a row. The database stops generating it and enforces only uniqueness and format.
- New accounts get a random 12-character lowercase base36 id that is never all digits.
- Existing accounts keep their current number as their id, in decimal text form (`42` → `"42"`). Nothing is backfilled or reissued.
- The four columns that reference users change type with the key: `deployment.user_id`, `subscription.user_id`, `user_ssh_key.user_id` and `var.created_by`.
- **BREAKING (API wire type):** every user id in the API becomes a JSON string instead of a number: path parameters, `id` on user reads and `/api/me`, `user_id` on deployments, subscriptions and usage reports, and the admin `user_id` query filter. The values for existing accounts are unchanged apart from the type.
- Registry repository names (`u/{id}`), pull usernames (`pull-{id}`) and the pull-credential derivation are built from the string id. They are byte-identical for existing accounts, so no images, releases or published pull secrets move.
- The UI treats user ids as strings. The `freepod` CLI already treats the id as opaque and needs no change. Released CLI versions keep working, so the client version gate is not raised.
- Out of scope: subscription ids and every other integer key.

## Capabilities

### New Capabilities

- `user-identifier`: how a user's id is assigned, what it looks like, how existing ids carry over, and which derived names it feeds (registry repositories and pull credentials).

### Modified Capabilities

- `authorization-guards`: `require_self` takes its `user_id` path parameter as a string instead of an integer.

## Impact

- **Database:** one Alembic migration converts `user.id` and its four referencing columns to `varchar(12)`, drops the sequence, and adds a format CHECK. It takes a brief exclusive lock on `user` and the four referencing tables. Downgrade is unsupported once a non-numeric id exists.
- **API (`api/`):** the `UserORM` key and id generator, about 116 `user_id: int` annotations across models, services and routes, the registry pull-username regex and `int()` parse (`registry_tokens.py`), and the `int(user_id)` in artifact object keys (`artifacts.py`). The test suite has many integer user-id fixtures to update.
- **UI (`ui/`):** `userId: number` → `string` in `api/types.ts`, `api/endpoints.ts` and their callers. `AdminUsagePanel` stops treating its `user` query parameter as digits.
- **Go daemons (`daemons/ssh-auth`, `daemons/app-auth`):** production SQL only joins on `user_id` and is type-agnostic. Test fixtures that insert integer user ids need updating.
- **CLI (`cli/`):** no functional change. Type hints `user_id: int` become `str`.
