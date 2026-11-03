## ADDED Requirements

### Requirement: The deploy form shows a conditional field only while its branch applies
The deploy form SHALL read the schema's root `if`/`then`/`else`, the same inside root
`allOf` entries, and root `dependentRequired`. A root property a branch mentions, in
its `required` or `properties`, SHALL be shown only while such a branch applies, unless
the root `required` names it. A property no branch mentions SHALL always be shown. A
`dependentRequired` entry SHALL apply while its trigger is present.

#### Scenario: Sign-in on hides the admin password
- **WHEN** a schema declares the chart value `auth.enabled` (default `true`) and the
  sensitive var `NEXTCLOUD_ADMIN_PASSWORD`, with a root `if` on `auth.enabled` being
  `false` whose `then` requires `NEXTCLOUD_ADMIN_PASSWORD`
- **AND** the form renders with the checkbox checked
- **THEN** the password field is not shown

#### Scenario: Sign-in off shows it
- **WHEN** the user unchecks the checkbox
- **THEN** the password field appears, marked required
- **AND** re-checking the checkbox hides it again

#### Scenario: A property the root requires
- **WHEN** a branch mentions a property the root `required` names
- **THEN** the field is shown whether or not the branch applies

### Requirement: Conditions are evaluated against the document a submission would form
The form SHALL evaluate each `if` with the JSON Schema validator it uses for
client-side validation, against one document holding the chart values and the vars it
would submit, vars typed as the platform coerces them. A field SHALL be marked required
when the root `required` or an applying branch's `required` names it.

#### Scenario: A boolean var read by a condition
- **WHEN** an `if` requires the boolean var `SIGNUPS` to be `true`
- **AND** the user checks the `SIGNUPS` field
- **THEN** the condition holds, as it would for the platform's coerced value

### Requirement: A hidden field's value is not submitted
A field the conditionals hide SHALL contribute nothing to the submission: no chart
value and no var entry. The form SHALL keep what the user typed, so showing the field
again restores it. A stored var whose field is hidden SHALL be left as stored, never
deleted.

#### Scenario: A value typed before the field was hidden
- **WHEN** the user types a password, then checks the checkbox that hides its field
- **THEN** the submission carries no entry for the password

#### Scenario: A stored var in a hidden field
- **WHEN** the Edit dialog opens a deployment whose stored vars include one whose field
  is hidden
- **AND** the user submits the update
- **THEN** the update carries no entry for that var, and the stored var is unchanged
