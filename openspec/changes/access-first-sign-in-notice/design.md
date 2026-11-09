# Design

## Context

An entry is bound in one place: `admitted` (`daemons/app-auth/access.go`) calls `store.bindEntry` when the broker issues a header sign-in code or the provider issues an OIDC authorization code. `bindEntry` is a single `UPDATE app_access_entry SET subject, name, bound_at WHERE id = $1 AND subject IS NULL`, so exactly one caller wins a race. A unique violation means another entry of the deployment already holds that subject. The role already reads `deployment.user_id` and `hostname`.

`notification-outbox` provides the outbox, the `md`-style escaping convention, and the sender. See that change's design.

## Goals / Non-Goals

**Goals:**

- Exactly one notice per binding, queued atomically with it whenever the outbox accepts it.
- No new path between app-auth and the API.

**Non-Goals:**

- Notifying the person who signed in. They know.
- The person's display name in the notice. It comes from their Keycloak profile, which they can set to anything.
- Unsubscribing, or a per-deployment switch. The kind is marked unsubscribable for when that exists.
- Notices for `anyone` deployments, which have no list to bind.

## Decisions

### D1. Queue inside `bindEntry`'s transaction, under a savepoint

`bindEntry` becomes:

```
BEGIN
UPDATE app_access_entry SET … WHERE id = $1 AND subject IS NULL RETURNING deployment_id, email
  (no row → COMMIT, false; 23505 → ROLLBACK, false, as today)
SELECT user_id, hostname FROM deployment WHERE id = <deployment_id>
SAVEPOINT notice
INSERT INTO notification_outbox (…) VALUES (…) ON CONFLICT (kind, dedupe_key) DO NOTHING
  (error → ROLLBACK TO SAVEPOINT notice, log a warning)
COMMIT
```

The binding and its notice commit together, and a binding that loses the race or rolls back queues nothing. The dedupe key `first-sign-in:<entry id>` makes a second insert for the same entry harmless. That can't happen through `WHERE subject IS NULL` today, but it costs nothing. A re-added entry has a new ID, so it notifies again, as the spec asks.

The savepoint keeps sign-in independent of the notice. A missing kind, a missing grant or a broken constraint loses the notice, logged, and never refuses a person their access.

*Alternative:* let an insert failure fail the binding. Rejected: access is the service's purpose and the notice is secondary, and a rollout-order slip (D4) would otherwise refuse every new invitee.

### D2. The owner is addressed as a user

`recipient_user_id = deployment.user_id`. The sender resolves the owner's current address, and a later push channel can reach the owner without changing this code.

### D3. app-auth may only notify users

The bootstrap grants `INSERT (kind, recipient_user_id, subject, heading, body, action_label, action_url, reason, dedupe_key)` on `notification_outbox`, deliberately without `recipient_email`.

app-auth can then only notify people who have a Freepod account. If it were compromised, it couldn't mail arbitrary addresses through the relay. That is the open-relay exposure an unrestricted producer would have. It gets no `SELECT`; `ON CONFLICT DO NOTHING` needs none.

### D4. Rollout order

The migration seeding `access.first_sign_in` and the bootstrap grant run with the API's rollout (worker init containers). app-auth's new version is applied afterwards through `tf/app`.

Applied the other way around, the savepoint loses the notices of the bindings in between, and everything else keeps working.

### D5. The notice

A fixed text in `daemons/app-auth/notice.go`. Every inserted value goes through an `mdEscape` that backslash-escapes ASCII punctuation, the same rule as the API's `md`.

- **subject:** `<email> signed in to <hostname>`
- **heading:** `Someone you invited has signed in`
- **body:** `<email>, whom you gave access to <hostname>, signed in to it for the first time. If the app creates accounts when people first sign in, it now knows them, so you can share with them or give them a role there.`
- **action:** `Open the app` → `https://<hostname>`
- **reason:** `You received this email because you own <hostname> on Freepod and gave <email> access to it.`

`hostname` is the deployment's own, even when the sign-in came through a `preview-` alias.

## Risks / Trade-offs

- [The binding happens when the code is issued, not when the app redeems it. If the app's callback fails, the owner is told about an account the app never created] → Accepted. The window is the browser's redirect to the app, and moving the binding would change admission for every protocol.
- [An owner with many invitees gets many emails] → Bounded by the invitation limit (100 a day per owner), since each entry notifies once. Unsubscribing comes with the kind's flag later.
- [A lost notice is visible only in app-auth's logs] → Accepted for a notice whose absence harms nothing. The binding time still shows in the Access dialog.

## Migration Plan

1. Merge after `notification-outbox` is live on the environment.
2. Roll out the API, which runs the migration and the bootstrap grant. Then apply the new daemons version for app-auth.
3. Verify on dev: invite a test address, sign in with it, and see one `access.first_sign_in` row from `caelus_app_auth` end `sent` to the owner. Sign in again and see no second row.
4. Rollback: revert app-auth's image. The kind and the grant are harmless without it.
