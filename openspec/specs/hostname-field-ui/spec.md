# hostname-field-ui Specification

## Purpose
The deploy dialog's hostname control: an application name beneath the account's
own domain name, or a whole FQDN the user brings themselves. It validates
against the platform as the user types and names the cause of every refusal.

## Requirements
### Requirement: HostnameField performs debounced real-time validation
The component MUST call `GET /api/hostnames/{fqdn}` with approximately 400ms debounce after the last keystroke to validate the current hostname. The API MUST NOT be called when the input is empty.

#### Scenario: Validation triggered after typing pauses
- **WHEN** the user types `myapp.freepod.eu` and stops typing for ~400ms
- **THEN** the component calls `GET /api/hostnames/myapp.freepod.eu`

#### Scenario: Rapid typing does not flood API
- **WHEN** the user types multiple characters in quick succession (within 400ms)
- **THEN** only one API call is made for the final value

#### Scenario: Empty input does not trigger validation
- **WHEN** the hostname input is empty
- **THEN** no API call is made and no status icon is shown

### Requirement: HostnameField shows CNAME setup instructions in custom domain mode
When the component is in custom FQDN mode, it MUST display static helper text below the input instructing the user to create a CNAME record pointing their domain to the platform's CNAME target domain (fetched from `GET /api/cname-target`, falling back to `freepod.eu` when empty/unavailable). This text MUST be visible as soon as custom mode is active, regardless of validation state.

#### Scenario: Helper text visible immediately on switching to custom mode
- **WHEN** the user switches to custom domain mode and `GET /api/cname-target` returned `"dev.freepod.eu"`
- **THEN** helper text "Point your domain at Freepod: create a CNAME record → dev.freepod.eu" is visible below the input field

#### Scenario: Helper text visible while typing in custom mode
- **WHEN** the user is typing a custom FQDN
- **THEN** the CNAME instruction helper text remains visible

#### Scenario: Helper text not shown in wildcard mode
- **WHEN** the component is in wildcard (free domain) mode
- **THEN** no CNAME instruction helper text is displayed

### Requirement: UserValuesForm detects hostname fields and renders HostnameField
The `UserValuesForm` component MUST detect schema fields where `field.title` (case-insensitive) equals `"hostname"` and render a `<HostnameField>` component instead of a standard `<TextField>` for those fields.

#### Scenario: Schema field with title "hostname" renders HostnameField
- **WHEN** the template schema contains a field with `"title": "hostname"`
- **THEN** the form renders a `HostnameField` component for that field

#### Scenario: Schema field with title "Hostname" (mixed case) renders HostnameField
- **WHEN** the template schema contains a field with `"title": "Hostname"`
- **THEN** the form renders a `HostnameField` component for that field

#### Scenario: Schema field with other title renders standard TextField
- **WHEN** the template schema contains a field with `"title": "Server Name"`
- **THEN** the form renders a standard `TextField` for that field

### Requirement: HostnameField integrates with UserValuesForm state
The `HostnameField` component MUST integrate with the existing `UserValuesForm` flattened state. The `onChange` callback MUST feed the hostname value back into the form's state using the field's dot-notation path.

#### Scenario: Hostname value flows into form submission
- **WHEN** the user enters `myapp.freepod.eu` in the HostnameField for a field at path `ingress.host`
- **THEN** the form's unflattened output includes `{"ingress": {"host": "myapp.freepod.eu"}}`

### Requirement: UserValuesForm seeds form fields from JSON Schema defaults only
The `UserValuesForm` component MUST NOT accept a `defaultValuesJson` prop. The `flattenDefaults()` function MUST be removed. Form field initial values MUST come from the JSON Schema `default` annotation on each field (`field.default`) only.

#### Scenario: Schema field with default annotation pre-populates
- **WHEN** a schema field has `"default": "some-value"` in the JSON Schema
- **THEN** the form field is pre-populated with `"some-value"`

#### Scenario: Schema field without default annotation starts empty
- **WHEN** a schema field has no `default` annotation
- **THEN** the form field starts empty (or `false` for booleans)

### Requirement: HostnameField skips validation for unchanged hostname
The component MUST NOT call `GET /api/hostnames/{fqdn}` while the composed FQDN equals the `initialHostname` it was given, reporting it as valid without asking. The check does not exclude the deployment that already holds the name, so re-checking an unchanged hostname would report it in use against itself.

#### Scenario: Initial hostname skips API validation
- **WHEN** `HostnameField` receives an `initialHostname` prop and the current FQDN equals `initialHostname`
- **THEN** the component sets validation status to `valid` without calling `GET /api/hostnames/{fqdn}`

#### Scenario: Changed hostname triggers normal validation
- **WHEN** `HostnameField` receives an `initialHostname` prop and the current FQDN differs from `initialHostname`
- **THEN** the component calls `GET /api/hostnames/{fqdn}` with the normal debounce behavior

#### Scenario: Reverted hostname skips validation again
- **WHEN** the user changes the hostname away from `initialHostname` and then changes it back
- **THEN** the component sets validation status to `valid` without calling the API

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
