# Proposal

## Why

Many apps behind a `listed` access list create a person's account only when they first sign in. Nextcloud with user_oidc is one, and so are Immich and Discourse. Until then the owner cannot share with that person or give them a role, and the owner has no way to know when that moment has come short of checking the Access dialog. The first sign-in is also when an invitation is, in effect, accepted. The owner should hear about it.

## What Changes

- When an access-list entry is first tied to the account that signs in with it, the deployment's owner is notified by email: who signed in, to which app, and that the app may now know them.
- app-auth, which binds the entry, queues the notice itself in the notification outbox (from `notification-outbox`), in the same transaction as the binding, with the entry's ID as its dedupe key.
- A new notification kind, `access.invitation_accepted`, beside `access.invitation`, marked unsubscribable for when unsubscribing exists.
- The app authentication role may queue notifications.
- If the notice can't be queued, the sign-in still succeeds and only the notice is lost.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `app-access-list`: the owner is notified when an entry is first used.
- `app-auth-data-model`: the app authentication role may queue notifications.

## Impact

- **app-auth** (`daemons/app-auth/`):
  - `bindEntry` runs in a transaction that also queues the notice;
  - a Markdown escape helper and the notice's fixed text;
  - the daemons version is bumped.
- **Database**: a migration seeds the `access.invitation_accepted` kind. `tf/app/caelus/app-auth-bootstrap.sql` grants `INSERT` on the outbox's producer columns.
- **Depends on** `notification-outbox` being deployed. On rollout, the API (migration and bootstrap) goes before app-auth.
- No API, UI or chart changes.
