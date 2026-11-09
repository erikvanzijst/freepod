# Design

## Context

The API sends mail from two places today, both through `app/services/mailer.py` (`smtplib` to the in-cluster relay, never raising) and `app/services/mail_layout.py` (Freepod's layout, kept in step with Keycloak's email theme):

- `app_access.send_invitation`, which the access endpoint runs as a FastAPI background task after the addition commits;
- `relational_storage._notify_threshold`, which db-worker's quota sweep calls, recording `warned_threshold` only once the relay accepted the mail so that an outage is retried on the next sweep.

Nothing records what was sent. app-auth, which only holds database grants, is about to need mail of its own (the next change, `access-first-sign-in-notice`). The relay is `smtp.mailer.svc.cluster.local:25`, unauthenticated, and has no NetworkPolicy of its own, so any pod in the platform namespace can reach it. Go daemons ship together in the daemons image, one static binary per `daemons/<name>/` module on `scratch`, and app-auth's store tests already run against the shared test Postgres with the real bootstrap SQL applied.

## Goals / Non-Goals

**Goals:**

- One way for any platform service to queue a message, needing only table and column grants.
- A durable record of every queued message and how it ended.
- Message content decoupled from the transport, so that a later push or in-app channel needs no producer changes beyond addressing users rather than addresses.
- One process that renders and delivers, small enough to cost little.

**Non-Goals:**

- Unsubscribing. `notification_kind.unsubscribable` is recorded, but no preference storage, signed link, `List-Unsubscribe` header or footer link is built.
- Retention and purging. The table grows without bound until a later change, after the subsystem has proved itself.
- Rate limits per origin or per kind. Producers are trusted platform services.
- Backoff, scheduled retries or dead-letter handling beyond the `failed` state.
- Attachments, CC and BCC.
- The upgrader, which is a tenant deployment with its own mail.
- Transports other than SMTP.

## Decisions

### D1. One row per recipient, addressed by user where possible

`recipient_user_id` (FK to `user`, `ON DELETE CASCADE`) or `recipient_email`, with `CHECK (num_nonnulls(recipient_user_id, recipient_email) = 1)`.

A user is resolved to their address at send time, which follows an email change. It is also what a push or in-app transport will need, since those reach accounts, not addresses. An address is only for people without an account, such as invitees. One row per person gives each delivery its own state, error and future preference check.

*Alternative:* `to`/`cc`/`bcc` arrays, as SMTP models it. Rejected: those concepts don't exist for other transports, and one row then holds several outcomes.

### D2. Schema

```
notification_kind
  kind            text primary key          -- 'access.invitation'
  unsubscribable  boolean not null

notification_outbox
  id               uuid primary key default gen_random_uuid()
  kind             text not null references notification_kind
  origin           text not null default session_user
  recipient_user_id integer references "user" on delete cascade
  recipient_email  text
  subject          text not null
  heading          text
  body             text not null            -- Markdown
  action_label     text
  action_url       text                     -- CHECK: both or neither; 'https://' prefix
  reason           text not null
  dedupe_key       text
  state            notification_state not null default 'pending'
  attempts         integer not null default 0
  created_at       timestamp not null default (now() at time zone 'utc')
  last_attempt_at  timestamp
  sent_at          timestamp
  error            text
  unique (kind, dedupe_key)
  index (created_at) where state = 'pending'
```

`notification_state` is a Postgres enum: `pending`, `sent`, `failed`, `suppressed`.

A UUID key keeps producers off any sequence grant.

The unique constraint is per kind, so a key only has to be unique within its kind. Postgres treats NULLs as distinct by default, so rows without a key never conflict.

`reason` lives on the row, not on the kind, because some reasons name a person, for example the inviting owner.

`body` is `NOT NULL` for now. A future purge can relax that on terminal rows.

The timestamps are naive UTC, as in the rest of the schema.

### D3. Origin is the inserting role

