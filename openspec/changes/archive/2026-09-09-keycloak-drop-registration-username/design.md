## Context

See proposal.md — Why. What matters for the approach:

- The realm is declared in `tf/deps/keycloak-config/realm.tf`. The provider argument is
  `registration_email_as_username`; the neighboring settings already hold the values this
  depends on (`duplicate_emails_allowed = false`, `login_with_email_allowed = true`, and
  `edit_username_allowed` unset, so false).
- The provider is capped below 5.8.0 for Keycloak 24 compatibility (`tf/deps/providers.tf`).
  Nothing here needs a newer one.
- The realm holds a small number of accounts, seeded during the `master` → `freepod`
  migration by `scripts/seed-keycloak-users.py`, which carried their original usernames over.
  Those are the accounts whose usernames diverge from their email addresses.
- Grafana authenticates against this realm with `login_attribute_path = "preferred_username"`
  (`tf/deps/prometheus/grafana.tf`), so it is the one downstream consumer of the value being
  changed.

## Goals / Non-Goals

**Goals:**

- One less field on the registration form, and one less way for a signup to fail.
- A realm left in a consistent state, rather than one that converts itself account by account
  at unpredictable moments.

**Non-Goals:**

- The first and last name fields, which registration also collects and Freepod also never
  reads. Removing those is a user-profile change with its own considerations (email
  salutations, the account console), and it is not this.
- Anything in the Freepod API, CLI, database or UI. None of them has a username to remove.
- Deleting usernames as a concept. Keycloak always has one; this decides what it holds.

## Decisions

### D1: Derive from email rather than making the field optional

Keycloak's user profile could mark username optional instead. Rejected: the account would
then have a username that is neither absent nor meaningful, and Keycloak generates one, so
the field's cost is paid and its confusion is kept. Deriving from email gives the account a
username that is true, stable in the only sense that matters here, and needs no explanation.

### D2: Normalize existing usernames now rather than letting Keycloak do it later

This is the substance of the change; the Terraform edit is one line.

With `registrationEmailAsUsername` enabled, Keycloak overwrites a custom username with the
email address on the next update to that account. It is a known and long-reported behavior,
and it does not fire at flip time — it fires whenever that account is next touched, by the
user editing their profile or by an administrator changing anything at all.

Left alone, that produces the worst version of this change: a person's login name changes
silently, weeks later, with nothing connecting it to a configuration change, and no record of
which accounts have converted and which have not. Doing it deliberately in one pass makes it
a single event with a known scope, a known moment, and an announcement if one is wanted.

The pass goes through the admin API, following `scripts/seed-keycloak-users.py`, both because
`keycloak-terraform-config` requires that Terraform never manage end-user accounts and
because Keycloak's Infinispan user cache makes direct SQL unreliable — the same reason that
script gives.

### D3: Nobody is locked out, and that is worth checking rather than assuming

The realm sets `login_with_email_allowed = true`, so every affected user can already sign in
with the address they are about to be renamed to, using their existing password. Credentials
are untouched by a username change, so no reset is involved.

The residual harm is a user who habitually types a username at the login prompt and finds it
no longer works. With the population this size that is an email, not a mechanism.

### D4: Grafana is the one downstream consumer, and it renames rather than duplicates

Grafana takes its login name from `preferred_username`, so affected users' Grafana login
names change with their Keycloak usernames. Grafana matches a returning OAuth user by the
token subject, which this change does not touch, so the expected outcome is a rename of an
existing account rather than a second one.

Expected, not verified — it is runtime behavior of a live Grafana against a live realm, and
the honest place to establish it is the normalization pass itself: convert one observability
group member first, have them sign in, confirm they land on their existing account, and only
then convert the rest. That is the same one-account-first discipline the realm migration used
for password hashes.

### D5: Independent of the subject join key change

`keycloak-subject-join-key` makes the Keycloak subject the join key between Keycloak
identities and Freepod records. Neither change needs the other: Freepod reads no username
today, so this one is safe on its own, and the subject change is about email, not username.

They do point the same way. Once the username is derived from the email address, it moves
whenever the email moves — which is the clearest possible demonstration that a username was
never a candidate for a stable identifier.

## Risks / Trade-offs

- **An account is touched between the Terraform apply and the normalization pass**, and
  Keycloak converts it first. → Harmless: the outcome is identical to what the pass would
  have produced. Run them close together so the window is small, and make the pass
  idempotent so an already-converted account is a no-op.
- **A Grafana user ends up with a second account** because Grafana matched on login name
  rather than subject. → Convert one observability group member first and confirm before
  converting the rest (D4). If it does duplicate, the fix is deleting the new Grafana user,
  not reverting the realm.
- **A user who signs in by username is surprised.** → They can sign in by email with the same
  password; announce it to the affected accounts, which are few and known.
- **Reverting the realm setting does not restore usernames.** Once normalized, the original
  values exist only in whatever the pass logged. → Have the pass record the previous username
  alongside the account id before writing, so a revert is possible even though it is not
  expected to be wanted.

## Migration Plan

1. Apply the Terraform change. From this point new registrations collect no username, and
   existing accounts are unaffected until touched.
2. Run the normalization pass in report-only mode first, producing the list of accounts whose
   username differs from their email, with the previous values recorded.
3. Convert one member of the `freepod-observability` group. Have them sign in to Freepod and
   to Grafana, and confirm they reach their existing Grafana account rather than a new one.
4. Convert the remainder. Verify no non-deleted account is left with a username that differs
   from its email address.
5. Register a new test account and confirm the registration form presents no username field
   and the resulting account's username is the address given.

**Rollback:** the Terraform argument can be reverted at any time, which restores the field for
future registrations. It does not restore already-normalized usernames — hence the recorded
previous values in step 2 — but nothing in Freepod reads them, so there is nothing to restore
them for beyond a user's habit at the login prompt.
