# Spec Delta

## ADDED Requirements

### Requirement: HostnameField takes the account's suffix from the platform

The field MUST take the account's `suffix` from `GET /api/me/handle` at runtime and use it
as opaque text. It MUST NOT build the suffix from the handle and a domain, and MUST NOT carry
any domain as a constant.

#### Scenario: The suffix comes from the platform
- **WHEN** the field renders in Freepod address mode
- **THEN** its suffix is exactly the `suffix` the API reported for this account and environment

#### Scenario: An account holding no handle does not reach the field
- **WHEN** a user holding no handle acts to deploy
- **THEN** the claim dialog opens instead, so the field is never rendered without a suffix to show

### Requirement: HostnameField offers a Freepod address or a custom domain

`HostnameField` MUST offer a **Freepod address** mode and a **custom domain** mode, which the
user can toggle between. Freepod address mode MUST accept an application label, with dots
stripped, show the account's `suffix` as static text after it, emit the label followed by the
suffix, and offer no choice of domain. Custom domain mode MUST accept and emit a complete FQDN
unchanged.

#### Scenario: Freepod mode renders the account's suffix
- **WHEN** a user holding the handle `alice` opens the deploy dialog on a platform whose tenant domain is `freepod.app`
- **THEN** the field shows an editable application label followed by a static `-alice.freepod.app`, with no domain selector

#### Scenario: An application label is combined with the suffix
- **WHEN** the user types `photos` and the account's suffix is `-alice.freepod.app`
- **THEN** the component emits `photos-alice.freepod.app` via `onChange`

#### Scenario: Dashes are allowed in the application label
- **WHEN** the user types `my-photos`
- **THEN** the component emits `my-photos-alice.freepod.app`

#### Scenario: Only the application label is editable
- **WHEN** the user interacts with the field in Freepod address mode
- **THEN** the suffix does not accept input

#### Scenario: Dots are stripped from the application label
- **WHEN** the user types or pastes `foo.bar` as the application label
- **THEN** the label becomes `foobar` and the component emits `foobar-alice.freepod.app`

#### Scenario: Custom domain mode allows dots
- **WHEN** the user types `foo.bar.example.com` in custom domain mode
- **THEN** the component emits `foo.bar.example.com` without stripping any characters

#### Scenario: Switching modes clears previous input
- **WHEN** the user switches between Freepod address mode and custom domain mode
- **THEN** the input fields are reset and `onChange` is called with the new (possibly empty) value

#### Scenario: An existing tenant hostname opens in Freepod address mode
- **WHEN** the field is given an initial hostname ending in the account's suffix
- **THEN** it opens in Freepod address mode with the text before the suffix as the label

## MODIFIED Requirements

### Requirement: HostnameField performs debounced real-time validation
The component MUST call `GET /api/hostnames/{fqdn}` with approximately 400ms debounce after the last keystroke to validate the current hostname. The API MUST NOT be called when the input is empty.

#### Scenario: Validation triggered after typing pauses
- **WHEN** the user types `myapp.example.com` in custom domain mode and stops typing for ~400ms
- **THEN** the component calls `GET /api/hostnames/myapp.example.com`

#### Scenario: Rapid typing does not flood API
- **WHEN** the user types multiple characters in quick succession (within 400ms)
- **THEN** only one API call is made for the final value

#### Scenario: Empty input does not trigger validation
- **WHEN** the hostname input is empty
- **THEN** no API call is made and no status icon is shown

### Requirement: HostnameField integrates with UserValuesForm state
The `HostnameField` component MUST integrate with the existing `UserValuesForm` flattened state. The `onChange` callback MUST feed the hostname value back into the form's state using the field's dot-notation path.

#### Scenario: Hostname value flows into form submission
- **WHEN** the user's hostname is `photos-alice.freepod.app` in the HostnameField for a field at path `ingress.host`
- **THEN** the form's unflattened output includes `{"ingress": {"host": "photos-alice.freepod.app"}}`

### Requirement: HostnameField shows a status icon naming the reason

The component MUST display a status indicator on the right of the input: a green check when
the hostname is usable, a red error icon with a tooltip when it is not, and a spinner while
a check is in flight. The tooltip MUST name the cause:

- `"invalid"` → "Invalid hostname format"
- `"reserved"` → "Hostname is reserved"
- `"in_use"` → "Already in use"
- `"claimed"` → the address belongs to another account
- `"not_resolving"` → "Create a CNAME record pointing to <cname-target>, or for a root
  domain, A/AAAA records with the same addresses as <cname-target>", where
  `<cname-target>` comes from `GET /api/cname-target`, falling back to `freepod.app` when
  empty or unavailable

No message for `nested_subdomain` may remain: the reason is retired.

#### Scenario: Usable hostname shows green check
- **WHEN** the API returns `{"fqdn": "photos-alice.freepod.app", "usable": true, "reason": null}`
- **THEN** a green CheckCircle icon is displayed

#### Scenario: Taken hostname shows red error with tooltip
- **WHEN** the API returns `{"fqdn": "photos-alice.freepod.app", "usable": false, "reason": "in_use"}`
- **THEN** a red Error icon is displayed with tooltip text "Already in use"

#### Scenario: Another account's address shows its own reason
- **WHEN** the API returns `{"fqdn": "photos-bob.freepod.app", "usable": false, "reason": "claimed"}`
- **THEN** a red Error icon is displayed with a tooltip saying the address belongs to another account

#### Scenario: Not-resolving hostname shows DNS instruction in tooltip
- **WHEN** the API returns `{"fqdn": "myapp.example.com", "usable": false, "reason": "not_resolving"}` and `GET /api/cname-target` returned `"dev.freepod.app"`
- **THEN** a red Error icon is displayed with tooltip text "Create a CNAME record pointing to dev.freepod.app, or for a root domain, A/AAAA records with the same addresses as dev.freepod.app"

#### Scenario: A retired reason is gone
- **WHEN** the field's reason messages are examined
- **THEN** no message for `nested_subdomain` remains

#### Scenario: Loading state shows spinner
- **WHEN** an API call is in flight
- **THEN** a CircularProgress spinner is displayed in place of the status icon

## REMOVED Requirements

### Requirement: HostnameField offers the account's own address or a custom domain
**Reason**: The Freepod address is now the application label followed by the account's suffix.
**Migration**: See *HostnameField offers a Freepod address or a custom domain*.

### Requirement: HostnameField learns the account's address from the platform
**Reason**: The account is addressed by a handle suffix rather than a subdomain.
**Migration**: See *HostnameField takes the account's suffix from the platform*.
