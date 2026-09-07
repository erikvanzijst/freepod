resource "keycloak_realm" "freepod" {
  realm        = var.realm_name
  enabled      = true
  display_name = "Freepod"

  # Freepod is a public service: anyone may sign up. registrationAllowed is a
  # realm-level setting with no per-client equivalent, so "open on prod, closed
  # on dev" is not expressible here — dev is closed by *authorization* instead,
  # via the freepod-dev group and oauth2-proxy allowed_groups.
  registration_allowed = true

  # The email claim is the sole join key between Keycloak and Freepod's own
  # user records (api/app/deps.py resolves callers by lower(email); no Keycloak
  # subject identifier is persisted anywhere). An account whose email could be
  # set to somebody else's would take over that Freepod account, so verification
  # is a security control and must not be relaxed.
  verify_email             = true
  duplicate_emails_allowed = false
  login_with_email_allowed = true

  # Registration collects no username; the account's username is its email
  # address. Nothing in Freepod reads a Keycloak username.
  #
  # The two settings below are load-bearing for this, not independent choices.
  # Keycloak rejects duplicate_emails_allowed alongside it — an email that is
  # the username cannot also be shared — and it forbids edit_username_allowed
  # alongside it, since a self-editable username would diverge from the email
  # the moment it was edited. edit_username_allowed already defaults to false;
  # it is written out so that flipping it is a visible decision here.
  registration_email_as_username = true
  edit_username_allowed          = false

  # Self-service password reset. This is how every migrated account seeded
  # without a credential obtains one, so it and SMTP below are on the critical
  # path of the cutover.
  reset_password_allowed = true

  # Baked into the Keycloak image (see ../keycloak/Dockerfile), not mounted, so
  # it is available to every realm on the instance.
  login_theme   = "freepod"
  email_theme   = "freepod"
  account_theme = "freepod"

  # Delivered via the in-cluster mailer relay, which holds the real upstream
  # credentials — so this hop needs no authentication and no transport
  # security, and no external SMTP secret lives in the realm configuration.
  # Same arrangement as Alertmanager (../prometheus/prometheus.tf).
  #
  # There is deliberately no `auth` block: the relay accepts unauthenticated
  # mail from inside the cluster. Adding credentials here would fail the
  # connection, not harden it.
  smtp_server {
    host              = var.smtp_host
    port              = var.smtp_port
    from              = var.smtp_from
    from_display_name = var.smtp_from_display_name
    reply_to          = var.smtp_reply_to
    ssl               = false
    starttls          = false
  }

  # Deleting a realm cascades to every user, credential and session inside it,
  # and Terraform does not manage those — they live in Keycloak's own Postgres
  # and are not reconstructible from this configuration.
  #
  # Two guards, because they fail in different places. prevent_destroy below is
  # a plan-time error, but it only applies while the resource is still in the
  # configuration: delete this block and apply, and the realm goes with it.
  # terraform_deletion_protection is enforced by the provider at the delete
  # call itself, so it survives the resource being removed from code. Removing
  # the realm deliberately means flipping this to false and applying first.
  terraform_deletion_protection = true

  lifecycle {
    prevent_destroy = true
  }
}
