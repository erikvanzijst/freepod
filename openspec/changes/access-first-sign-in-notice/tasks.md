# Tasks

## 1. Database

- [ ] 1.1 Write an Alembic migration seeding the `access.first_sign_in` kind (unsubscribable), with a `downgrade` that deletes it, and verify `upgrade head`, then `downgrade -1`, then `upgrade head` again against the test database
- [ ] 1.2 Grant `caelus_app_auth` `INSERT` on the producer columns except `recipient_email` in `tf/app/caelus/app-auth-bootstrap.sql` (design D3), and extend app-auth's role tests to show that it can queue a notification for a user, and is refused when it queues one for an address, reads the outbox or changes a state

## 2. app-auth

- [ ] 2.1 Add `notice.go` with `mdEscape` and the fixed notice (design D5), with tests showing the escaping of punctuation in emails and hostnames and the exact subject, body, action and reason
- [ ] 2.2 Make `pgStore.bindEntry` a transaction that queues the notice under a savepoint (design D1), with store tests against the test database covering:
  - one row queued from `caelus_app_auth` to the owner's user ID;
  - none on a lost race or a 23505;
  - none on a second binding attempt;
  - a new row after the entry is removed and added again;
  - a binding that still succeeds when the kind is missing, with no row queued.
- [ ] 2.3 Extend `memstore_test.go` and the broker and provider tests so that a first header sign-in and a first OIDC sign-in each queue one notice, and a repeat sign-in, the owner's sign-in and a refused sign-in queue none
- [ ] 2.4 Mention the notice in `daemons/app-auth/README.md`, bump `daemons/VERSION`, and verify `GOWORK=off go vet ./... && GOWORK=off go test ./...` in `daemons/app-auth`

## 3. Verification on dev

- [ ] 3.1 Roll out the API, then app-auth. Invite a test address to a `listed` deployment and sign in with it: one `access.first_sign_in` row ends `sent` and the owner receives the email. A second sign-in queues nothing
- [ ] 3.2 Do the same against a Nextcloud (SSO) deployment and verify that, when the owner's email arrives, the invitee exists in Nextcloud and can be shared with

## Workflow follow-up

- Roll out to prod after review and merge (API first, then app-auth).
- Archive the change and sync its specs.
