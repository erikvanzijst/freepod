# Spec Delta

## ADDED Requirements

### Requirement: Every deployment records its class or none

Every deployment SHALL record the StorageClass its volumes are provisioned on, or none. A deployment that records none SHALL have its volumes rendered exactly as its chart renders them. Deployments that existed before the platform recorded classes SHALL record none until the class is recorded for them.

#### Scenario: An existing deployment after the upgrade

- **WHEN** the platform is upgraded to record classes
- **THEN** every existing deployment records no storage class, and its next reconcile renders the same volume specs as before

#### Scenario: A new deployment in an environment that names no class

- **WHEN** a deployment is created in an environment that names no class for new deployments
- **THEN** the deployment records no storage class, and its volumes are rendered as its chart renders them

### Requirement: The environment chooses the class at creation

When a deployment is created, the platform SHALL set its storage class to the class the environment names for new deployments, or to none when the environment names none. Neither the owning account nor the account that creates the deployment SHALL influence the choice.

#### Scenario: A new deployment on prod

- **WHEN** any account creates a deployment on an environment that names `ceph-freepod`
- **THEN** the deployment records `ceph-freepod`

#### Scenario: An administrator creates for another account

- **WHEN** an administrator creates a deployment owned by another account on an environment that names `ceph-freepod`
- **THEN** the deployment records `ceph-freepod`

#### Scenario: The environment's class changes

- **WHEN** an operator changes the class the environment names for new deployments
- **THEN** existing deployments keep the class they recorded, and only deployments created afterwards record the new one

### Requirement: The environment's class is one it allows

Each environment SHALL list the StorageClasses its deployments may record, and the class it names for new deployments SHALL be on that list. The platform SHALL refuse to start when it is not. A create that would record a class not on the list SHALL be refused, naming the class, with nothing persisted. Every class is visible cluster-wide, so this keeps one environment out of another's pool.

#### Scenario: Dev configured with the prod class

- **WHEN** the dev platform names `ceph-freepod` for new deployments but allows only `ceph-freepod-dev`
- **THEN** the platform refuses to start, naming `ceph-freepod`

#### Scenario: A class that is not allowed at create

- **WHEN** a create would record a class the environment does not allow
- **THEN** the create is refused, naming the class, and no deployment, release or subscription row is stored

## REMOVED Requirements

### Requirement: A deployment records its storage class

**Reason**: Its scenario for a new deployment ties "no class" to the owner's account. That no longer holds, so the requirement is replaced by "Every deployment records its class or none".
**Migration**: None; the behavior for existing deployments is unchanged.

### Requirement: The class is chosen once, at creation

**Reason**: The class now comes from the environment rather than the owner's account. It is replaced by "The environment chooses the class at creation".
**Migration**: Operators set `CAELUS_STORAGE_CLASS` per environment instead of flagging accounts.

### Requirement: Only allowed classes are chosen

**Reason**: With no account flag left, the allowlist now checks the environment's own class. It is replaced by "The environment's class is one it allows".
**Migration**: None; `CAELUS_STORAGE_CLASSES` keeps its meaning.

### Requirement: An account's class is an operator setting

**Reason**: Every new deployment now records the environment's class, so a per-account opt-in has nothing left to select.
**Migration**: None for users; the flag was never exposed. Operators stop setting `user.storage_class`, and the column is dropped. Deployments created while it was set keep the class they recorded.