`origin` defaults to `session_user`, and producer roles get `INSERT` on every column except `origin`, `state`, `attempts`, the timestamps and `error`. A producer therefore cannot claim to be another service, and cannot queue a row that is already terminal.

The API and its workers share the schema owner's role, so their rows all carry that role's name. `kind` identifies the subsystem within it.

*Alternative:* `origin` as a free-text producer column. Rejected: it would be unverifiable.

### D4. Producers queue in their own transaction

A producer inserts the row in the same transaction as the change that causes it. The message then exists exactly when the change commits, and the addition, binding or quota state change needs no separate "send after commit" step.

A producer that sets a dedupe key inserts with `ON CONFLICT (kind, dedupe_key) DO NOTHING`, which needs no `SELECT` grant.

In the API, `app/services/notifications.py` offers:

- `queue(session, *, kind, user_id=None, email=None, subject, body, reason, heading=None, action=None, dedupe_key=None)`, which adds to the caller's session and never commits;
- `md(text)`, which backslash-escapes every ASCII punctuation character. CommonMark allows that escape on any of them, so an escaped value is always literal text.

Bare URLs and addresses don't become links, because the renderer has no autolink extension (D7).

### D5. Wake-up by trigger, sweep as fallback

A row-level `AFTER INSERT OR UPDATE OF state` trigger, `WHEN (NEW.state = 'pending')`, calls `pg_notify('notification_outbox', '')`. Postgres delivers it on commit and merges identical notifications within a transaction. Producers can't forget it, and it needs no privilege. The sender's own updates to terminal states don't fire it. A hand requeue does.

The sender keeps one dedicated connection, not taken from the pool, and runs:

```
connect; LISTEN notification_outbox; sweep
loop: WaitForNotification(timeout 60s); sweep   -- on a wake-up or a timeout alike
on a connection error: back off 5 s, reconnect, start over
```

Running `LISTEN` before the first sweep closes the gap between them. A row committed during the sweep is either found by it or leaves a wake-up already queued. The timeout covers wake-ups lost while the sender was down or disconnected, which Postgres doesn't keep.

*Alternative:* polling alone. Rejected: either it adds latency or it queries constantly.

### D6. Claim, deliver and record in one transaction per row

A sweep repeats until nothing is pending:

1. `BEGIN`
2. `SELECT … WHERE state = 'pending' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1`, joined to `user` for the address
3. deliver, with up to three attempts two seconds apart
4. `UPDATE` to the terminal state
5. `COMMIT`

Holding the row lock through the SMTP exchange makes replicas safe, and a crash before step 5 leaves the row pending (at-least-once delivery). The worst-case lock is about 35 seconds: three 10-second SMTP timeouts plus the pauses.

`attempts` counts every attempt across requeues.

`Message-ID` is `<row id>@<sender domain>`, so a duplicate after a crash carries the same ID and mail clients can collapse it.

### D7. Rendering: goldmark, an inline-style pass, and a text pass

The body is parsed once with goldmark: CommonMark, no extensions, no `WithUnsafe`, so raw HTML is omitted. Two passes over the AST follow:

- **HTML pass:**
  - drops links and images whose scheme isn't `https`, `http` or `mailto`, keeping a link's text;
  - adds the layout's inline styles to paragraphs, links and lists, since mail clients strip `<style>`.
- **Plain-text pass:** renders the same tree to text, with a link as `text (url)`. Escapes and markup don't leak into the text part.

The layout is `mail_layout.py`'s table HTML, ported to an embedded Go `html/template`. Heading (or subject), subject, label and reason go through the template's escaping as text. The body is the only `template.HTML`. The note under the button that `mail_layout` offered is dropped: no remaining sender uses it, and a body paragraph replaces it.

The "change the two together" note about the Keycloak email theme moves with the template.

### D8. SMTP

