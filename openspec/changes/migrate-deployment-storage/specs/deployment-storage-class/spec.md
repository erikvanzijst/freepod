# Spec Delta

## MODIFIED Requirements

### Requirement: The class never changes through the API

No API, CLI or UI operation SHALL accept a storage class as input, report a deployment's storage class, or change it after creation. Updating values or vars, moving to another template version, stopping, starting and redeploying SHALL all keep the class the deployment was created with. Only the operator's storage migration (`deployment-storage-migration`) SHALL change a recorded class.

#### Scenario: A template upgrade

- **WHEN** an administrator moves a deployment that records `ceph-freepod` to a newer template version whose chart adds a volume
- **THEN** the deployment still records `ceph-freepod`, and the new volume is provisioned on it

#### Scenario: A create that tries to choose

- **WHEN** a create or update request carries a storage class field
- **THEN** the field has no effect on the deployment's storage class

#### Scenario: A migrated deployment

- **WHEN** the operator migrates a deployment that records no class onto `ceph-freepod`
- **THEN** the deployment records `ceph-freepod`
