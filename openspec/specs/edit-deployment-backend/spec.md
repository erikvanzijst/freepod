# edit-deployment-backend Specification

## Purpose

The service behind `PUT /api/users/{uid}/deployments/{id}`: which template versions an update may target, and the deployment states it may be applied in.

## Overview

```
User clicks Update
       |
       v
 PUT /deployments/{id}
       |
       v
 UPDATE deployments
 SET user_values_json = ...,
     status = 'provisioning',
     generation = generation + 1
 WHERE id = ? AND status = 'ready'    <-- atomic guard
       |
       +-- rows affected = 1 --> success, enqueue reconcile
       +-- rows affected = 0 --> 409 Conflict
```

```
Template version check (relaxed):

  desired_template_id < current   --> REJECT (downgrade)
  desired_template_id = current   --> ALLOW  (value-only edit)  [NEW]
  desired_template_id > current   --> ALLOW  (upgrade)
```

## Requirements

### Requirement: Update deployment allows same template version
The `update_deployment()` service MUST allow updates where `desired_template_id` equals the deployment's current `desired_template_id`. It MUST still reject updates where the new `desired_template_id` is strictly less than the current one.

#### Scenario: Same-version value-only update
- **WHEN** a client sends `PUT /api/users/{user_id}/deployments/{deployment_id}` with the same `desired_template_id` as the deployment's current value and different `user_values_json`
- **THEN** the service accepts the update, re-derives the hostname, validates user values, sets status to `provisioning`, increments `generation`, and enqueues a reconcile job

#### Scenario: Template downgrade still rejected
- **WHEN** a client sends a PUT request with a `desired_template_id` that is strictly less than the deployment's current value
- **THEN** the service raises an IntegrityException and the deployment is not modified

#### Scenario: Template upgrade still accepted
- **WHEN** a client sends a PUT request with a `desired_template_id` that is strictly greater than the deployment's current value
- **THEN** the service accepts the update (existing behavior unchanged)

### Requirement: Update deployment requires ready status
An update that releases (see "An update releases only when the running app would change")
MUST atomically verify that the deployment's status is `ready` or `error` and that it is
not stopped for maintenance, and MUST be refused otherwise. An update that does not
release MUST be accepted in every status except `deleting` and `deleted`, and MUST NOT
change the status.

#### Scenario: Update deployment in ready state
- **WHEN** a client sends a PUT request that changes chart values for a deployment whose status is `ready`
- **THEN** the service applies the update and returns the updated deployment

#### Scenario: Update deployment in provisioning state
- **WHEN** a client sends a PUT request that changes chart values for a deployment whose status is `provisioning`
- **THEN** the API returns HTTP 409 Conflict and the deployment is not modified

#### Scenario: Update deployment in error state
- **WHEN** a client sends a PUT request for a deployment whose status is `error`
- **THEN** the service applies the update and creates a release

#### Scenario: Update deployment in deleting state
- **WHEN** a client sends a PUT request for a deployment whose status is `deleting`
- **THEN** the API returns HTTP 409 Conflict and the deployment is not modified

#### Scenario: Race condition with concurrent reconciler
- **WHEN** the reconciler changes a deployment's status from `ready` to `provisioning` between the user clicking Update and a releasing PUT request being processed
- **THEN** the conditional SQL update affects 0 rows and the API returns HTTP 409 Conflict

#### Scenario: Renaming while provisioning
- **WHEN** a client sends a PUT request that changes only the name of a deployment whose status is `provisioning`
- **THEN** the name is changed, the status stays `provisioning`, and no release is created

### Requirement: An update releases only when the running app would change

An update SHALL create a release and queue a reconcile when its chart values differ from
the deployment's stored ones, when it names another template, when it names a build,
when it carries vars, or when the deployment's status is `error`. Staged vars alone SHALL
NOT make an update release. Any other update SHALL change
only the deployment's row, and SHALL create no release and queue no reconcile.

#### Scenario: Only the name changes

- **WHEN** an update changes only `name` on a `ready` deployment
- **THEN** no release is created and no reconcile is queued

#### Scenario: Chart values and a build in one release

- **WHEN** an update changes `auth`, names a build and carries its image
- **THEN** exactly one release is created, running that image with the new `auth`

#### Scenario: Staged vars

- **WHEN** an update with unchanged values names the build the deployment runs, and the
  deployment's vars are pending
- **THEN** a release is created from the current image and the vars take effect

#### Scenario: Renaming with staged vars

- **WHEN** an update changes only `name` on a deployment whose vars are pending, whether
  it is `ready` or `provisioning`
- **THEN** no release is created, and the vars stay pending

#### Scenario: Retrying a failed deployment

- **WHEN** an update with unchanged values is sent to a deployment in `error`
- **THEN** a release is created and a reconcile is queued

### Requirement: An update carries the deployment's identity

The update SHALL accept optional `name`, `description` and `icon`, validated as
deployment-identity requires. A field left out SHALL keep its value, and a null
`description` or `icon` SHALL clear it. `desired_template_id` SHALL become optional,
defaulting to the deployment's current one, so that an identity-only update need not
name a template.

#### Scenario: A rename from the dashboard

- **WHEN** the owner sends an update holding only `name`
- **THEN** the deployment is renamed, its chart values are unchanged and no release is created
