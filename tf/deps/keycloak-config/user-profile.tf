# The realm's user profile: Keycloak's 26 default, except that users don't see
# their username. It is always their email address (registration_email_as_username),
# so the account console would show the same value twice.
#
# Authoritative: this replaces the realm's whole profile, so every attribute
# is listed, not just username.
resource "keycloak_realm_user_profile" "freepod" {
  realm_id = keycloak_realm.freepod.id

  attribute {
    name         = "username"
    display_name = "$${username}"

    permissions {
      view = ["admin"]
      edit = ["admin"]
    }

    validator {
      name   = "length"
      config = { min = "3", max = "255" }
    }
    validator { name = "username-prohibited-characters" }
    validator { name = "up-username-not-idn-homograph" }
  }

  attribute {
    name               = "email"
    display_name       = "$${email}"
    required_for_roles = ["user"]

    permissions {
      view = ["admin", "user"]
      edit = ["admin", "user"]
    }

    validator { name = "email" }
    validator {
      name   = "length"
      config = { max = "255" }
    }
  }

  attribute {
    name               = "firstName"
    display_name       = "$${firstName}"
    required_for_roles = ["user"]

    permissions {
      view = ["admin", "user"]
      edit = ["admin", "user"]
    }

    validator {
      name   = "length"
      config = { max = "255" }
    }
    validator { name = "person-name-prohibited-characters" }
  }

  attribute {
    name               = "lastName"
    display_name       = "$${lastName}"
    required_for_roles = ["user"]

    permissions {
      view = ["admin", "user"]
      edit = ["admin", "user"]
    }

    validator {
      name   = "length"
      config = { max = "255" }
    }
    validator { name = "person-name-prohibited-characters" }
  }

  group {
    name                = "user-metadata"
    display_header      = "User metadata"
    display_description = "Attributes, which refer to user metadata"
  }
}
