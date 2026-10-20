# Spec Delta

## ADDED Requirements

### Requirement: A hostname is sent as entered and re-checked only when it changes

The client SHALL send the project file's hostname as entered: a bare label for the
platform to complete, or a dotted FQDN left alone. It SHALL check the hostname only when it
differs from the recorded deployment's, since the check would report an unchanged name as in
use by its own deployment. For that comparison it SHALL append the account's reported
`suffix` to a bare label as opaque text, and SHALL NOT otherwise build a hostname.

#### Scenario: An unchanged hostname is not re-checked

- **WHEN** a deploy runs, the project file's hostname is `photos`, the account's suffix is
  `-alice.freepod.app`, and the deployment's hostname is `photos-alice.freepod.app`
- **THEN** the client performs no hostname check

#### Scenario: A changed hostname is checked before packing

- **WHEN** the project file's hostname differs from the deployment's
- **THEN** the client checks it before packing
- **AND** stops with the reported reason when it is unusable

#### Scenario: A bare label is submitted as a label

- **WHEN** the project file's hostname is `photos`
- **THEN** the client checks and submits `photos`, and reports the hostname the platform
  completed it to

#### Scenario: A full FQDN is left alone

- **WHEN** the project file's hostname is `photos.example.com`
- **THEN** the client submits it unchanged and the custom-domain path applies

### Requirement: An old-format hostname in the project file is rewritten to its label

When the project file's hostname has the form `<label>.<x>.freepod.eu` or
`<label>.<x>.dev.freepod.eu`, the client SHALL replace it with `<label>`, save the project
file, and print one line saying so, before any hostname check or submission. This pattern is
fixed in the client: it only corrects the client's own earlier output.

#### Scenario: A production hostname is rewritten

- **WHEN** the project file's hostname is `photos.alice.freepod.eu`
- **THEN** the client rewrites it to `photos`, saves the file, and says so

#### Scenario: A development hostname is rewritten

- **WHEN** the project file's hostname is `notes.bob.dev.freepod.eu`
- **THEN** the client rewrites it to `notes`

#### Scenario: Other hostnames are untouched

- **WHEN** the project file's hostname is `photos`, `photos-alice.freepod.app`,
  `grafana.freepod.eu`, or `photos.example.com`
- **THEN** the client leaves it unchanged

## REMOVED Requirements

### Requirement: The hostname is re-checked only when it changes
**Reason**: The client no longer completes a bare label; the platform does.
**Migration**: See *A hostname is sent as entered and re-checked only when it changes*.
