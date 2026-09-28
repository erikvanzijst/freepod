## Context

See proposal.md for the why. The facts that shape the approach:

- Every Freepod client authenticates against the one `freepod` realm: the oauth2-proxy
  clients, the CLI clients, the app-auth broker and Grafana. Identity providers are realm
  objects, so one provider reaches all of them.
- The API resolves callers by `lower(email)` (`api/app/deps.py`). A Google user is an
  ordinary realm user with a Keycloak subject and an email claim, so nothing downstream of
  Keycloak can tell how they signed in.
- The realm sets `registration_email_as_username`, `duplicate_emails_allowed = false` and
  `verify_email = true`. `duplicate_emails_allowed = false` is what makes Keycloak detect
  an existing account by email during a first Google sign-in.
- The login theme is CSS only on top of `keycloak.v2`, and that parent template already
  renders the configured identity providers as buttons.
- The behavior below was read from the Keycloak 24.0.5 source (`IdentityBrokerService`,
  `IdpCreateUserIfUniqueAuthenticator`, `IdpAutoLinkAuthenticator`,
  `IdpEmailVerificationAuthenticator`, `VerifyEmail`), which matches the `keycloak:24.0`
  base image.

## Goals / Non-Goals

**Goals:**

- One account per person, whichever sign-in method they use first.
- No change to anything downstream of Keycloak.

**Non-Goals:**

- A seamless, prompt-free link for existing password accounts (see D2).
- A custom Keycloak extension or any `kc.sh build` step in the image.
- Letting a user unlink Google or manage linked identities beyond what the stock account
  console already offers.

## Decisions

### D1: Trust Google's email assertion

`trust_email = true`. On first sign-in, Keycloak then marks the new account's email verified
without sending a verification email. Keycloak applies this only on the account-creation
path, and not when the user edited the email on the review-profile page, so an address the
user typed is still verified by email.

Alternative: `trust_email = false`, which sends every Google user one Keycloak verification
email. Rejected: Google is trusted as an email authority here, and the extra email adds
friction to exactly the sign-up this change is meant to shorten.

### D2: Keep the stock first-login flow, not automatic linking

The identity provider uses Keycloak's built-in `first broker login` flow unchanged:

1. **Review profile** runs only when required attributes are missing. The stock
   configuration is `missing`, and Google always supplies email and name.
2. **Create user if unique** creates the account unless a user with that email already
   exists.
3. Otherwise, **Confirm link existing account** asks the user to confirm, then **Verify
   existing account** requires an emailed link or that account's password.
4. The link path attaches the federated identity and writes no attributes to the existing
   user (with `IMPORT` sync, see D3).

Alternative: replace step 3 with `idp-auto-link` (**Automatically set existing user**).
It is prompt-free, but it links to *any* user with that email, including an unverified one.
That opens a pre-account takeover:

1. An attacker registers the victim's address with their own password. They can't verify
   it, so the account sits unverified.
2. The victim later signs in with Google and is linked to it. Linking does not set
   `emailVerified`; only the account-creation path does.
3. Keycloak's `VerifyEmail` trigger prompts the victim to verify, and they do.
4. The attacker's password now opens the victim's account.

Keycloak 24's conditional authenticators can't inspect the existing user at that point in
the flow, so closing this gap needs a custom authenticator: a Java extension, a multi-stage
image build and `kc.sh build`. The stock flow costs an existing user one confirmation page
and one email click or password, once. Revisit only if that measurably hurts sign-in.

### D3: `IMPORT` sync mode

`sync_mode = "IMPORT"`: attributes are copied at account creation and never overwritten on
later sign-ins. With `FORCE`, a changed Google address would rewrite the Keycloak email on
the next sign-in. Under the email join key, that silently moves the person to a new, empty
Freepod account.

Set explicitly rather than relying on a default, with a comment pointing at
`keycloak-subject-join-key`. That change makes `FORCE` safe, and switching belongs to it or
to a later change, not this one.

### D4: One realm-wide provider, gated by existing authorization

A single provider on the realm, with no client-specific visibility. Development and Grafana
access remain governed by `freepod-dev` / `freepod-observability` group membership, which a
Google account never receives on creation (no identity-provider mappers are declared).

Alternative: per-client providers or hiding Google from some clients. Rejected: nothing
needs it, and Keycloak can only hide a provider realm-wide, not per client.

### D5: Credentials flow through `tf/deps`

The Google client ID and secret become sensitive root variables in `tf/deps/variables.tf`
and are passed into `module.keycloak_config`, like the other secrets in that root module.
The Google OAuth client itself is created by hand in the Google Cloud console. It is a
one-time object, and bringing the Google provider into Terraform for it would add a second
cloud credential to a module that has none.

### D6: Theme stays CSS-only

`login.css` styles the parent template's social-provider section to match the Freepod
look, while keeping the Google mark and wording that Google's branding guidelines require.
No FreeMarker override, so the theme continues to track `keycloak.v2`.

## Risks / Trade-offs

- **Existing users see an unfamiliar "account already exists" page.** → The login theme's
  message bundle can reword it if needed. This is a one-time step per user.
- **Google brand verification lags.** Until it's approved, Google's consent screen shows the
  bare domain instead of Freepod's name and logo. → Submit it early; sign-in works
  meanwhile.
- **Removing the provider later strands Google-only accounts.** They have no password. →
  Such users recover through self-service password reset, which the realm already allows.
- **The `keycloak:24.0` tag floats across patch releases.** The flow behavior relied on
  above is long-standing. → The dev verification tasks exercise each path end to end
  rather than trusting the source reading alone.

## Migration Plan

1. Create the Google OAuth client and put its credentials in `tf/deps/secrets.auto.tfvars`.
2. Rebuild and push the Keycloak image with the button styling; restart Keycloak.
3. `terraform apply` in `tf/deps/`. The provider appears on the realm's login page
   immediately, for prod and dev together, because they share the realm.
4. Verify the scenarios right after the apply, on `dev.freepod.eu` with a test Google
   account. There is no dev-only stage: the realm is shared, so the button reaches prod at
   the same moment. If a check fails, roll back as below.

**Rollback:** set the provider to disabled, or remove it, and apply. Accounts and links
already created stay in the realm. Google-only users regain access through password reset.
