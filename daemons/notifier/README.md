# notifier — delivers the notification outbox

Platform services queue messages for people as rows in `notification_outbox`;
this renders each one into Freepod's mail layout and sends it through the
shared SMTP relay. It wakes on the table's `notification_outbox` LISTEN
channel and sweeps every minute for wake-ups it missed.

Spec: [notification-outbox](../../openspec/specs/notification-outbox/spec.md),
[notification-sender](../../openspec/specs/notification-sender/spec.md)

## Configuration

| Variable | |
|---|---|
| `NOTIFIER_DATABASE_URL` | Platform database, as `caelus_notifier` ([bootstrap](../../tf/app/caelus/notifier-bootstrap.sql)) |
| `NOTIFIER_SMTP_HOST`, `NOTIFIER_SMTP_PORT` | The relay; port defaults to 25 |
| `NOTIFIER_SMTP_FROM` | Sender address, and the domain of each `Message-ID` |

Without a host or sender address every notification is marked `suppressed`.

## Producing

Insert one row per recipient in the producer's own transaction. Escape every
interpolated value as Markdown (backslash before each ASCII punctuation
character, as `app.services.notifications.md` does); the body's own links stay
links. A new kind is a row in `notification_kind`, added by a migration.

## Requeueing

A row is `failed` after three attempts a couple of seconds apart. Setting it
back to `pending` wakes the notifier, which tries it again:

```sql
UPDATE notification_outbox SET state = 'pending'
 WHERE state = 'failed' AND created_at > now() - interval '1 day';
```

## Testing

The store and listener tests run against `CAELUS_TEST_DATABASE_URL`, migrated
to head, as the role the bootstrap creates.
