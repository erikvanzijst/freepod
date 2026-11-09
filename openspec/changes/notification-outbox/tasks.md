# Tasks

## 1. Outbox schema

- [ ] 1.1 Add `NotificationKindORM`, `NotificationORM` and the `notification_state` enum to `api/app/models/` per design D2, and verify `uv run python -c "import app.models"` succeeds
- [ ] 1.2 Write the Alembic migration: the enum, both tables with their CHECK constraints (one recipient; action label and URL together, URL `https://`), the unique `(kind, dedupe_key)`, the partial pending index, the seeded kinds `access.invitation` and `database.quota`, and the D5 trigger. Verify `alembic upgrade head`, then `downgrade -1`, then `upgrade head` again against the test database
- [ ] 1.3 Add `tf/app/caelus/notifier-bootstrap.sql` creating and converging `caelus_notifier` with only the D10 grants (REVOKE ALL first, as in `app-auth-bootstrap.sql`), and verify it applies twice in a row with `psql -v notifier_password=… -f` against the test database
- [ ] 1.4 Add schema tests in `api/tests/` covering the notification-outbox scenarios: one recipient, unknown kind, action without URL, origin from `session_user` and refused when supplied by a non-owner role, dedupe per kind with NULLs distinct, a wake-up on commit and on requeue but not on rollback (`LISTEN` on a second connection), and producer and notifier roles refused outside their grants. Verify they pass with `-n 8`

## 2. API producers

- [ ] 2.1 Add `app/services/notifications.py` with `queue(...)` (adds to the caller's session, `ON CONFLICT DO NOTHING` when a dedupe key is given) and `md(text)`, and unit tests showing `md` turns every ASCII punctuation character literal (for example `[x](javascript:…)`, `*a*`, `<b>`, `ana_b@example.com`) and that `queue` doesn't commit
- [ ] 2.2 Queue the invitation in `app_access.add_entry`'s transaction (kind `access.invitation`, address recipient, owner email and hostname through `md`), remove `send_invitation`, `invitation_text` and the background task in `app/api/access.py`, and update the access-list tests to assert exactly one queued row per addition and none on a refused addition
- [ ] 2.3 Queue the quota notices in `relational_storage._notify_threshold` (kind `database.quota`, user recipient, dashboard action) per design D9, and update the quota tests to assert the queued row and that `warned_threshold` is set in the same transaction
- [ ] 2.4 Delete `app/services/mailer.py`, `app/services/mail_layout.py`, their tests and the `smtp_*` settings, and verify `grep -rn "mailer\.\|mail_layout\|smtp_" api/app` finds nothing and the full `api/` suite passes with `-n 8`

## 3. Notifier daemon

- [ ] 3.1 Create the `daemons/notifier/` module (`go.mod` with pgx v5 and goldmark, `main.go` reading `DATABASE_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`), add it to `go.work` and `.dockerignore`, and verify `GOWORK=off go vet ./...` passes
- [ ] 3.2 Implement rendering per design D7 (goldmark without extensions, the scheme filter, the inline-style pass, the plain-text pass, and the layout ported from `mail_layout.py` as an embedded `html/template`), with `render_test.go` covering every notification-sender layout and Markdown scenario plus ordinary bodies, asserting on both parts
- [ ] 3.3 Implement the MIME message and SMTP delivery per design D8, with tests against an in-process fake SMTP server checking the headers, the RFC 2047 subject, both parts and `Message-ID` from the row ID
- [ ] 3.4 Implement the store and sweep per design D6 (claim one row with `SKIP LOCKED`, resolve the user's address, three attempts two seconds apart, terminal update, `suppressed` without a relay, `failed` without an address), with store tests run as `caelus_notifier` against the test database and the bootstrap SQL, as app-auth's are. Cover the sent, retried, failed, suppressed and no-address cases, two concurrent sweeps delivering a row once, and a row left pending when the sweep is interrupted before its commit
- [ ] 3.5 Implement the listen loop per design D5 (a dedicated connection, `LISTEN` before the first sweep, a 60-second wait, reconnecting after 5 seconds), with tests showing a row is sent within five seconds of its commit, a row queued while the loop is disconnected is sent after it reconnects, and the timeout sweep finds a row whose wake-up was lost
- [ ] 3.6 Write `daemons/notifier/README.md` (purpose, configuration, requeueing failed rows, spec links), add the notifier to `daemons/README.md`, bump `daemons/VERSION`, and verify `docker build daemons/` produces `/notifier`

## 4. Infrastructure

- [ ] 4.1 Add the notifier role's secret and the bootstrap ConfigMap, plus the init container in `tf/app/caelus/worker.tf` after `migrate` (like app-auth's), and verify `terraform validate` and a `terraform plan` on dev show only the expected additions
- [ ] 4.2 Add the `caelus-notifier` deployment (one replica, `Recreate`, the daemons image with `/notifier`, a small memory request, `DATABASE_URL` built from the role secret, the SMTP host and sender address) and the `notifier_image` variable through `tf/app`. Remove `CAELUS_SMTP_*` from the API configmap, and verify `terraform plan` on dev
- [ ] 4.3 Add `caelus-notifier` to `scripts/rollout.sh`, and verify `bash -n scripts/rollout.sh`
- [ ] 4.4 Update `AGENTS.md`'s architecture notes with a short entry on the outbox and the notifier linking both specs, and verify the links resolve

## 5. Verification on dev

- [ ] 5.1 Roll out to dev and add an access-list entry: one `access.invitation` row ends `sent` and the email arrives in the Freepod layout with a readable plain-text part
- [ ] 5.2 Scale the notifier to zero, add an entry, scale it back, and verify the invitation is sent within a minute
- [ ] 5.3 Point the notifier at an unreachable relay, add an entry, and verify the row ends `failed` after three attempts with the error recorded. Restore the relay, requeue the row with an `UPDATE` setting it back to `pending`, and verify it is sent

## Workflow follow-up

- Roll out to prod after review and merge, then repeat 5.1 there.
- Archive the change and sync its specs.
- Then propose `access-first-sign-in-notice`, which grants `caelus_app_auth` the producer columns and queues the owner's notice when an entry is bound.
