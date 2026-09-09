## MODIFIED Requirements

### Requirement: The hostname is re-checked only when it changes

The client SHALL check the hostname against the platform only when it is new or has
changed relative to the recorded deployment. It SHALL NOT re-check an unchanged
hostname.

The platform's hostname check does not exclude the deployment that already holds the
name, so re-checking an unchanged hostname would report it as in use by its own
deployment. The check also performs live name resolution for hostnames outside the
platform's own domains, which is slow and can fail transiently.

A bare label in the project file SHALL be completed into an FQDN beneath the account's own
subdomain — `<label>.<subdomain>.<domain>` — rather than beneath a platform wildcard domain.
The client SHALL learn the subdomain and the domain from the platform at runtime and SHALL
NOT carry either as a constant. A value already containing a dot SHALL be treated as a
complete FQDN and left alone, so a custom domain still works.

#### Scenario: An unchanged hostname is not re-checked

- **WHEN** a deploy runs and the project file's hostname matches the deployment's
- **THEN** the client performs no hostname check

#### Scenario: A changed hostname is checked before packing

- **WHEN** the project file's hostname differs from the deployment's
- **THEN** the client checks it before packing
- **AND** stops with the reported reason when it is unusable

#### Scenario: A bare label completes under the account's address

- **WHEN** the project file's hostname is `photos`, the account holds `alice`, and the
  platform domain is `freepod.eu`
- **THEN** the client submits `photos.alice.freepod.eu`

#### Scenario: A full FQDN is left alone

- **WHEN** the project file's hostname is `photos.example.com`
- **THEN** the client submits it unchanged and the custom-domain path applies
