# Spec Delta

## Purpose

Moves an existing deployment's volumes from `local-path` onto its environment's storage class, one deployment at a time, by an operator. The deployment ends as one created on that class would be, its data verified, and the old volumes kept until the operator deletes them.

## ADDED Requirements

### Requirement: The migration is an operator script

The migration SHALL be a script run by an operator inside the platform, not an API, `caelus` or UI operation. It SHALL move one deployment per run, onto one of the environment's allowed classes, defaulting to the only one when there is exactly one.

#### Scenario: Listing what is left

- **WHEN** the operator runs `plan`
- **THEN** it lists the deployments with volumes on `local-path`, their claims and sizes, and the volumes earlier runs kept

#### Scenario: A class the environment does not allow

- **WHEN** the operator names a class not on the environment's list
- **THEN** the run refuses before changing anything

### Requirement: Nothing stops before the deployment is known to fit

Before stopping anything, a run SHALL render the release and refuse a deployment that:
- holds a claim the release does not render;
- has a claim on a class other than `local-path`, or one that is not bound or is a block volume;
- could mount a claim from two pods at once;
- has a StatefulSet that deletes its claims with it;
- uses more than 80% of a claim's rendered size.

A dry run SHALL perform these checks and report, changing nothing.

#### Scenario: A volume too full for its claim

- **WHEN** a claim's data exceeds 80% of the size its release renders
- **THEN** the run refuses, naming the claim, and the deployment keeps running

#### Scenario: A deployment without volumes

- **WHEN** the deployment's release renders no claims and no claim templates
- **THEN** the run records the class without stopping it

### Requirement: A migration can grow the deployment's plan

`migrate` SHALL accept another version of the deployment's plan, at the same price and billing interval, and refuse any other. It SHALL size the new claims by that version, measure the 80% limit against those sizes, and move the subscription to it only after the old claims are deleted, because a class that cannot grow a claim fails any release that tries. Without one, it SHALL size the claims by the subscription's current plan version, as the next reconcile renders them.

#### Scenario: A volume that outgrew its plan

- **WHEN** the operator migrates a deployment whose data exceeds its plan's size, naming a bigger version of the same plan
- **THEN** the new claims have the bigger size, and the subscription is on that version once the deployment runs again

#### Scenario: A version of another plan or price

- **WHEN** the operator names a plan version of another plan, or at another price
- **THEN** the run refuses before changing anything

#### Scenario: Rolling back a grown deployment

- **WHEN** the operator rolls back a deployment whose plan grew in its migration
- **THEN** it keeps the bigger plan, and its kept `local-path` volumes are recorded as big as the claims ask

### Requirement: The deployment is held for maintenance while its data moves

A run SHALL hold the deployment for maintenance and wait until no running pod uses its claims before copying. It SHALL delete finished pods that name one of the claims, because claim protection keeps a claim they name from being deleted. It SHALL release the hold only once every claim is bound to its new volume, and the deployment SHALL then return to the power it had before. If a copy fails, the run SHALL release the hold, and the deployment SHALL run on its old volumes as before.

#### Scenario: A deployment its owner had stopped

- **WHEN** a stopped deployment is migrated
- **THEN** it is stopped afterwards, with reason `manual`

#### Scenario: A finished pod names a claim

- **WHEN** a pod that ran before the hold has finished but still names one of the claims
- **THEN** the run deletes it before switching, and the old claim's deletion completes

#### Scenario: A copy that fails

- **WHEN** a volume does not fit on its new claim
- **THEN** the deployment is released from maintenance, still records no class, and runs on its old volumes

### Requirement: The copy is complete and verified

Each claim's data SHALL be copied with its owners, modes, hard links, ACLs and extended attributes, including the root directory's, and without the new filesystem's empty `lost+found`. A second, checksum-comparing pass SHALL find no difference, or the run SHALL fail. A rerun SHALL re-synchronize an earlier copy rather than reuse it unchecked.

#### Scenario: A world-writable root

- **WHEN** a `local-path` volume's root is mode 0777
- **THEN** the new volume's root is mode 0777

### Requirement: Claims keep their names and are owned as the release renders them

After a migration, each claim SHALL have its old name, the new class and `ReadWriteOncePod`, and SHALL be bound to the volume its data was copied to. Claims the release renders SHALL be created by the release. Claims of a StatefulSet SHALL be created from its claim template. The deployment SHALL record the new class.

#### Scenario: A Helm-owned claim

- **WHEN** a deployment whose chart renders a claim `data` is migrated
- **THEN** `data` is created by the release on the new class and bound to the copy

#### Scenario: A StatefulSet database

- **WHEN** a deployment whose database StatefulSet `db` has claim `pg-db-0` is migrated
- **THEN** the StatefulSet is recreated by the release with the new class in its claim template, and `pg-db-0` is bound to the copy

### Requirement: No reconcile can bind an empty volume

A new volume SHALL be reserved for its claim's name before the class is recorded, and the class SHALL be recorded before any old claim is deleted. A reconcile at any point of a run SHALL either render the old claims on the old volumes or bind the reserved copies.

#### Scenario: A run interrupted after the class is recorded

- **WHEN** a run stops after recording the class
- **THEN** the deployment stays held for maintenance, and running `migrate` again binds the reserved copies

### Requirement: A run resumes from where the last one stopped

A run SHALL work out its progress from the cluster and the database alone. It SHALL refuse to run while another run works on the same deployment.

#### Scenario: Two runs at once

- **WHEN** a second run starts on a deployment another run is migrating
- **THEN** it refuses

### Requirement: Old volumes are kept until cleanup

Every volume a run releases SHALL be kept, labeled with its deployment, its role and the claim it belonged to, and stamped with when it was released. `rollback` SHALL put a migrated deployment back on its kept `local-path` volumes in the same way, losing what was written since. `cleanup` SHALL delete released volumes older than a cutoff, 14 days by default, after confirmation, optionally for one deployment only.

#### Scenario: Rolling back

- **WHEN** the operator rolls back a migrated deployment
- **THEN** it records no class again, its claims are bound to the kept `local-path` volumes, and the copies are kept as released

#### Scenario: A claim created after the migration

- **WHEN** a migrated deployment has a claim with no kept `local-path` volume
- **THEN** rollback refuses

#### Scenario: Cleaning up

- **WHEN** the operator runs `cleanup` 14 days after a migration
- **THEN** the old `local-path` volumes are deleted along with their data

### Requirement: Kept volumes are scoped to the environment

`plan` and `cleanup` SHALL consider only volumes labeled with a deployment in their own environment's database, because environments may share a cluster. `plan` SHALL list only the kept volumes that no claim holds.

#### Scenario: Another environment's volumes

- **WHEN** dev and prod share a cluster and the operator runs `cleanup` in dev
- **THEN** no volume kept by a prod migration is listed or deleted

#### Scenario: A migrated deployment's live volumes

- **WHEN** the operator runs `plan` after a migration
- **THEN** the copies the deployment runs on are not listed
