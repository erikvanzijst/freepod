## 1. Realm configuration

- [x] 1.1 Set `registration_email_as_username = true` on the realm resource in `tf/deps/keycloak-config/realm.tf` and verify `terraform plan` shows that single attribute change and nothing else.
- [x] 1.2 Record in comments beside it why `duplicate_emails_allowed` and `edit_username_allowed` must both stay false — Keycloak rejects the first combination and forbids the second — so neither is later flipped as an apparent independent choice.
- [x] 1.3 Apply, then verify through the admin API that the realm reports `registrationEmailAsUsername` true, `duplicateEmailsAllowed` false and `editUsernameAllowed` false.

## 2. Normalization pass

- [x] 2.1 Write the pass in the shape of `scripts/seed-keycloak-users.py` (admin API, token minted per call), with a report-only mode, and verify it lists exactly the non-deleted accounts whose username differs from their email address.
- [x] 2.2 Have the pass record each account's id, previous username and email before writing, and verify the record is produced in report-only mode too, so the list exists before anything changes.
- [x] 2.3 Make the pass idempotent and verify that re-running it over already-converted accounts writes nothing — Keycloak may have converted an account on its own between the apply and the run.
- [x] 2.4 Convert one member of the `freepod-observability` group and verify they sign in to Freepod with their email and existing password, with no reset required.
- [ ] 2.5 Verify that same user reaches their existing Grafana account under a changed login name, and that no second Grafana user was created for them, before converting anyone else.
      **Not verifiable, for a reason unrelated to this change.** Grafana's OAuth
      link for that account (`user_auth.auth_id`) still holds the pre-migration
      `master`-realm subject, which no longer exists in Keycloak, so the login
      fails at user sync before any rename could happen — identically on
      2026-08-31, before this change. D4's premise holds; the link is stale.
      Tracked with `keycloak-subject-join-key`. No other account is in
      `freepod-observability`, so nothing else in this change depended on it.
- [x] 2.6 Convert the remaining accounts and verify no non-deleted account is left with a username that differs from its email address.

## 3. Verification

- [x] 3.1 Register a new test account and verify the registration form presents no username field and the created account's username is the address given.
- [x] 3.2 Verify the test account completes email verification and reaches the Freepod dashboard, confirming nothing in the API depended on the field that was removed.
- [x] 3.3 Notify the affected accounts that their username is now their email address, and verify the list sent matches the accounts the pass converted.
