## ADDED Requirements

### Requirement: Operator CLI parity
The `caelus` operator CLI MUST offer every vars operation the REST API offers — reading
the collection and a single var, merging, replacing, deleting one var, and supplying vars
when a deployment is created or updated — in the one wire shape, by calling the same
service layer. Validation, reserved keys, limits and error messages SHALL be the API's,
and a write SHALL be recorded as made by the operator who ran it.

#### Scenario: Deploying a product with a required runtime var
- **WHEN** an operator creates a deployment through the CLI and supplies the template's
  required sensitive var through the vars input
- **THEN** the deployment is created with the var stored as sensitive and included in
  its first release

#### Scenario: An invalid var through the CLI
- **WHEN** an operator writes a reserved key through the CLI
- **THEN** the CLI fails with the API's error for that key, and nothing is written

### Requirement: The operator CLI keeps secret values off the command line
The CLI SHALL let a var's value be supplied without placing it in a command-line
argument — from standard input, or at a prompt that does not echo — since arguments are
visible to other processes and kept in shell history. A CLI read SHALL omit the value of
a sensitive var exactly as an API read does.

#### Scenario: Supplying a secret without a command-line argument
- **WHEN** an operator sets a var through the CLI and provides its value on standard
  input or at a non-echoing prompt
- **THEN** the var is written and the value appears in no argument of the process

#### Scenario: Reading a sensitive var through the CLI
- **WHEN** an operator lists a deployment's vars through the CLI
- **THEN** a sensitive var is reported without its value
