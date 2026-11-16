# Spec Delta

## MODIFIED Requirements

### Requirement: Each deployment is a row with a plain-language status
Each deployment SHALL be shown as a row with the deployment's own name and its
effective icon (its own, or else its product's), a status in plain words, the
deployment's address, its plan and price, its running version and an Open
action. A deployment in progress SHALL show a progress indicator. Open SHALL be
disabled until the app can be reached.

#### Scenario: Statuses in plain words
- **WHEN** deployments are `ready`, `pending`, `error` and `deleting`
- **THEN** their statuses read Running, Waiting for payment, Needs attention
  and Removing

#### Scenario: Applying changes
- **WHEN** a deployment is `provisioning` without changing version
- **THEN** its status reads "Applying changes"

#### Scenario: Update to a new version
- **WHEN** a deployment running 1.120.2 is `provisioning` toward 1.121.0
- **THEN** its status reads "Updating to 1.121.0" and Open stays available

#### Scenario: First setup
- **WHEN** a new deployment is `provisioning` for the first time
- **THEN** its status reads "Setting up" and Open is disabled

#### Scenario: Not reachable yet
- **WHEN** a deployment is waiting for payment or being removed
- **THEN** Open is disabled

#### Scenario: Plan and price
- **WHEN** a deployment is on the Personal plan at 4.99 euros a month
- **THEN** its row reads "Personal · €4.99/mo"

#### Scenario: Custom deployments are told apart
- **WHEN** an owner has Custom deployments named `Arkanoid` and `Recipes`, one with an icon of its own
- **THEN** the rows read `Arkanoid` and `Recipes`, not the product's name
- **AND** the one with its own icon shows it, the other the Custom product's

### Requirement: The list can be searched and sorted
The dashboard SHALL offer a search over each deployment's name, its app (the
same fields as the catalog search), address and plan name, and a sort by newest
first (the default), oldest first, name, or most recently updated. Both SHALL
be kept in the address (`search` and `sort`). Pressing `/` outside a text field
SHALL focus the search.

#### Scenario: Search by address
- **WHEN** a user searches their apps for part of a deployment's address
- **THEN** only deployments whose address or other searched fields contain
  it are listed

#### Scenario: Search by name
- **WHEN** a user searches for `ark`
- **THEN** a deployment named `Arkanoid` is listed

#### Scenario: Sort by name
- **WHEN** a user sorts by name
- **THEN** deployments are ordered by deployment name, then by address
