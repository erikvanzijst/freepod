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
The `update_deployment()` service MUST atomically verify that the deployment's status is `ready` before applying changes. If the deployment is not in `ready` status at the time of the SQL update, the service MUST reject the request.

#### Scenario: Update deployment in ready state
- **WHEN** a client sends a PUT request for a deployment whose status is `ready`
- **THEN** the service applies the update and returns the updated deployment

#### Scenario: Update deployment in provisioning state
- **WHEN** a client sends a PUT request for a deployment whose status is `provisioning`
- **THEN** the API returns HTTP 409 Conflict and the deployment is not modified

#### Scenario: Update deployment in error state
- **WHEN** a client sends a PUT request for a deployment whose status is `error`
- **THEN** the API returns HTTP 409 Conflict and the deployment is not modified

#### Scenario: Update deployment in deleting state
- **WHEN** a client sends a PUT request for a deployment whose status is `deleting`
- **THEN** the API returns HTTP 409 Conflict and the deployment is not modified

#### Scenario: Race condition with concurrent reconciler
- **WHEN** the reconciler changes a deployment's status from `ready` to `provisioning` between the user clicking Update and the PUT request being processed
- **THEN** the conditional SQL update affects 0 rows and the API returns HTTP 409 Conflict
