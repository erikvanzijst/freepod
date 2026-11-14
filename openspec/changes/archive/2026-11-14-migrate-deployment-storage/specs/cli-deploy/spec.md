# Spec Delta

## MODIFIED Requirements

### Requirement: Deploy waits for a deployment that is not ready to update

The platform accepts an update only while a deployment is settled. When the recorded
deployment is mid-rollout, the client SHALL wait, reporting the current status, until it
settles or the configured timeout elapses.

#### Scenario: An in-progress rollout is waited out

- **WHEN** the recorded deployment is provisioning at release time
- **THEN** the client waits, showing its status, and proceeds once it settles

#### Scenario: A conflicting update is reported for what it is

- **WHEN** the platform refuses the update because an operation is already in progress
- **THEN** the client reports that another operation is in progress

#### Scenario: A refusal is attributed by its reason, not by its status

- **WHEN** the platform refuses the release with a conflict status
- **THEN** the client reports the specific reason the platform gave
- **AND** suggests retrying only for the reasons a retry could resolve

#### Scenario: Stored values that no longer satisfy the target template are named as such

- **WHEN** the release is refused because the deployment's values fail the target
  template's schema
- **THEN** the client reports that the values no longer satisfy the template being moved
  to, naming the move
- **AND** does not present it as a transient conflict worth retrying

#### Scenario: A broken template schema is not blamed on the user

- **WHEN** the release is refused because the target template's own schema is invalid
- **THEN** the client reports a platform-side defect
- **AND** does not suggest the user change their configuration

#### Scenario: A hostname conflict at release is attributed correctly

- **WHEN** the platform refuses the update because the hostname is in use
- **THEN** the client reports that another deployment holds the hostname

#### Scenario: A release to a deployment held for maintenance

- **WHEN** the platform refuses the update with code `under_maintenance`
- **THEN** the client says the deployment is held for platform maintenance and is worth retrying later
- **AND** says the built image is reused by a re-run
