## REMOVED Requirements

### Requirement: HostnameField component supports dual-mode hostname input
**Reason**: The Freepod mode no longer offers a choice of domain. An account has exactly one
Freepod address — its own — so the prefix-plus-dropdown pairing is replaced by an
application label and a static suffix carrying the account's subdomain and the platform
domain. Replaced by "HostnameField offers the account's own address or a custom domain".
**Migration**: The domain `Select` is removed from `ui/src/components/HostnameField.tsx`.
Custom domain mode is unchanged, including dot handling.

### Requirement: HostnameField fetches wildcard domains from API
**Reason**: The field no longer populates a dropdown from `GET /api/domains`; it renders one
address, composed from the subdomain the account holds and the platform domain. Replaced by
"HostnameField learns the account's address from the platform".
**Migration**: The `GET /api/domains` query in the field is replaced by the account's held
subdomain. `GET /api/domains` itself remains, and remains public.

### Requirement: HostnameField displays validation status icon
**Reason**: One of the reason codes it renders — `nested_subdomain` — is retired with the
depth rule that produced it, and `claimed` joins the set. Replaced by "HostnameField shows
a status icon naming the reason".
**Migration**: Remove the `nested_subdomain` entry from `REASON_LABELS` and add `claimed`.

## ADDED Requirements

### Requirement: HostnameField offers the account's own address or a custom domain

`HostnameField` MUST offer two modes: a **Freepod address** mode and a **custom domain**
mode, with the user able to toggle between them. Freepod address mode MUST accept a single
application label and render the account's own address as a static, non-editable suffix —
`.<subdomain>.<domain>` — so the user composes `<app>.<subdomain>.<domain>` while typing
only `<app>`. Dots MUST be stripped from the application label. Custom domain mode MUST
accept a complete FQDN, dots included, unchanged.

Freepod address mode MUST NOT present a choice of domain. There is one Freepod address
available to a given account, so a selector would offer a decision the user does not have.

#### Scenario: Freepod mode renders the account's address as a fixed suffix
- **WHEN** a user holding the subdomain `alice` opens the deploy dialog on a platform whose domain is `freepod.eu`
- **THEN** the field shows an editable application label followed by a static `.alice.freepod.eu`, with no domain selector

#### Scenario: An application label is combined with the account's address
- **WHEN** the user types `photos` and holds the subdomain `alice`
- **THEN** the component emits `photos.alice.freepod.eu` via `onChange`

#### Scenario: Only the application label is editable
- **WHEN** the user interacts with the field in Freepod address mode
- **THEN** the account subdomain and the platform domain do not accept input

#### Scenario: Dots are stripped from the application label
- **WHEN** the user types or pastes `foo.bar` as the application label
- **THEN** the label becomes `foobar` and the component emits `foobar.alice.freepod.eu`

#### Scenario: Custom domain mode allows dots
- **WHEN** the user types `foo.bar.example.com` in custom domain mode
- **THEN** the component emits `foo.bar.example.com` without stripping any characters

#### Scenario: Switching modes clears previous input
- **WHEN** the user switches between Freepod address mode and custom domain mode
- **THEN** the input fields are reset and `onChange` is called with the new (possibly empty) value

### Requirement: HostnameField learns the account's address from the platform

The field MUST learn the account's own address from the platform at runtime — the held
subdomain and the platform domain — and MUST NOT compose it from a value hardcoded in the
client.

#### Scenario: The suffix comes from the platform
- **WHEN** the field renders in Freepod address mode
- **THEN** the subdomain and domain in its suffix are the values the API reported for this account and environment

#### Scenario: An account holding no subdomain does not reach the field
- **WHEN** a user holding no subdomain acts to deploy
- **THEN** the claim dialog opens instead, so the field is never rendered without an address to show

### Requirement: HostnameField shows a status icon naming the reason

The component MUST display a status indicator on the right of the input: a green check when
the hostname is usable, a red error icon with a tooltip when it is not, and a spinner while
a check is in flight. The tooltip MUST name the cause:

- `"invalid"` → "Invalid hostname format"
- `"reserved"` → "Hostname is reserved"
- `"in_use"` → "Already in use"
- `"claimed"` → the address belongs to another account
- `"not_resolving"` → "Create a CNAME record pointing to <cname-target>", where
  `<cname-target>` comes from `GET /api/cname-target`, falling back to `freepod.eu` when
  empty or unavailable

No message for `nested_subdomain` may remain: the reason is retired.

#### Scenario: Usable hostname shows green check
- **WHEN** the API returns `{"fqdn": "photos.alice.freepod.eu", "reason": null}`
- **THEN** a green CheckCircle icon is displayed

#### Scenario: Taken hostname shows red error with tooltip
- **WHEN** the API returns `{"fqdn": "photos.alice.freepod.eu", "reason": "in_use"}`
- **THEN** a red Error icon is displayed with tooltip text "Already in use"

#### Scenario: Another account's address shows its own reason
- **WHEN** the API returns `{"fqdn": "photos.bob.freepod.eu", "reason": "claimed"}`
- **THEN** a red Error icon is displayed with a tooltip saying the address belongs to another account

#### Scenario: Not-resolving hostname shows CNAME instruction in tooltip
- **WHEN** the API returns `{"fqdn": "myapp.example.com", "reason": "not_resolving"}` and `GET /api/cname-target` returned `"dev.freepod.eu"`
- **THEN** a red Error icon is displayed with tooltip text "Create a CNAME record pointing to dev.freepod.eu"

#### Scenario: A retired reason is gone
- **WHEN** the field's reason messages are examined
- **THEN** no message for `nested_subdomain` remains

#### Scenario: Loading state shows spinner
- **WHEN** an API call is in flight
- **THEN** a CircularProgress spinner is displayed in place of the status icon
