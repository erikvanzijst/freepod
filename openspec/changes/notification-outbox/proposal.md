# Proposal

## Why

The API sends its own mail: each sender formats a message and talks SMTP inline, and nothing records what was sent. Other services, starting with app-auth, now need to notify people too, and they should not each grow a mailer. A database outbox gives every platform service one way to hand over a message, under table and column grants, with a lasting record of what was queued and how it ended. Keeping the message apart from its delivery also leaves room for transports other than email later.

## What Changes

- A `notification_outbox` table where a platform service deposits one message per recipient: a `kind`, the recipient (a Freepod user, or an address for someone without an account), a subject, an optional heading, a Markdown body, an optional action link, and the reason the recipient gets it.
- A `notification_kind` table listing the kinds that may be queued, each marked as whether it could be unsubscribed from. The unsubscribe mechanism itself is not part of this change.
- `origin` is set by the database to the role that inserted the row and cannot be supplied by the producer.
- An optional dedupe key, unique per kind, so a producer that retries cannot queue the same message twice.
- Each row moves from `pending` to exactly one of `sent`, `failed` or `suppressed`, with its attempts, its last error and the time it was sent.
- A new Go daemon, `notifier`, in the daemons image. It wakes on a Postgres notification raised whenever a row becomes pending, sweeps on a timer as a fallback, renders the Markdown into Freepod's mail layout, and delivers through the shared SMTP relay. It retries a few times at once and then gives up. Where no relay is configured, it marks rows `suppressed`.
- **BREAKING (internal)**: the API stops sending mail. Access-list invitations and the database quota notices are queued in the outbox, in the same transaction as the change that causes them. `app/services/mailer.py` and `app/services/mail_layout.py` are removed, along with the API's `CAELUS_SMTP_*` settings.
- The upgrader is out of scope. It is a tenant deployment, not part of the platform, and keeps its own mail.

## Capabilities

### New Capabilities

- `notification-outbox`: the outbox contract between producers and the sender. Covers the columns, recipients, kinds, origin, dedupe keys, delivery states, which roles may queue, and the wake-up raised for pending rows.
- `notification-sender`: the daemon that delivers queued notifications. Covers picking up pending rows promptly and after missed wake-ups, rendering and the Freepod layout, Markdown safety, retries and terminal states, suppression without a relay, and running more than one replica safely.

### Modified Capabilities

- `app-access-list`: invitations are queued in the outbox with the addition, instead of sent by the API after it.

## Impact

- **Database**: new tables `notification_kind` (seeded with `access.invitation` and `database.quota`) and `notification_outbox`, plus a trigger that raises the wake-up. A new `caelus_notifier` role is created by a bootstrap SQL beside app-auth's.
- **API**:
  - a small queueing service with a Markdown escape helper;
  - `app_access.add_entry` queues the invitation in its transaction, and the access endpoint no longer sends it in a background task;
  - `relational_storage` queues its threshold notices;
  - the mailer, the mail layout, their tests and the SMTP settings are removed.
- **Daemons**: new module `daemons/notifier/` (pgx, goldmark, `net/smtp`), with the Freepod layout ported from `mail_layout.py`. The image gains `/notifier` and its version is bumped.
- **Infrastructure** (`tf/app/caelus`):
  - a `caelus-notifier` deployment in the platform namespace;
  - the role's secret and bootstrap, run by the worker's init containers like app-auth's;
  - the SMTP host and sender address move from the API configmap to the notifier;
  - the new image variable.
  `scripts/rollout.sh` learns the new deployment.
- **Docs**: `AGENTS.md` architecture notes and `daemons/README.md`.