`net/smtp` to `SMTP_HOST:SMTP_PORT`, unauthenticated with no TLS, the same as `mailer.py` today. The relay authenticates upstream to Scaleway.

The message is built by hand: `multipart/alternative` with text, then HTML, both quoted-printable UTF-8; RFC 2047 encoded `Subject`; `From`, `To`, `Date` and `Message-ID`.

An empty `SMTP_HOST` or `SMTP_FROM` means suppression. The sender logs this once at startup, and each row it reaches is marked `suppressed`.

### D9. The quota notices treat queueing as sent

`_notify_threshold` queues and returns `True`, so `warned_threshold` is recorded in the same transaction as the queued notice. Previously a relay outage left it unset and the next minute's sweep tried again. Now an outage that outlasts the sender's three attempts leaves a `failed` row instead.

This is accepted: the failure is now recorded and can be requeued, where before the only trace was a log line. It also matches the delivery model for every other kind.

### D10. A separate Go process

The sender is `daemons/notifier`, deployed as `caelus-notifier` in the platform namespace beside Postgres, and not a db-worker tick:

- db-worker runs its ticks in sequence, so a long daily purge would hold mail up;
- a Python process costs far more memory than a static Go binary.

It runs as the new `caelus_notifier` role, created by `tf/app/caelus/notifier-bootstrap.sql` in a worker init container, like `app-auth-bootstrap.sql`, after `migrate`. Its grants:

- `SELECT` on `notification_outbox`;
- `SELECT (id, email)` on `"user"`;
- `UPDATE (state, attempts, last_attempt_at, sent_at, error)` on `notification_outbox`, which also allows `FOR UPDATE`.

`LISTEN` needs no grant.

The deployment runs one replica with the `Recreate` strategy; D6 makes a second replica safe, but nothing needs one. It has no listener and no probes: it is idle when nothing is queued, and a stuck connection is replaced through the reconnect loop. Requests are sized to its idle usage, about 10 Mi, by the platform's convention.

## Risks / Trade-offs

- [A relay outage longer than a few seconds turns every message in it into `failed`] → It is recorded, with the error. An operator requeues with `UPDATE notification_outbox SET state = 'pending' WHERE state = 'failed' AND created_at > …`, which wakes the sender. Scheduled retries can come later if outages prove common.
- [The table holds message bodies, personal data, with no retention] → Accepted for v1, as a non-goal. A purge, and its mention in the privacy policy, follow once the subsystem has proved itself.
- [Any producer role can mail anyone, in Freepod's layout] → Accepted: producers are platform services and their grants are reviewed in the bootstrap SQL. `origin` records which role queued each row.
- [The sender's goldmark scheme filter or style pass misses a node type] → Tests render a fixed set of hostile and ordinary bodies to HTML and text and assert on both. goldmark is pinned in `go.mod`.
- [Messages queue while the notifier is missing or down] → They wait as `pending` and go out once it runs. This also makes rollout order irrelevant.
- [Moving the layout to Go splits it from the Python tests that checked it] → The ported tests come with it (`render_test.go`), and the API's tests assert on the queued rows instead.

## Migration Plan

1. One release carries the following. Nothing in it depends on the order the parts start in:
   - the migration, which creates the enum, both tables, the seeded kinds and the trigger, and has a `downgrade` that drops them;
   - `notifier-bootstrap.sql`;
   - the API change;
   - the daemons version that adds `/notifier`;
   - the `caelus-notifier` deployment.
2. On rollout, the API and db-worker begin queuing as soon as they run the new image. The notifier sends whatever is pending when it starts.
3. Verify on dev:
   - add an access-list entry and see one `sent` row and the email;
   - stop the notifier, add another, start it, and see it sent;
   - point the notifier at a bad port and see `failed` with three attempts, then requeue it.
4. Rollback: revert the API image (the old code sends directly again) and scale the notifier to zero. Rows already queued stay pending and are sent if the notifier returns, or are dropped with the downgrade.
