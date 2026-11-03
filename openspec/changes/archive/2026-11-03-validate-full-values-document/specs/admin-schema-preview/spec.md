## ADDED Requirements

### Requirement: The preview reflects the schema's conditionals
The live deploy dialog preview SHALL show, hide and require fields by the root
conditionals of the schema in the editor, as the deploy form does. It SHALL re-evaluate
them whenever the editor holds a new valid schema and whenever the admin changes a
field in the preview.

#### Scenario: A conditional added in the editor
- **WHEN** the admin adds a root `if`/`then` whose `then` requires a field, and the
  condition does not hold for the preview's values
- **THEN** after the debounce period the preview no longer shows that field

#### Scenario: A toggle in the preview
- **WHEN** the admin changes a preview field so that the condition holds
- **THEN** the field appears, marked required

#### Scenario: The conditional removed again
- **WHEN** the admin removes the `if`/`then` from the editor
- **THEN** the field is shown and no longer marked required
