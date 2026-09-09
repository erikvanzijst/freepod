## Why

The `freepod` realm's registration form asks for a username. Nothing consumes it. Freepod
resolves callers by email and stores no Keycloak identifier; the platform has no concept of
a username anywhere in its API, its CLI or its database.

So it is a required, uniqueness-checked field that a person must invent at the exact moment
they are trying to sign up, whose only effect is to give them a second way to fail
registration — and, because the form validates on submit, a failure that returns the page
with both password fields cleared. It also invites a reasonable misreading: a unique,
lowercase, hostname-shaped name asked for at signup looks like it might be the name a user's
apps will be served under, and it is not.

Keycloak can simply not ask, deriving the username from the email address.

## What Changes

- **Registration stops collecting a username.** `registration_email_as_username` is enabled
  on the realm, so a new account's username is its email address and the field disappears
  from the form.
- **Two related realm settings are asserted rather than changed.** `duplicate_emails_allowed`
  must remain false (the provider refuses the combination otherwise) and
  `edit_username_allowed` must remain false, since Keycloak does not allow a self-editable
  username alongside this setting.
- **Existing usernames are normalized once, deliberately.** With the setting enabled,
  Keycloak overwrites a custom username with the email address on the next update to that
  account — an unannounced, per-account event at an unpredictable future moment. A one-off
  admin-API pass brings every existing account to `username == email` at the time of the
  flip instead, so the realm ends consistent and nothing changes underneath a user later.
- **Grafana's login names follow.** Grafana derives its login from `preferred_username`
  (`tf/deps/prometheus/grafana.tf`), so the observability group's Grafana login names become
  their email addresses. Accounts are matched on the token subject, so this renames rather
  than duplicates — verified during the normalization pass, not assumed.

## Capabilities

### Modified Capabilities

- `keycloak-user-realm`: adds requirements that registration collects no username, that the
  settings this depends on are pinned, and that existing accounts are normalized once rather
  than drifting.

## Impact

- `tf/deps/keycloak-config/realm.tf`: one new argument on the realm resource, plus comments
  recording why the two neighboring settings are load-bearing.
- A one-off normalization script or admin-API pass over existing accounts, in the shape of
  the existing `scripts/seed-keycloak-users.py`. Not Terraform: `keycloak-terraform-config`
  requires that Terraform never manage end-user accounts.
- Grafana users in the `freepod-observability` group see their login name change.
- Not affected: the Freepod API, CLI, database and UI, none of which read a username; and
  every user's ability to sign in, since the realm already permits login by email.
