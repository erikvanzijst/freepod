# Spec Delta

## MODIFIED Requirements

### Requirement: The migration is an operator script

The migration SHALL be a script run by an operator inside the platform, not an API, `caelus` or UI operation. It SHALL move one deployment per run, onto one of the environment's allowed classes. When the operator names none, it SHALL use the class the environment names for new deployments, or the only allowed class when the environment names none.

#### Scenario: Listing what is left

- **WHEN** the operator runs `plan`
- **THEN** it lists the deployments with volumes on `local-path`, their claims and sizes, and the volumes earlier runs kept

#### Scenario: A class the environment does not allow

- **WHEN** the operator names a class not on the environment's list
- **THEN** the run refuses before changing anything

#### Scenario: No class named

- **WHEN** the operator names no class on an environment that names `ceph-freepod` for new deployments
- **THEN** the run moves the deployment onto `ceph-freepod`
