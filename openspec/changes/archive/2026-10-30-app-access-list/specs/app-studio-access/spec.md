# Spec Delta

## ADDED Requirements

### Requirement: The owner and the people they list are allowed

An App Studio template SHALL set `auth.enabled: true` and `auth.access: listed` as system values and offer neither in its user values. Only the deployment's owner and the people on its access list SHALL reach the studio or its preview. With an empty list, which is how every studio starts, only the owner SHALL reach either hostname.

#### Scenario: Owner signs in

- **WHEN** the deployment's owner signs in on the studio's hostname
- **THEN** the studio loads

#### Scenario: Another account signs in

- **WHEN** a Freepod account that is neither the owner nor listed signs in on the studio or preview hostname
- **THEN** it is refused and sees a page saying it has no access

#### Scenario: The owner lists someone

- **WHEN** the owner adds Sam to the studio's access list and Sam signs in on the studio's hostname
- **THEN** the studio loads for Sam

#### Scenario: User values cannot widen access

- **WHEN** a deployment's user values try to set `auth.access: anyone`
- **THEN** schema validation rejects them

### Requirement: No verifier, no studio

The chart SHALL fail to render when the platform has not injected the verifier's address, or when its values do not set `auth.enabled: true`, `auth.protocol: header` and `auth.access: listed`, rather than serve either hostname with weaker access control.

#### Scenario: Verifier address missing

- **WHEN** an App Studio deployment is rendered without the verifier's address
- **THEN** rendering fails and the previous release keeps serving

#### Scenario: Open access

- **WHEN** an App Studio deployment is rendered with `auth.access: anyone`
- **THEN** rendering fails

## REMOVED Requirements

### Requirement: Only the owner is allowed

**Reason**: The studio now uses the platform's access list, which always admits the owner and also admits anyone the owner lists. The owner-only list in the edge configuration is gone.

**Migration**: The template sets `auth.access: listed`. Existing studios have empty lists, so they admit only their owners, as before.

### Requirement: No owner, no studio

**Reason**: The owner is recognized from the platform's records, not from an injected email, so the chart no longer needs the owner's email to restrict access.

**Migration**: Replaced by *No verifier, no studio*.
